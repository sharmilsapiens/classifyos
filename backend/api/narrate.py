"""Off-cluster LLM reason-code narration for a STORED run (Databricks backend).

Why this exists
---------------
LLM narratives (schema 1.7 — ``result.explanations[model].rows[].narrative``) are normally generated
by the engine DURING the run (``ModelRunner._add_llm_narratives``). On the **databricks** execution
backend the run executes on the CLUSTER, which cannot reach the Azure OpenAI endpoint — it is locked
to a private endpoint, so every call fails with a 403 "Public access is disabled". FastAPI CAN reach
it (that is why local narration works). So on Databricks the engine writes SHAP + a side artifact
(``api/narration_context.json``) and skips the call (``CLASSIFYOS_NARRATE_IN_ENGINE=false``); this
module does the narration off-cluster, from the run's persisted ``/run`` envelope + that side artifact.

Full context parity
--------------------
:func:`narrate_envelope` rebuilds the **same** :class:`~classifyos.analysis.llm_explain.RunContext`
the engine would have used, sourcing every field from data it already has:

* ``problem_type`` / ``target`` / ``class_base_rates`` — from ``result.run`` (base rates are the
  ``class_distribution`` counts normalised to proportions, exactly as the engine derives them);
* per-model ``model_metrics`` — from ``result.models`` (F1-weighted + accuracy);
* ``global_features`` — from ``result.permutation_importance`` (model-agnostic), falling back to
  ``result.feature_impact`` (composite score) — the same preference order as the engine;
* the SHAP rows (``base_value`` / ``prediction`` / ``contributions`` / ``feature_values``) — from
  ``result.explanations``;
* ``dataset_context`` / ``column_context`` / ``context_mode`` and the data-derived ``derived_schema``
  / ``sample_rows`` — from the ``narration_context`` side artifact (the only fields not in the envelope).

It then computes the one-per-run "primer" (:func:`derive_dataset_understanding`) and narrates every
row (:func:`narrate_rows`), attaching each ``narrative`` back onto a DEEP COPY of the envelope. It
**reuses the engine narrator entirely** — no new ML, no re-implemented prompt logic.

Report-only
-----------
Absent credentials (``narrator_from_env`` → ``None``), absent context artifact, an unsupported
problem type (multilabel), or ANY failure returns the envelope UNCHANGED with a zero count — the
route then returns it verbatim (never a 500). Presentational only; no leakage surface.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)


def narrate_envelope(
    envelope: dict[str, Any], narration_context: dict[str, Any] | None
) -> tuple[dict[str, Any], int]:
    """Narrate every SHAP row of ``envelope`` off-cluster; return ``(envelope, n_attached)``.

    Returns the ORIGINAL envelope unchanged with ``0`` when there is nothing to narrate, credentials
    are absent, the context artifact is missing, or anything fails (report-only — never raises). When
    at least one narrative is produced, returns a DEEP COPY with the narratives attached (the caller
    persists that copy so a reload shows them). The engine narrator does all the work.
    """
    try:
        return _narrate(envelope, narration_context)
    except Exception:  # noqa: BLE001 — report-only; a narration failure must never 500 the route
        logger.exception("narrate_envelope failed; returning the envelope unchanged")
        return envelope, 0


def _narrate(
    envelope: dict[str, Any], narration_context: dict[str, Any] | None
) -> tuple[dict[str, Any], int]:
    """The real work (wrapped by :func:`narrate_envelope` for the report-only guarantee)."""
    # Reuse the engine narrator ENTIRELY — no new prompt/ML logic here.
    from classifyos.analysis.llm_explain import (  # noqa: PLC0415 — lazy (openai only when narrating)
        _GLOBAL_FEATURE_TOP_K,
        RunContext,
        derive_dataset_understanding,
        narrate_rows,
        narrator_from_env,
    )

    result = (envelope or {}).get("result") or {}
    explanations = result.get("explanations") or {}
    if not explanations:
        return envelope, 0  # no SHAP rows → nothing to narrate
    if not narration_context:
        return envelope, 0  # no side artifact → cannot reach full parity → leave unchanged

    run = result.get("run") or {}
    problem_type = run.get("problem_type") or "binary"
    if problem_type == "multilabel":  # multilabel is never narrated (mirrors the engine)
        return envelope, 0

    narrator = narrator_from_env()  # reads FastAPI's AZURE_OPEN_AI_* creds; None if unconfigured
    if narrator is None:
        return envelope, 0

    target = run.get("target") or ""
    feature_cols = list(narration_context.get("feature_cols") or run.get("features") or [])

    # class base rates: normalise the raw class_distribution counts to proportions (the engine reads
    # value_counts(normalize=True) off the raw frame — the same population distribution).
    dist = run.get("class_distribution") or {}
    total = float(sum(v for v in dist.values() if isinstance(v, (int, float)))) or 0.0
    class_base_rates = (
        {str(k): float(v) / total for k, v in dist.items() if isinstance(v, (int, float))}
        if total
        else {}
    )

    models_by_name = {m.get("name"): m for m in (result.get("models") or []) if m.get("name")}

    def _model_metrics(name: str) -> dict[str, float]:
        row = models_by_name.get(name) or {}
        out: dict[str, float] = {}
        for key in ("f1_weighted", "accuracy"):
            value = row.get(key)
            if isinstance(value, (int, float)):
                out[key] = float(value)
        return out

    perm = result.get("permutation_importance") or {}
    feature_impact = result.get("feature_impact") or []

    def _global_features(name: str | None) -> list[tuple[str, float]]:
        """Top-K global features — permutation importance first, else the feature-impact composite
        (the SAME preference order as ``ModelRunner._global_features``)."""
        rows = perm.get(name) if name else None
        if rows:
            ranked = sorted(rows, key=lambda r: (r.get("importance") or 0.0), reverse=True)
            return [
                (str(r["feature"]), float(r.get("importance") or 0.0))
                for r in ranked[:_GLOBAL_FEATURE_TOP_K]
            ]
        if feature_impact:
            ranked = sorted(
                feature_impact, key=lambda r: (r.get("composite_score") or 0.0), reverse=True
            )
            return [
                (str(r["feature"]), float(r["composite_score"]))
                for r in ranked[:_GLOBAL_FEATURE_TOP_K]
                if r.get("composite_score") is not None
            ]
        return []

    context_mode = narration_context.get("context_mode", "both")
    dataset_context = narration_context.get("dataset_context", "") or ""
    column_context = narration_context.get("column_context", {}) or {}
    derived_schema = list(narration_context.get("derived_schema") or [])
    sample_ctx_rows = list(narration_context.get("sample_rows") or [])

    # One-time primer (mirrors the engine): infer dataset/target meaning from the derived facts so
    # every row is framed consistently, even when the analyst supplied no context. Derived/both only.
    dataset_understanding = ""
    if context_mode in ("derived", "both"):
        first_model = next(iter(explanations), None)
        hint_features = [f for f, _ in _global_features(first_model)]
        primer_ctx = RunContext(
            problem_type=problem_type,
            target=target,
            class_base_rates=class_base_rates,
            context_mode=context_mode,
            derived_schema=derived_schema,
            sample_rows=sample_ctx_rows,
        )
        dataset_understanding = (
            derive_dataset_understanding(narrator, primer_ctx, global_features=hint_features) or ""
        )

    contexts: dict[str, RunContext] = {}

    def _context_for(name: str) -> RunContext:
        if name not in contexts:
            contexts[name] = RunContext(
                problem_type=problem_type,
                target=target,
                class_base_rates=class_base_rates,
                model_metrics=_model_metrics(name),
                global_features=_global_features(name),
                dataset_context=dataset_context,
                column_context=column_context,
                context_mode=context_mode,
                derived_schema=derived_schema,
                sample_rows=sample_ctx_rows,
                dataset_understanding=dataset_understanding,
            )
        return contexts[name]

    # Build one narration job per (model, explained row). The row's ORIGINAL feature values live in
    # the envelope (schema 1.8 ``feature_values``); reconstruct the raw-column-keyed ``original_row``
    # the engine passes so the prompt shows "source_column = value" (one-hot → its source column).
    jobs: list[dict[str, Any]] = []
    for name, model_expl in explanations.items():
        rows = (model_expl or {}).get("rows") or []
        run_context = _context_for(name)
        for row in rows:
            original_row = _reconstruct_original_row(row.get("feature_values") or {}, feature_cols)
            jobs.append(
                {
                    "key": (name, row["sample_index"]),
                    "params": {
                        "model_name": name,
                        "problem_type": problem_type,
                        "target": target,
                        "explained_class": row["explained_class"],
                        "base_value": row["base_value"],
                        "prediction": row["prediction"],
                        "contributions": row["contributions"],
                        "original_row": original_row,
                        "run_context": run_context,
                    },
                }
            )

    narratives = narrate_rows(narrator, jobs)

    # Attach onto a DEEP COPY so a partial/failed batch never mutates the caller's envelope.
    narrated = copy.deepcopy(envelope)
    n_attached = 0
    for name, model_expl in (narrated["result"]["explanations"] or {}).items():
        for row in model_expl.get("rows") or []:
            text = narratives.get((name, row["sample_index"]))
            if text:
                row["narrative"] = text
                n_attached += 1

    logger.info("narrate_envelope: attached %d LLM narrative(s)", n_attached)
    return (narrated, n_attached) if n_attached else (envelope, 0)


def _reconstruct_original_row(
    feature_values: dict[str, Any], feature_cols: list[str]
) -> dict[str, Any] | None:
    """Rebuild a raw-column-keyed ``original_row`` from the envelope's ``feature_values``.

    ``feature_values`` (schema 1.8) is ``{engineered_feature: original_value}`` — the raw value already
    resolved by the engine (``None`` for a derived/interaction feature with no raw source). This maps
    each engineered feature back to its RAW source column (a one-hot ``col_cat`` → ``col``, longest
    matching prefix wins — the same rule as ``llm_explain._resolve_feature_display``) so the engine's
    ``_resolve_feature_display`` then renders "source_column = value" in the prompt, matching what the
    in-engine narrator produces. Returns ``None`` when nothing resolvable (so the narrator falls back
    to the engineered names) — never fabricates a value. ``None`` values are skipped.
    """
    if not feature_values:
        return None
    original: dict[str, Any] = {}
    for feature, value in feature_values.items():
        if value is None:
            continue
        if feature in feature_cols:
            original[feature] = value
            continue
        prefixes = [c for c in feature_cols if isinstance(c, str) and feature.startswith(c + "_")]
        if prefixes:
            original[max(prefixes, key=len)] = value  # longest matching original-column prefix
    return original or None
