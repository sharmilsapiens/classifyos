"""LLM-authored per-row narratives on top of the SHAP explanations (Azure OpenAI).

:mod:`classifyos.analysis.explain` produces the *numbers* behind a single prediction —
the SHAP base value, each feature's signed contribution, and the additive landing point
(``base_value + Σ contributions == prediction``). Those numbers answer "which features moved
this prediction and by how much", but an underwriter or claims adjuster still has to read a
waterfall. This module turns the SAME numbers into a short plain-language paragraph — a
reason-code narrative — by asking an Azure OpenAI chat model to describe, for one row, how the
top features pushed the model toward (or away from) its prediction.

Design (mirrors the opt-in / lazy-import discipline of ``shap`` and ``optuna``):

* **Optional dependency, lazy import.** ``openai`` is imported only inside
  :func:`narrator_from_env`, so a run that does not ask for narratives never needs the package.
* **No new ML, no leakage surface.** This reads only the values SHAP already computed plus the
  (already model-space) feature values of the explained TEST rows. It fits nothing, trains
  nothing, and mutates no input. It is a *presentation* layer over the SHAP output.
* **Credentials from the environment.** The five ``AZURE_OPEN_AI_*`` variables are read from the
  process environment (the CLI / API load ``.env`` at startup; a standalone caller must too —
  the same convention as ``DATA_DIR`` / ``OUTPUT_DIR``). If any is missing, or the SDK/endpoint
  errors, narration degrades gracefully to ``None`` — exactly like a failed explainer — so the
  report-only step never aborts a run.

The narrator is fed the **original, un-scaled** row values (mapped back from the engineered SHAP
feature names via :func:`_resolve_feature_display`), plus whole-run context — dataset/domain
description (analyst-supplied and/or data-derived), class base rates, the model's headline
performance, and the global feature ranking — assembled once per model into a :class:`RunContext`
and carried in the system message. So a narrative can say *"num_late_payments = 3 pushed this
above the ~12% base rate"* instead of restating a scaled float. The stable context lives in the
system message (consistent framing across rows); only the row's own values live in the user
message. Calls are independent and I/O-bound, so :func:`narrate_rows` fans them out over a small
thread pool.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Azure OpenAI credential environment variables (as provided for this deployment).
ENV_ENDPOINT = "AZURE_OPEN_AI_ENDPOINT"
ENV_API_KEY = "AZURE_OPEN_AI_API_KEY"
ENV_API_VERSION = "AZURE_OPEN_AI_API_VERSION"
ENV_MODEL = "AZURE_OPEN_AI_MODEL"
ENV_DEPLOYMENT = "AZURE_OPEN_AI_DEPLOYMENT_NAME"

#: Top-N features (by |contribution|) handed to the model — the rest are summarised as a net
#: residual. Kept small so the narrative focuses on the handful of real drivers, not a long list.
DEFAULT_MAX_FEATURES = 5
#: Temperature is left UNSET by default (``None`` → not sent). Reasoning models (o1/o3/gpt-5)
#: only accept the default temperature and 400 on any explicit value; leaving it unset works for
#: those AND for the classic chat models. A caller may still pass a float (honoured by models that
#: support it; :meth:`AzureNarrator.narrate` transparently retries without it if the model rejects
#: it), but the default avoids a wasted round-trip on reasoning deployments.
DEFAULT_TEMPERATURE: float | None = None
#: Output-token budget, sent as ``max_completion_tokens`` (the modern parameter — ``max_tokens`` is
#: rejected by reasoning models). It is generous because reasoning models spend part of this budget
#: on hidden reasoning tokens; too small a value can starve the visible answer and return empty.
#: The context-rich prompt drives substantial reasoning (observed: gpt-5-mini spends up to ~1000
#: reasoning tokens before the ~150-token answer), so the budget is generous; a run that still
#: truncates (finish_reason == "length" with empty content) gets one automatic retry at 2x.
DEFAULT_MAX_COMPLETION_TOKENS = 4000
#: Per-request bounds so one slow/hung call cannot stall a run.
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2
#: How many narration calls run concurrently (thread pool). Calls are independent and I/O-bound
#: (network latency dominates), so a small pool cuts wall-clock time sharply while staying well
#: under typical Azure per-minute request limits.
DEFAULT_CONCURRENCY = 6
#: Global features listed to the model (top-K by importance) and sample rows fed for derived context.
_GLOBAL_FEATURE_TOP_K = 10
_DERIVED_SAMPLE_ROWS = 2

#: The fixed role/behaviour instructions. Dataset context, class base rates, model performance and
#: the global feature ranking are appended per model by :func:`build_system_message`.
#:
#: Deliberately prose-first: the SHAP contributions are given only so the model can rank the drivers
#: and get their direction right — it is told NOT to print the raw numbers, so the output reads like
#: an underwriter's note rather than a restated SHAP table.
_ROLE_INSTRUCTIONS = (
    "You are an insurance analyst explaining, in plain business language, why a model scored one "
    "case the way it did. You are given SHAP feature contributions (a signed number per feature: "
    "POSITIVE pushed the score TOWARD the stated class, NEGATIVE pushed it AWAY) and the row's "
    "ORIGINAL feature values. Use the contributions ONLY to decide which 2-3 features mattered most "
    "and in which direction.\n"
    "\n"
    "Write 2-4 flowing sentences for an underwriter. Rules:\n"
    "- Do NOT print the SHAP numbers, the base value, or 'feature = value (contribution +/-x)' style "
    "text. Describe influence qualitatively (strongly/slightly increased or decreased the likelihood).\n"
    "- Lead with whether the case is more or less likely than the population, comparing to the class "
    "base rate in words (e.g. 'well below the typical rate'), not as a raw probability.\n"
    "- Name only the 2-3 strongest drivers, referring to them by business meaning (use the dataset "
    "context / column meanings when given) and weaving in their value naturally.\n"
    "- Many categorical fields are stored as opaque integer CODES (e.g. a status or class code); treat "
    "such values as categories, never as quantities or amounts, and describe them qualitatively.\n"
    "- Never invent data or meanings beyond what is provided, never state the outcome as certain, and "
    "output a single short paragraph with no lists, headings, or numbers in parentheses."
)


@dataclass
class RunContext:
    """Whole-run context shared across every explained row of ONE model.

    Assembled once by the runner (:meth:`ModelRunner._build_run_context`) from data it already
    holds, then rendered into the system message so every narrative is framed against the same
    dataset meaning, class base rates, model performance and global feature ranking. Purely
    presentational — nothing here touches the ML.
    """

    problem_type: str
    target: str
    #: {class_label: proportion in the full dataset} — the population base rate per class.
    class_base_rates: dict[str, float] = field(default_factory=dict)
    #: This model's headline metrics, e.g. {"f1_weighted": 0.83, "accuracy": 0.86}.
    model_metrics: dict[str, float] = field(default_factory=dict)
    #: Global feature ranking as (feature, score) pairs, most important first (top-K).
    global_features: list[tuple[str, float]] = field(default_factory=list)
    #: Analyst free-text describing the dataset / target (used when context_mode != "derived").
    dataset_context: str = ""
    #: {column: note} analyst per-column meaning (used when context_mode != "derived").
    column_context: dict[str, str] = field(default_factory=dict)
    #: given | derived | both — how the above + derived facts reach the model.
    context_mode: str = "both"
    #: Data-derived per-column facts (dtype group + example values), used when mode != "given".
    derived_schema: list[str] = field(default_factory=list)
    #: A couple of raw sample rows ({column: value}) fed for derived context (mode != "given").
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    #: A short LLM-inferred description of the dataset/columns/target (the "primer"), produced once
    #: per run by :func:`derive_dataset_understanding` and reused across every row. Presented as a
    #: hypothesis, not ground truth. Empty in ``given`` mode or when the primer was unavailable.
    dataset_understanding: str = ""


class AzureNarrator:
    """A chat client bound to one Azure OpenAI deployment, used to narrate SHAP rows.

    Construct via :func:`narrator_from_env` in normal use; the explicit constructor exists so a
    test can inject a stub client (any object exposing ``chat.completions.create``) without a
    live endpoint.
    """

    def __init__(
        self,
        client: Any,
        deployment: str,
        *,
        model_label: str | None = None,
        temperature: float | None = DEFAULT_TEMPERATURE,
        max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
        max_features: int = DEFAULT_MAX_FEATURES,
    ) -> None:
        self.client = client
        self.deployment = deployment
        #: The underlying model name (from ``AZURE_OPEN_AI_MODEL``) — informational only; the
        #: chat call is keyed on the *deployment* name, per Azure OpenAI's API.
        self.model_label = model_label
        #: Optional; ``None`` → not sent (works for reasoning models that reject explicit values).
        self.temperature = temperature
        self.max_completion_tokens = max_completion_tokens
        self.max_features = max_features

    def _create(
        self,
        messages: list[dict[str, str]],
        *,
        with_temperature: bool,
        max_completion_tokens: int | None = None,
    ) -> Any:
        """Issue one chat completion, using the modern ``max_completion_tokens`` parameter.

        ``max_tokens`` is deliberately NOT used — reasoning models (o1/o3/gpt-5) reject it. The
        ``temperature`` is only attached when configured AND ``with_temperature`` is set, so a
        caller-supplied value can be dropped on a retry if the model rejects it.
        ``max_completion_tokens`` may be overridden (used to retry a length-truncated call).
        """
        kwargs: dict[str, Any] = {
            "model": self.deployment,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens or self.max_completion_tokens,
        }
        if self.temperature is not None and with_temperature:
            kwargs["temperature"] = self.temperature
        return self.client.chat.completions.create(**kwargs)

    def narrate(
        self,
        *,
        model_name: str,
        problem_type: str,
        target: str,
        explained_class: str,
        base_value: float,
        prediction: float,
        contributions: dict[str, float],
        original_row: dict[str, Any] | None = None,
        feature_values: dict[str, Any] | None = None,
        run_context: "RunContext | None" = None,
    ) -> str | None:
        """Return a plain-language paragraph for one explained row, or ``None`` on failure.

        Args:
            model_name: The ClassifyOS model whose prediction is being explained (e.g.
                ``"RandomForest"``) — used only to ground the wording.
            problem_type: ``"binary"`` | ``"multiclass"`` (multilabel is not narrated).
            target: The target column name (e.g. ``"will_lapse"``).
            explained_class: The class the SHAP waterfall describes.
            base_value: The SHAP base value (population-average model output).
            prediction: The row's predicted output (``base_value + Σ contributions``).
            contributions: ``{feature: signed SHAP contribution}`` for this row.
            original_row: Optional ``{original_column: raw value}`` for this row — the preferred,
                human-readable values (mapped from engineered SHAP names by
                :func:`_resolve_feature_display`).
            feature_values: Optional ``{feature: value}`` in model-space (fallback when a feature
                cannot be resolved to an original column).
            run_context: Optional :class:`RunContext` — dataset/domain context, class base rates,
                model performance and global feature ranking, rendered into the system message.

        A network/SDK error is logged and turned into ``None`` so the surrounding
        report-only step never aborts the run.
        """
        messages = _build_messages(
            model_name=model_name,
            problem_type=problem_type,
            target=target,
            explained_class=explained_class,
            base_value=base_value,
            prediction=prediction,
            contributions=contributions,
            original_row=original_row,
            feature_values=feature_values,
            run_context=run_context,
            max_features=self.max_features,
        )
        try:
            response = self._create(messages, with_temperature=True)
        except Exception as exc:  # noqa: BLE001 — report-only; a bad call must never kill the run
            # A model that rejects an explicit temperature (reasoning models) gets one retry
            # with it dropped; any other error is logged and degrades to no narrative.
            if self.temperature is not None and "temperature" in str(exc).lower():
                try:
                    response = self._create(messages, with_temperature=False)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "AzureNarrator: chat completion failed for model %r (deployment %r)",
                        model_name,
                        self.deployment,
                    )
                    return None
            else:
                logger.exception(
                    "AzureNarrator: chat completion failed for model %r (deployment %r)",
                    model_name,
                    self.deployment,
                )
                return None

        text, finish = _content_and_finish(response)
        # A reasoning model can spend the whole budget on hidden reasoning and return empty with
        # finish_reason == "length"; retry once at double the budget before giving up.
        if not text and finish == "length":
            try:
                response = self._create(
                    messages,
                    with_temperature=self.temperature is not None,
                    max_completion_tokens=self.max_completion_tokens * 2,
                )
                text, _ = _content_and_finish(response)
            except Exception:  # noqa: BLE001 — report-only
                logger.exception(
                    "AzureNarrator: length-retry failed for model %r", model_name
                )
                return None
        return text or None


def narrator_from_env(
    *,
    temperature: float | None = DEFAULT_TEMPERATURE,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    max_features: int = DEFAULT_MAX_FEATURES,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> AzureNarrator | None:
    """Build an :class:`AzureNarrator` from the ``AZURE_OPEN_AI_*`` environment variables.

    Returns ``None`` (with a single explanatory log line) when any required credential is
    absent or the SDK cannot be constructed, so an enabled-but-unconfigured run simply ships
    SHAP without narratives rather than failing. The ``openai`` package is imported lazily here,
    so it is only required when narration is actually requested.
    """
    # ``.strip()`` so a stray leading/trailing space in a ``.env`` value (e.g. ``KEY= value``)
    # doesn't produce a malformed endpoint/key.
    endpoint = (os.environ.get(ENV_ENDPOINT) or "").strip() or None
    api_key = (os.environ.get(ENV_API_KEY) or "").strip() or None
    api_version = (os.environ.get(ENV_API_VERSION) or "").strip() or None
    deployment = (os.environ.get(ENV_DEPLOYMENT) or "").strip() or None
    model_label = (os.environ.get(ENV_MODEL) or "").strip() or None

    missing = [
        name
        for name, value in (
            (ENV_ENDPOINT, endpoint),
            (ENV_API_KEY, api_key),
            (ENV_API_VERSION, api_version),
            (ENV_DEPLOYMENT, deployment),
        )
        if not value
    ]
    if missing:
        logger.warning(
            "LLM narratives requested but these env vars are unset: %s; shipping SHAP only",
            ", ".join(missing),
        )
        return None

    try:
        from openai import AzureOpenAI  # lazy — only needed when narration is requested
    except ImportError:
        logger.warning("LLM narratives requested but the 'openai' package is not installed")
        return None

    try:
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
            timeout=timeout,
            max_retries=max_retries,
        )
    except Exception:  # noqa: BLE001 — a bad endpoint/config must not abort the run
        logger.exception("Failed to construct AzureOpenAI client; shipping SHAP only")
        return None

    return AzureNarrator(
        client,
        str(deployment),
        model_label=model_label,
        temperature=temperature,
        max_completion_tokens=max_completion_tokens,
        max_features=max_features,
    )


def _top_features(
    contributions: dict[str, float], max_features: int
) -> tuple[list[tuple[str, float]], float]:
    """Return the ``max_features`` largest-|contribution| features and the residual of the rest.

    The residual (sum of the omitted contributions) keeps the prompt honest — the model is told
    how much signed push was folded away — without listing every engineered column.
    """
    ordered = sorted(contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)
    head = ordered[:max_features]
    residual = sum(v for _, v in ordered[max_features:])
    return head, residual


def _resolve_feature_display(
    feature: str, original_row: dict[str, Any] | None
) -> tuple[str, str | None]:
    """Map one engineered SHAP feature to a human ``(label, value)`` using the raw row.

    * The feature name is itself a raw column (numeric / ordinal / target / freq / binary) →
      ``(feature, original value)``.
    * A one-hot column ``f"{col}_{cat}"`` whose ``col`` is a raw column → ``(col, raw value of
      col)`` (the longest matching original-column prefix wins, so ``a_b_c`` maps to column
      ``a_b`` before ``a`` when both exist).
    * Otherwise (interaction / derived feature with no raw source) → ``(feature, None)`` so the
      caller shows the contribution without a fabricated value.
    """
    if not original_row:
        return feature, None
    if feature in original_row:
        return feature, _fmt(original_row[feature])
    prefixes = [c for c in original_row if isinstance(c, str) and feature.startswith(c + "_")]
    if prefixes:
        col = max(prefixes, key=len)  # longest matching original column name
        return col, _fmt(original_row[col])
    return feature, None


def _build_messages(
    *,
    model_name: str,
    problem_type: str,
    target: str,
    explained_class: str,
    base_value: float,
    prediction: float,
    contributions: dict[str, float],
    original_row: dict[str, Any] | None,
    feature_values: dict[str, Any] | None,
    run_context: "RunContext | None",
    max_features: int,
) -> list[dict[str, str]]:
    """Assemble the (system, user) chat messages for one row.

    The system message carries the shared :class:`RunContext` (or the bare role instructions when
    none is given); the user message carries this row's predicted output and its top features with
    their ORIGINAL values (falling back to the model-space value only when a feature can't be
    resolved to a raw column).
    """
    head, residual = _top_features(contributions, max_features)
    scaled = feature_values or {}

    lines: list[str] = []
    for feature, contrib in head:
        direction = "increased" if contrib > 0 else "decreased"
        label, value = _resolve_feature_display(feature, original_row)
        if value is None and feature in scaled:  # fallback: model-space value
            value = _fmt(scaled[feature])
        value_txt = f" = {value}" if value is not None else ""
        lines.append(
            f"- {label}{value_txt}: {direction} the prediction (contribution {contrib:+.4f})"
        )
    if abs(residual) > 1e-9:
        lines.append(f"- All other features combined: net contribution {residual:+.4f}")

    user = (
        f"Model: {model_name} ({problem_type} classification of '{target}').\n"
        f"Predicted class explained: {explained_class}.\n"
        f"Population-average model output (base value): {base_value:.4f}.\n"
        f"This row's model output for that class: {prediction:.4f}.\n"
        f"Feature contributions (SHAP), most influential first:\n"
        + "\n".join(lines)
    )
    system = build_system_message(run_context) if run_context is not None else _ROLE_INSTRUCTIONS
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_system_message(ctx: "RunContext") -> str:
    """Render the role instructions + whole-run context into the system message.

    Included per :attr:`RunContext.context_mode`: the analyst dataset/column context (``given`` /
    ``both``) and/or the data-derived schema + sample rows (``derived`` / ``both``); always the
    class base rates, this model's performance, and the global feature ranking.
    """
    parts: list[str] = [_ROLE_INSTRUCTIONS, ""]

    if ctx.class_base_rates:
        rates = ", ".join(f"{k}={v:.1%}" for k, v in ctx.class_base_rates.items())
        parts.append(f"Target '{ctx.target}' class base rates (population): {rates}.")
    if ctx.model_metrics:
        metrics = ", ".join(f"{k}={v:.3f}" for k, v in ctx.model_metrics.items())
        parts.append(f"This model's overall performance: {metrics}.")
    if ctx.global_features:
        feats = ", ".join(f for f, _ in ctx.global_features)
        parts.append(f"Globally most important features across the test set: {feats}.")

    include_given = ctx.context_mode in ("given", "both")
    include_derived = ctx.context_mode in ("derived", "both")

    # Analyst-provided context is authoritative and comes first; the inferred primer follows,
    # explicitly flagged as a hypothesis so the model leans on the analyst text when both exist.
    if include_given and ctx.dataset_context.strip():
        parts.append("\nDataset context (provided by the analyst):\n" + ctx.dataset_context.strip())
    if include_given and ctx.column_context:
        col_lines = "\n".join(
            f"- {col}: {note}" for col, note in ctx.column_context.items() if note.strip()
        )
        if col_lines:
            parts.append("\nColumn meanings (provided by the analyst):\n" + col_lines)

    if include_derived and ctx.dataset_understanding.strip():
        parts.append(
            "\nModel-inferred dataset understanding (a hypothesis from the data, not ground "
            "truth — defer to any analyst context above):\n" + ctx.dataset_understanding.strip()
        )
    if include_derived and ctx.derived_schema:
        parts.append("\nColumn facts (derived from the data):\n" + "\n".join(ctx.derived_schema))
    if include_derived and ctx.sample_rows:
        sample_lines = []
        for i, row in enumerate(ctx.sample_rows, start=1):
            cells = ", ".join(f"{k}={_fmt(v)}" for k, v in row.items())
            sample_lines.append(f"row {i}: {cells}")
        parts.append(
            "\nSample rows from the dataset (for context; not the row being explained):\n"
            + "\n".join(sample_lines)
        )

    return "\n".join(parts)


def narrate_rows(
    narrator: AzureNarrator,
    jobs: list[dict[str, Any]],
    *,
    max_workers: int = DEFAULT_CONCURRENCY,
) -> dict[Any, str | None]:
    """Narrate many rows concurrently, returning ``{job["key"]: narrative | None}``.

    Each ``job`` is ``{"key": <hashable id>, "params": {<narrate kwargs>}}``. Calls run on a
    bounded thread pool (they are independent, I/O-bound network calls); results are keyed by
    ``job["key"]`` so attachment is deterministic regardless of completion order. A per-job
    failure is caught and stored as ``None`` — one bad row never aborts the batch.
    """
    if not jobs:
        return {}
    results: dict[Any, str | None] = {}
    workers = max(1, min(max_workers, len(jobs)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_key = {
            pool.submit(narrator.narrate, **job["params"]): job["key"] for job in jobs
        }
        for future in concurrent.futures.as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception:  # noqa: BLE001 — report-only; one bad row never aborts the batch
                logger.exception("narrate_rows: job %r failed", key)
                results[key] = None
    return results


_PRIMER_SYSTEM = (
    "You are a data analyst. Given a dataset's target, class balance, per-column facts and a couple "
    "of sample rows, infer in 2-4 sentences what the dataset is about, what the target likely means "
    "(including what the explained class represents), and the likely business meaning of the most "
    "important columns. Be concise and hedge appropriately ('likely', 'appears to') — this is an "
    "inference from structure, not ground truth. Do not restate raw numbers; write plain prose."
)


def derive_dataset_understanding(
    narrator: AzureNarrator, ctx: "RunContext", *, global_features: list[str] | None = None
) -> str | None:
    """One LLM call inferring what the dataset/target/columns mean, for reuse across all rows.

    Uses the same client as the narrator. Returns a short paragraph, or ``None`` when there is
    nothing to infer from (no schema/sample rows) or the call fails — report-only, so a missing
    primer just leaves narratives at their no-primer behaviour. This is the "derived context"
    seed: it gives the row narrator semantics even when the analyst supplied none.
    """
    if not ctx.derived_schema and not ctx.sample_rows:
        return None

    lines = [f"Target column: '{ctx.target}' ({ctx.problem_type} classification)."]
    if ctx.class_base_rates:
        rates = ", ".join(f"{k}={v:.1%}" for k, v in ctx.class_base_rates.items())
        lines.append(f"Class base rates: {rates}.")
    feats = global_features or [f for f, _ in ctx.global_features]
    if feats:
        lines.append("Most important columns (by the model): " + ", ".join(feats) + ".")
    if ctx.derived_schema:
        lines.append("Column facts:\n" + "\n".join(ctx.derived_schema))
    if ctx.sample_rows:
        sample_lines = [
            "row {}: {}".format(i, ", ".join(f"{k}={_fmt(v)}" for k, v in row.items()))
            for i, row in enumerate(ctx.sample_rows, start=1)
        ]
        lines.append("Sample rows:\n" + "\n".join(sample_lines))

    messages = [
        {"role": "system", "content": _PRIMER_SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]
    try:
        response = narrator._create(messages, with_temperature=narrator.temperature is not None)
    except Exception:  # noqa: BLE001 — report-only; a failed primer must not abort the run
        logger.exception("derive_dataset_understanding: primer call failed")
        return None
    text, finish = _content_and_finish(response)
    if not text and finish == "length":
        try:
            response = narrator._create(
                messages,
                with_temperature=narrator.temperature is not None,
                max_completion_tokens=narrator.max_completion_tokens * 2,
            )
            text, _ = _content_and_finish(response)
        except Exception:  # noqa: BLE001
            logger.exception("derive_dataset_understanding: length-retry failed")
            return None
    return text or None


def _content_and_finish(response: Any) -> tuple[str | None, str | None]:
    """Extract ``(stripped content or None, finish_reason or None)`` from a chat completion."""
    try:
        choice = response.choices[0]
        text = choice.message.content
        finish = getattr(choice, "finish_reason", None)
    except (AttributeError, IndexError, TypeError):
        logger.warning("AzureNarrator: unexpected completion shape; no narrative")
        return None, None
    text = text.strip() if isinstance(text, str) and text.strip() else None
    return text, finish


def _fmt(value: Any) -> str:
    """Compactly format a feature value for the prompt (round floats; str() otherwise)."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
