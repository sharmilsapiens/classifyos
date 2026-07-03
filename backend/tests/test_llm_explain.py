"""Tests for LLM reason-code narratives (:mod:`classifyos.analysis.llm_explain`).

These never touch a live Azure OpenAI endpoint — a stub client (any object exposing
``chat.completions.create``) is injected into :class:`AzureNarrator`, and the credential
factory is exercised only for its env-driven branching. The contract:

* a narrative is a faithful, grounded restatement of the SHAP numbers (the prompt carries the
  top features, their signed contributions, the base value and the prediction);
* it degrades gracefully — a raised SDK error, an empty completion, or missing credentials all
  yield ``None`` rather than aborting;
* ``narrator_from_env`` returns ``None`` unless every required ``AZURE_OPEN_AI_*`` var is set.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from classifyos.analysis import llm_explain
from classifyos.analysis.llm_explain import (
    AzureNarrator,
    RunContext,
    _ROLE_INSTRUCTIONS,
    _build_messages,
    _resolve_feature_display,
    _top_features,
    build_system_message,
    derive_dataset_understanding,
    narrate_rows,
    narrator_from_env,
)
from classifyos.config import build_config


class _StubClient:
    """Minimal stand-in for an ``openai.AzureOpenAI`` client.

    Records the kwargs of the last ``chat.completions.create`` call and returns a canned
    completion (or raises / returns empty, to exercise the failure paths).
    """

    def __init__(self, *, content: str | None = "Because of X and Y.", raise_exc: bool = False):
        self._content = content
        self._raise = raise_exc
        self.last_kwargs: dict | None = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._raise:
            raise RuntimeError("boom")
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


_CONTRIB = {"num_late_payments": 0.40, "policy_tenure_years": -0.11, "region_west": 0.02}


def test_narrate_returns_text_and_calls_deployment() -> None:
    """A successful call returns the stripped content and keys the request on the deployment."""
    client = _StubClient(content="  This policy is high risk.  ")
    narrator = AzureNarrator(client, "gpt-4o-deploy", model_label="gpt-4o")
    text = narrator.narrate(
        model_name="RandomForest",
        problem_type="binary",
        target="will_lapse",
        explained_class="1",
        base_value=0.36,
        prediction=0.65,
        contributions=_CONTRIB,
        feature_values={"num_late_payments": 3, "policy_tenure_years": 8.0},
    )
    assert text == "This policy is high risk."
    assert client.last_kwargs["model"] == "gpt-4o-deploy"  # deployment, not model_label
    # modern token param (reasoning models reject max_tokens); temperature unset by default
    assert "max_completion_tokens" in client.last_kwargs
    assert "max_tokens" not in client.last_kwargs
    assert "temperature" not in client.last_kwargs  # DEFAULT_TEMPERATURE is None → not sent
    # the system + user messages both reach the model
    roles = [m["role"] for m in client.last_kwargs["messages"]]
    assert roles == ["system", "user"]


def test_narrate_returns_none_on_sdk_error() -> None:
    """A raised SDK error is swallowed (report-only) → ``None``, never propagated."""
    narrator = AzureNarrator(_StubClient(raise_exc=True), "d")
    assert narrator.narrate(
        model_name="SVM",
        problem_type="binary",
        target="will_lapse",
        explained_class="1",
        base_value=0.5,
        prediction=0.5,
        contributions=_CONTRIB,
    ) is None


def test_narrate_returns_none_on_empty_completion() -> None:
    """An empty/whitespace completion yields ``None`` (nothing useful to show)."""
    narrator = AzureNarrator(_StubClient(content="   "), "d")
    assert narrator.narrate(
        model_name="XGBoost",
        problem_type="binary",
        target="will_lapse",
        explained_class="1",
        base_value=0.5,
        prediction=0.7,
        contributions=_CONTRIB,
    ) is None


def test_top_features_orders_by_magnitude_and_folds_residual() -> None:
    """Top-N by |contribution|; the omitted tail is summed into a signed residual."""
    head, residual = _top_features(_CONTRIB, max_features=2)
    assert [f for f, _ in head] == ["num_late_payments", "policy_tenure_years"]
    assert residual == pytest.approx(0.02)  # region_west folded away


def test_build_messages_grounds_prompt_in_shap_numbers() -> None:
    """The user message names the top features, their direction, base value and prediction."""
    messages = _build_messages(
        model_name="RandomForest",
        problem_type="binary",
        target="will_lapse",
        explained_class="1",
        base_value=0.36,
        prediction=0.65,
        contributions=_CONTRIB,
        original_row=None,
        feature_values={"num_late_payments": 3},
        run_context=None,
        max_features=2,
    )
    user = messages[1]["content"]
    assert "num_late_payments" in user
    assert "increased" in user and "decreased" in user
    assert "0.3600" in user and "0.6500" in user  # base value + prediction
    assert "All other features combined" in user  # residual line present


def test_build_messages_uses_original_values() -> None:
    """When an original row is given, the user message shows the ORIGINAL value, not the scaled one."""
    messages = _build_messages(
        model_name="RandomForest",
        problem_type="binary",
        target="will_lapse",
        explained_class="1",
        base_value=0.36,
        prediction=0.65,
        contributions={"num_late_payments": 0.40},
        original_row={"num_late_payments": 3},
        feature_values={"num_late_payments": -1.473},  # model-space; must NOT be shown
        run_context=None,
        max_features=8,
    )
    user = messages[1]["content"]
    assert "num_late_payments = 3" in user
    assert "-1.473" not in user


def test_resolve_feature_display_maps_numeric_onehot_and_unresolved() -> None:
    """Numeric passthrough, one-hot → source column (longest prefix), and unresolved → no value."""
    row = {"num_late_payments": 3, "region": "West", "age_band": "adult"}
    # exact numeric column
    assert _resolve_feature_display("num_late_payments", row) == ("num_late_payments", "3")
    # one-hot col `region_West` → source column `region` with its raw value
    assert _resolve_feature_display("region_West", row) == ("region", "West")
    # longest matching prefix wins: `age_band_adult` maps to `age_band`, not `age`
    label, value = _resolve_feature_display("age_band_adult", row)
    assert label == "age_band" and value == "adult"
    # an interaction/derived feature with no raw source → value None
    assert _resolve_feature_display("a_x_b", row) == ("a_x_b", None)


def test_build_system_message_carries_run_context() -> None:
    """The system message includes base rates, model performance, global features, and given context."""
    ctx = RunContext(
        problem_type="binary",
        target="converted",
        class_base_rates={"0": 0.7, "1": 0.3},
        model_metrics={"f1_weighted": 0.83},
        global_features=[("Decision_Days", 0.12), ("billingPlan", 0.09)],
        dataset_context="Arizona commercial quotes; converted = quote was bound.",
        column_context={"Decision_Days": "days from quote to decision"},
        context_mode="both",
        derived_schema=["- Decision_Days (numeric): min=1, median=15, max=30"],
        sample_rows=[{"Decision_Days": 5, "billingPlan": 1}],
    )
    system = build_system_message(ctx)
    assert "base rates" in system and "1=30.0%" in system
    assert "f1_weighted=0.830" in system
    assert "Decision_Days" in system and "billingPlan" in system
    assert "quote was bound" in system  # given dataset context
    assert "days from quote to decision" in system  # given column context
    assert "Column facts (derived" in system  # derived schema (mode=both)


def test_role_instructions_forbid_printing_numbers() -> None:
    """The prompt must steer AWAY from restating SHAP numbers (prose, not a table)."""
    text = _ROLE_INSTRUCTIONS.lower()
    assert "do not print" in text
    assert "code" in text  # coded-categorical guidance present
    assert "2-3" in _ROLE_INSTRUCTIONS  # focus on the few strongest drivers


def test_build_system_message_includes_inferred_understanding() -> None:
    """The inferred primer is rendered (flagged as a hypothesis) in derived/both mode."""
    ctx = RunContext(
        problem_type="binary",
        target="converted",
        context_mode="both",
        derived_schema=["- x (numeric): min=1, median=2, max=3"],
        dataset_understanding="This looks like insurance quotes; converted likely means bound.",
    )
    system = build_system_message(ctx)
    assert "Model-inferred dataset understanding" in system
    assert "hypothesis" in system.lower()
    assert "converted likely means bound" in system
    # ...but not in given-only mode
    ctx.context_mode = "given"
    assert "Model-inferred dataset understanding" not in build_system_message(ctx)


def test_derive_dataset_understanding_happy_and_empty_and_failure() -> None:
    """The primer returns text with a stub client, None with no facts, and None on error."""
    ctx = RunContext(
        problem_type="binary",
        target="converted",
        class_base_rates={"0": 0.85, "1": 0.15},
        context_mode="both",
        derived_schema=["- Decision_Days (numeric): min=1, median=15, max=30"],
        sample_rows=[{"Decision_Days": 5}],
    )
    ok = AzureNarrator(_StubClient(content="Insurance quotes; converted = bound."), "d")
    assert derive_dataset_understanding(ok, ctx) == "Insurance quotes; converted = bound."

    # nothing to infer from → no call, None
    empty_ctx = RunContext(problem_type="binary", target="converted", context_mode="both")
    assert derive_dataset_understanding(ok, empty_ctx) is None

    # a raising client degrades to None (report-only)
    bad = AzureNarrator(_StubClient(raise_exc=True), "d")
    assert derive_dataset_understanding(bad, ctx) is None


def test_build_system_message_given_mode_omits_derived() -> None:
    """context_mode='given' keeps analyst text but drops the data-derived schema/sample rows."""
    ctx = RunContext(
        problem_type="binary",
        target="converted",
        dataset_context="Some analyst notes.",
        context_mode="given",
        derived_schema=["- x (numeric): min=1, median=2, max=3"],
        sample_rows=[{"x": 1}],
    )
    system = build_system_message(ctx)
    assert "Some analyst notes." in system
    assert "Column facts (derived" not in system
    assert "Sample rows" not in system


def test_narrate_rows_attaches_by_key_and_swallows_failures() -> None:
    """Concurrency helper keys results by job['key'] and turns a failing job into None."""

    class _Narrator:
        def narrate(self, *, model_name, **kwargs):
            if model_name == "Bad":
                raise RuntimeError("boom")
            return f"note for {model_name}"

    jobs = [
        {"key": ("RandomForest", 0), "params": {"model_name": "RandomForest"}},
        {"key": ("RandomForest", 1), "params": {"model_name": "RandomForest"}},
        {"key": ("Bad", 0), "params": {"model_name": "Bad"}},
    ]
    results = narrate_rows(_Narrator(), jobs, max_workers=3)
    assert results[("RandomForest", 0)] == "note for RandomForest"
    assert results[("RandomForest", 1)] == "note for RandomForest"
    assert results[("Bad", 0)] is None


def test_narrator_from_env_returns_none_when_unconfigured(monkeypatch) -> None:
    """Missing any required credential → ``None`` (a run then ships SHAP only)."""
    for var in (
        llm_explain.ENV_ENDPOINT,
        llm_explain.ENV_API_KEY,
        llm_explain.ENV_API_VERSION,
        llm_explain.ENV_DEPLOYMENT,
        llm_explain.ENV_MODEL,
    ):
        monkeypatch.delenv(var, raising=False)
    assert narrator_from_env() is None


def test_narrator_from_env_builds_client_when_configured(monkeypatch) -> None:
    """With all creds set, a real AzureOpenAI client is constructed (no network on build)."""
    monkeypatch.setenv(llm_explain.ENV_ENDPOINT, "https://example.openai.azure.com/")
    monkeypatch.setenv(llm_explain.ENV_API_KEY, "dummy-key")
    monkeypatch.setenv(llm_explain.ENV_API_VERSION, "2024-06-01")
    monkeypatch.setenv(llm_explain.ENV_DEPLOYMENT, "my-deploy")
    monkeypatch.setenv(llm_explain.ENV_MODEL, "gpt-4o")
    narrator = narrator_from_env()
    assert narrator is not None
    assert narrator.deployment == "my-deploy"
    assert narrator.model_label == "gpt-4o"


def test_config_validates_llm_narratives_flag() -> None:
    """``explainability.llm_narratives`` must be a bool (else a build-time ValueError = 422)."""
    cfg = build_config(
        "f.csv", "y", ["a"], explainability={"enabled": True, "llm_narratives": True}
    )
    assert cfg["explainability"]["llm_narratives"] is True
    with pytest.raises(ValueError):
        build_config(
            "f.csv", "y", ["a"], explainability={"enabled": True, "llm_narratives": "yes"}
        )


def test_config_validates_context_fields() -> None:
    """dataset_context (str), column_context (dict[str,str]) and context_mode (enum) are validated."""
    cfg = build_config(
        "f.csv", "y", ["a"],
        explainability={
            "enabled": True,
            "llm_narratives": True,
            "context_mode": "given",
            "dataset_context": "some notes",
            "column_context": {"a": "column a note"},
        },
    )
    assert cfg["explainability"]["context_mode"] == "given"
    assert cfg["explainability"]["column_context"] == {"a": "column a note"}
    # bad context_mode
    with pytest.raises(ValueError):
        build_config("f.csv", "y", ["a"], explainability={"context_mode": "nope"})
    # column_context must be a dict of {str: str}
    with pytest.raises(ValueError):
        build_config("f.csv", "y", ["a"], explainability={"column_context": ["not", "a", "dict"]})
    with pytest.raises(ValueError):
        build_config("f.csv", "y", ["a"], explainability={"column_context": {"a": 123}})
