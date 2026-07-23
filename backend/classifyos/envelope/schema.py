"""Pydantic response models for the LOCKED ``/api/v1/run`` schema (see ``docs/api_contract.md``).

These describe the shape of a run's result envelope on the way out. Declaring it as models keeps
it self-documenting, validated on the way out, and gives the frontend a precise target.

They live in the ENGINE (``classifyos.envelope``), not the FastAPI layer, so the Databricks Job
notebook can build a **byte-identical** envelope from the installed wheel alone — no repo checkout
of ``backend/api`` required. ``api.models`` re-exports every name here, so the FastAPI layer and its
tests import them from ``api.models`` exactly as before.

Only the RESPONSE side lives here. The REQUEST model (``RunConfig``) and the read-path / Databricks
orchestration models stay in ``api.models`` — those are genuinely web-layer (``RunConfig`` bridges
to ``classifyos.config.build_config``; the others back specific HTTP endpoints).

[Locked-contract rule] ``SCHEMA_VERSION`` is bumped ONLY for additive changes; never mutate an
earlier version's field shapes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: Current locked-contract version, reported in every ``/api/v1/run`` response and by the
#: read-path endpoints. Bump ONLY for additive contract changes (docs/api_contract.md);
#: never mutate an earlier version's field shapes. History lives on :class:`RunResponse`.
SCHEMA_VERSION = "1.11"


class RunMeta(BaseModel):
    """Curated run metadata (``result.run``) — a subset of ``run_profile.json``."""

    target: str
    problem_type: str
    features: list[str]
    active_features: list[str]
    interaction_cols: list[str]
    class_distribution: dict[str, int]
    n_rows: int
    n_train: int
    n_test: int
    class_balance: str | None
    class_weight: dict[str, float] | None
    models_succeeded: int
    timestamp: str


class TrainMetrics(BaseModel):
    """``result.models[].train`` — headline metrics on the PRE-balance TRAIN split (1.2).

    Additive in ``schema_version`` 1.2. The SAME headline scalars as the test-side fields on
    :class:`ModelMetrics`, but measured on the pre-balance TRAIN split (real rows at the
    natural class distribution — NOT the SMOTE/undersampled matrix the model was fit on). The
    point is the overfit gap: ``model.<metric> − model.train.<metric>``. Every field is
    ``None`` for a failed model (or when train evaluation was unavailable), so the block's
    shape is always present and only the values vary.
    """

    accuracy: float | None = None
    f1_weighted: float | None = None
    f1_macro: float | None = None
    precision_weighted: float | None = None
    recall_weighted: float | None = None
    roc_auc: float | None = None
    pr_auc: float | None = None
    log_loss: float | None = None
    mcc: float | None = None


class ModelMetrics(BaseModel):
    """One per-model row in ``result.models`` (a LIST so the frontend can ``.map``).

    The top-level metric fields are the HELD-OUT TEST split (1.0). ``train`` (1.2, additive)
    carries the same headline metrics on the pre-balance TRAIN split for the overfit gap.
    """

    name: str
    status: str  # "ok" | "failed"
    accuracy: float | None = None
    f1_weighted: float | None = None
    f1_macro: float | None = None
    precision_weighted: float | None = None
    recall_weighted: float | None = None
    roc_auc: float | None = None
    pr_auc: float | None = None
    log_loss: float | None = None
    mcc: float | None = None
    # NEW in schema 1.2 (additive): pre-balance TRAIN headline metrics. Always present.
    train: TrainMetrics | None = None
    # NEW in schema 1.5 (additive): the decision policy actually applied to this model.
    # ``decision_threshold`` is the effective positive-class operating threshold for a BINARY
    # problem (tuned best / fixed value / 0.5 default); ``null`` for multiclass/multilabel and
    # for failed models. ``calibrated`` is whether the probabilities are calibrated.
    decision_threshold: float | None = None
    calibrated: bool | None = None
    error: str | None = None


class PredictionRow(BaseModel):
    """One sampled prediction in ``result.predictions.sample_rows``."""

    model: str
    sample_index: int
    actual: str
    predicted: str
    confidence: float | None
    correct_flag: bool
    probabilities: dict[str, float | None]


class PredictionsBlock(BaseModel):
    """``result.predictions`` — SAMPLED for display; full table via the artifacts CSV."""

    sample_rows: list[PredictionRow]
    sampled: bool
    rows_returned: int
    rows_total: int
    full_csv: str


class ConfusionMatrixEntry(BaseModel):
    """Per-model confusion matrix (full test set), ``result.confusion_matrix[model]``."""

    labels: list[str]
    matrix: list[list[int]]


class ClassReportRow(BaseModel):
    """One per-class row in ``result.class_report[model]``."""

    class_: str = Field(alias="class")
    precision: float | None
    recall: float | None
    f1: float | None
    support: float | None

    model_config = ConfigDict(populate_by_name=True)


class FeatureImpactRow(BaseModel):
    """One ranked feature in ``result.feature_impact`` (preserves the id_like flag)."""

    feature: str
    dtype_group: str | None = None
    anova_f: float | None = None
    anova_p: float | None = None
    mutual_info: float | None = None
    point_biserial: float | None = None
    corr_ratio: float | None = None
    composite_score: float | None = None
    id_like: bool = False
    rank: int | None = None


class FeatureImportanceRow(BaseModel):
    """One ranked feature in ``result.feature_importance[model]`` (NEW in schema 1.3).

    The model's NATIVE (built-in) importance for one feature, read post-training from the
    fitted estimator (tree impurity/gain or ``|coef|``), with a 1-based ``rank`` descending
    within that model. Model-dependent and NOT comparable across models — distinct from the
    pre-training ``result.feature_impact`` screen of raw features.
    """

    feature: str
    importance: float | None = None
    rank: int | None = None


class PermutationImportanceRow(BaseModel):
    """One ranked feature in ``result.permutation_importance[model]`` (NEW in schema 1.4).

    The model's PERMUTATION importance for one feature — the drop in F1-weighted on the
    held-out TEST split when that feature's values are shuffled — with a 1-based ``rank``
    descending within that model. Unlike ``feature_importance`` (native, only the tree/linear
    models), this is **model-agnostic** so it is present for EVERY model, including the
    RBF-SVM and GaussianNB that expose no native importance. ``importance`` may be slightly
    negative (shuffle noise). Measured in one consistent unit (F1-weighted drop), so it is
    comparable across models — unlike the native importances.
    """

    feature: str
    importance: float | None = None
    rank: int | None = None


class ExplanationRow(BaseModel):
    """One explained row in ``result.explanations[model].rows`` (NEW in schema 1.6).

    Per-row SHAP contributions for one held-out TEST row: ``base_value`` is the model's
    average output (the waterfall's start), ``contributions`` maps each feature to its signed
    push, and ``base_value + Σ contributions == prediction`` (the SHAP-additive landing
    point). ``explained_class`` is the class the waterfall describes — the positive class for
    binary, the predicted (argmax) class for multiclass. ``sample_index`` is the 0-based row
    position within the held-out test set.
    """

    sample_index: int
    explained_class: str
    base_value: float
    prediction: float
    contributions: dict[str, float] = Field(default_factory=dict)
    # NEW in schema 1.8 (additive): each contributed feature's ORIGINAL (raw, pre-preprocessing)
    # value, keyed identically to ``contributions`` — so the waterfall can show "feature = value"
    # (the reason-code convention). A one-hot ``col_cat`` feature resolves to its source column's
    # raw category; a derived/interaction feature with no raw source resolves to ``None``. Present
    # whenever SHAP explanations are (not gated on the LLM flag); empty when unresolved.
    feature_values: dict[str, str | None] = Field(default_factory=dict)
    # NEW in schema 1.7 (additive, optional): an LLM-authored plain-language reason-code
    # paragraph for this row (Azure OpenAI). ``None`` when LLM narratives were OFF (the default),
    # credentials were absent, or the call failed — so a SHAP-only run is unchanged from 1.6.
    narrative: str | None = None


class ModelExplanation(BaseModel):
    """``result.explanations[model]`` — one model's per-row SHAP explanations (NEW in 1.6).

    ``method`` names the explainer used (``"shap.TreeExplainer"`` for the tree models,
    ``"shap.KernelExplainer"`` for LogisticRegression/SVM/NaiveBayes). ``rows`` holds one
    :class:`ExplanationRow` per explained test row.
    """

    method: str
    rows: list[ExplanationRow] = Field(default_factory=list)


class ArtifactEntry(BaseModel):
    """One output file in ``result.artifacts`` (PNGs fetched on demand via /outputs)."""

    name: str
    suffix: str
    size_bytes: int


class RunTuning(BaseModel):
    """``result.tuning`` — per-model tuned hyperparameters (NEW in schema 1.1).

    Additive in ``schema_version`` 1.1: mirrors the ``tuning`` block of ``run_profile.json``
    one-for-one. The whole block is optional — ``RunResult.tuning`` is ``None`` when tuning was
    OFF (or produced no tuned params), so a non-tuning run is byte-identical to 1.0.
    ``best_params`` values are heterogeneous (float/int/str/bool), hence ``dict[str, Any]``.
    """

    enabled: bool
    metric: str | None = None
    cv: bool | None = None
    cv_folds: int | None = None
    n_trials: int | None = None
    timeout_seconds: float | None = None
    tuned_models: list[str] = Field(default_factory=list)
    best_params: dict[str, dict[str, Any]] = Field(default_factory=dict)


class MlflowInfo(BaseModel):
    """``result.mlflow`` — where this run was logged in MLflow (NEW in schema 1.9).

    Present only when the opt-in ``mlflow.enabled`` was set AND logging succeeded; ``None``
    otherwise (so a run without MLflow logging is byte-identical to earlier schemas). ``models``
    maps each fitted algorithm to its logged-model URI, loadable via ``mlflow.<flavor>.load_model``
    (a partial map if a particular model failed to serialize). ``tracking_uri`` is where the run
    was recorded (a local ``./mlruns`` folder by default, or a configured tracking server).
    """

    run_id: str
    experiment_id: str
    tracking_uri: str
    models: dict[str, str] = Field(default_factory=dict)


class RunResult(BaseModel):
    """``result`` — the whole reshaped run output."""

    run: RunMeta
    models: list[ModelMetrics]
    predictions: PredictionsBlock
    # Loose dicts keyed by model/class name — too dynamic to type strictly, but each
    # value's shape is documented in docs/api_contract.md and the models above.
    confusion_matrix: dict[str, ConfusionMatrixEntry]
    class_report: dict[str, list[ClassReportRow]]
    feature_impact: list[FeatureImpactRow]
    curves: dict[str, Any]
    artifacts: list[ArtifactEntry]
    # NEW in schema 1.1 (additive, optional): the per-model tuned hyperparameters. ``None``
    # when tuning was OFF / produced nothing, so existing 1.0 fields are untouched.
    tuning: RunTuning | None = None
    # NEW in schema 1.3 (additive, optional): native per-model feature importance, keyed by
    # model name. Models with no native importance (RBF-SVM, GaussianNB) are omitted; ``None``
    # when no model exposes any, so an SVM/NB-only run is byte-identical to earlier schemas.
    feature_importance: dict[str, list[FeatureImportanceRow]] | None = None
    # NEW in schema 1.4 (additive, optional): per-model PERMUTATION importance, keyed by model
    # name. Model-agnostic, so it covers ALL models (SVM/NaiveBayes included) — the complement
    # to the native ``feature_importance`` above. ``None`` when it could not be computed for
    # any model, so a run that produced none is byte-identical to earlier schemas.
    permutation_importance: dict[str, list[PermutationImportanceRow]] | None = None
    # NEW in schema 1.6 (additive, optional): per-row SHAP explanations keyed by model name
    # (LOCAL explainability — why THIS prediction). ``None`` when explainability was OFF (the
    # default) or produced nothing, so a run without it is byte-identical to earlier schemas.
    explanations: dict[str, ModelExplanation] | None = None
    # NEW in schema 1.9 (additive, optional): a pointer to where this run was logged in MLflow
    # (run id + per-model saved-model URIs). ``None`` when the opt-in ``mlflow.enabled`` was OFF
    # (the default) or logging failed, so a run without MLflow logging is byte-identical to 1.8.
    mlflow: MlflowInfo | None = None


class RunResponse(BaseModel):
    """Top-level envelope for ``POST /api/v1/run`` (the forward-compat seam)."""

    status: str = "ok"  # "ok" | "error"
    # 1.1 (additive): added the optional ``result.tuning`` block.
    # 1.2 (additive): added ``result.models[].train`` (pre-balance train headline metrics).
    # 1.3 (additive): added the optional ``result.feature_importance`` block (native
    #     per-model post-training importance).
    # 1.4 (additive): added the optional ``result.permutation_importance`` block (model-agnostic
    #     per-model permutation importance, covering all models). All earlier fields unchanged.
    # 1.5 (additive): added ``result.models[].decision_threshold`` + ``.calibrated`` (the
    #     decision policy applied per model). All earlier fields unchanged.
    # 1.6 (additive): added the optional ``result.explanations`` block (per-row SHAP — LOCAL
    #     explainability). ``None`` when explainability was OFF (default). All earlier fields unchanged.
    # 1.7 (additive): added the optional ``result.explanations[model].rows[].narrative`` field
    #     (LLM-authored reason-code paragraph, Azure OpenAI). ``None`` unless the opt-in
    #     ``explainability.llm_narratives`` was on AND credentials were configured. All earlier
    #     fields unchanged.
    # 1.8 (additive): added ``result.explanations[model].rows[].feature_values`` — each explained
    #     feature's ORIGINAL (raw) value, keyed identically to ``contributions`` (so the waterfall
    #     can show "feature = value"). Present whenever SHAP explanations are; ``null`` per feature
    #     for derived/interaction features with no raw source. All earlier fields unchanged.
    # 1.9 (additive): added the optional ``result.mlflow`` block (run id + per-model saved-model
    #     URIs) reporting where the run was logged in MLflow. ``None`` unless the opt-in
    #     ``mlflow.enabled`` was on AND logging succeeded, so a run without it is byte-identical to
    #     1.8. All earlier fields unchanged.
    # 1.10 (additive): NO change to this ``/run`` envelope — its shape is byte-identical to 1.9.
    #     1.10 adds the MLflow read-path endpoints (``GET /runs`` + ``GET /runs/{run_id}``,
    #     Interim 2a) that list past runs and reload one; the version marker moves so the
    #     contract doc's advance is recorded (locked-contract rule). All fields unchanged.
    # 1.11 (additive): NO change to this ``/run`` envelope. 1.11 adds the Databricks orchestration
    #     layer (§6.6 Step 6): when the server runs the DATABRICKS execution backend, ``POST /run``
    #     instead returns a ``RunSubmission`` (``{job_id, run_id, status}``) and the run is
    #     polled via ``GET /run/{job_id}/status`` → fetched via ``GET /run/{job_id}/results`` (which
    #     returns THIS same envelope). In the default LOCAL backend ``/run`` is byte-identical to
    #     1.10. Also adds the UC data-source proxies (``GET /databricks/{catalogs,schemas,tables}``).
    schema_version: str = SCHEMA_VERSION
    result: RunResult | None = None
    error: str | None = None
