"""Pydantic request/response models — the web-facing API contract.

A FastAPI app describes the JSON it accepts and returns as **Pydantic models**. When a
request arrives, FastAPI validates the incoming body against the declared model BEFORE the
endpoint function runs, and auto-returns HTTP 422 (with a precise, field-level message) if
it does not fit. This is the web-layer twin of the engine's :func:`classifyos.config.build_config`
validation: same idea (reject bad input early, in one place), different layer.

This module holds:

* :class:`RunConfig` — the request body for ``POST /api/v1/run``. Its fields mirror the
  user-settable knobs of the engine's ``DEFAULT_CONFIG``. It is intentionally a SEPARATE
  thing from the engine's internal config dict: the web contract can stay stable even if the
  engine's internal defaults evolve. :meth:`RunConfig.to_engine_config` is the one place the
  web shape is translated into the dict ``build_config`` expects (reconciling plan_tweak
  row 6 — the engine config is wider than the scope's table).
* The response models for the **locked** ``/api/v1/run`` schema (see ``docs/api_contract.md``).
  Declaring the response shape as models keeps it self-documenting and validated on the way
  out, and gives the Phase 9 frontend a precise target.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from classifyos.config import (
    USER_FEATURE_DATETIME_DIFF_OPS,
    USER_FEATURE_DATETIME_UNITS,
    USER_FEATURE_NUMERIC_OPS,
    USER_FEATURE_SINGLE_OPS,
    USER_FEATURE_TYPES,
    build_config,
)

#: Current locked-contract version, reported in every ``/api/v1/run`` response and by the
#: read-path endpoints. Bump ONLY for additive contract changes (docs/api_contract.md);
#: never mutate an earlier version's field shapes. History lives on :class:`RunResponse`.
SCHEMA_VERSION = "1.10"

# --------------------------------------------------------------------------- #
# Request models                                                              #
# --------------------------------------------------------------------------- #


class FeatureEngineeringConfig(BaseModel):
    """Section 7 (FeatureBuilder) toggles. Mirrors ``DEFAULT_CONFIG['feature_engineering']``."""

    enabled: bool = True
    polynomial: bool = False  # OFF by default — squared terms explode width with trees
    ratios: bool = True
    binning: bool = True
    max_poly_features: int = 8


class InteractionFeaturesConfig(BaseModel):
    """Section 7B (InteractionFeatureBuilder) toggles. Mirrors the engine sub-dict."""

    enabled: bool = True
    interaction_pairs: dict[str, str] = Field(default_factory=dict)
    default_interactions: list[str] = Field(default_factory=lambda: ["multiply"])
    drop_original_if_interacted: bool = False
    max_auto_pairs: int = 10
    fill_method: str = "zero"


class TuningConfig(BaseModel):
    """Section 8B (Optuna) dials. OFF by default. Mirrors ``DEFAULT_CONFIG['tuning']``."""

    enabled: bool = False
    models: list[str] = Field(default_factory=list)  # [] / ["all"] → every run algorithm
    metric: str = "f1_weighted"
    cv: bool = True
    cv_folds: int = 3
    n_trials: int = 30
    timeout_seconds: float | None = None  # per-model wall-clock cap; None = no cap (n_trials bounds it)
    search_space_overrides: dict[str, Any] = Field(default_factory=dict)


class ExplainabilityConfig(BaseModel):
    """Per-row SHAP explainability dials. OFF by default. Mirrors ``DEFAULT_CONFIG['explainability']``.

    Opt-in because the model-agnostic KernelExplainer (SVM/NaiveBayes) has real cost; when
    enabled, per-row SHAP contributions are computed during the run for the first
    ``sample_rows`` held-out test rows per model and returned in ``result.explanations``.
    ``build_config`` is the authoritative validator of the values.
    """

    enabled: bool = False
    sample_rows: int = 20  # first N held-out TEST rows per model to explain
    background_size: int = 100  # TRAIN rows sampled as the SHAP reference distribution
    # NEW in schema 1.7 (request-side): opt-in Azure OpenAI reason-code narrative per explained
    # row (requires ``enabled``; credentials come from the AZURE_OPEN_AI_* env vars). Absent
    # credentials / a failed call degrade to SHAP-only, so a run stays valid either way.
    llm_narratives: bool = False
    # Dataset/domain context that shapes the LLM prompt ONLY (never touches the ML). ``context_mode``
    # (given | derived | both) chooses whether the model sees the analyst text below, engine-derived
    # facts (headers + a sample row + light stats + class base rates), or both. Request-side only —
    # forwarded to build_config (authoritative validator); no response-shape / schema_version change.
    dataset_context: str = ""
    column_context: dict[str, str] = Field(default_factory=dict)
    context_mode: str = "both"


class InputSourceConfig(BaseModel):
    """Where the run's data comes from (Interim 2b). Default ``file`` = today's behaviour.

    Mirrors ``DEFAULT_CONFIG['input_source']``. ``type="postgres"`` materializes a table/query to
    ``input_file`` under DATA_DIR BEFORE the run (Option B, materialize-to-file), then the pipeline
    reads that snapshot file unchanged. The DB connection is referenced by ``connection_env`` — the
    NAME of a server-side env var (in ``backend/.env``) holding the SQLAlchemy DSN — never a
    credential in the request. Provide EITHER ``table`` (→ ``SELECT * FROM <table>``) OR ``query``.
    Request-side dial only; ``build_config`` is the authoritative validator of the values.
    """

    # Reject unknown keys so a typo'd field is a clear 422, not a silent no-op.
    model_config = ConfigDict(extra="forbid")

    type: str = "file"
    connection_env: str = "CLASSIFYOS_PG_DSN"
    table: str | None = None
    query: str | None = None


class MlflowConfig(BaseModel):
    """MLflow logging dials (Databricks integration — Phase A). OFF by default.

    Mirrors ``DEFAULT_CONFIG['mlflow']``. When ``enabled``, the run is logged to MLflow AFTER
    training — the config as params, each model's headline TEST metrics, the artifact files, and
    one saved model per fitted algorithm (flavor-native). Local ``./mlruns`` by default; a managed
    tracking server is selected server-side via the ``MLFLOW_TRACKING_URI`` env var (not a request
    field). Request-side dial only; ``build_config`` is the authoritative validator of the values.
    """

    enabled: bool = False
    experiment: str = "classifyos"
    run_name: str | None = None


class UserFeatureSpec(BaseModel):
    """One user-defined STRUCTURED feature spec (UserFeatureBuilder).

    Mirrors the engine's allowlist-bounded spec shape (see
    ``classifyos.preprocessing.user_features`` and the ``USER_FEATURE_*`` allowlists in
    ``classifyos.config``): a new column built by applying a KNOWN ``op`` from a fixed
    allowlist to KNOWN existing column(s). There is NO free-text formula — nothing is ever
    ``eval``'d. The three shapes:

    * ``type="numeric"`` — two numeric columns + an op in :data:`USER_FEATURE_NUMERIC_OPS`
      (``add``/``subtract``/``multiply``/``divide``/``ratio``); ``col_b`` required.
    * ``type="datetime_diff"`` — two datetime columns, ``op="subtract"`` → a duration in
      ``unit`` (:data:`USER_FEATURE_DATETIME_UNITS`, default ``days``); ``col_b`` required.
    * ``type="single"`` — one column + an op in :data:`USER_FEATURE_SINGLE_OPS`
      (numeric ``log``/``abs``/``bin`` or date-part ``year``/``month``/``day``/``dayofweek``/
      ``hour``); ``col_b`` must be omitted.

    This is the fast-fail web-boundary guard (reject an unknown ``op``/``type`` with a clear
    422 before any work runs). The engine's ``build_config`` remains the AUTHORITATIVE
    validator — these checks intentionally mirror its allowlists and must not diverge from
    them. Column existence/type are NOT checked here (the dataset is not loaded yet); the
    engine validates those at fit time and skips a bad spec without aborting the run.
    """

    # Reject unknown keys so a typo'd spec field is a clear 422, not a silent no-op.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="New column name (non-empty; must not collide).")
    type: str = Field(..., description=f"One of {list(USER_FEATURE_TYPES)}.")
    op: str = Field(..., description="Operation from the allowlist for this type.")
    col_a: str = Field(..., description="Source column A (non-empty).")
    col_b: str | None = Field(None, description="Source column B (required for two-column types).")
    unit: str | None = Field(None, description="Duration unit for datetime_diff (default days).")

    @field_validator("name", "col_a")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _check_type_op_columns(self) -> "UserFeatureSpec":
        """Reject an unknown type, an op not permitted for the type, or a missing col_b."""
        if self.type not in USER_FEATURE_TYPES:
            raise ValueError(
                f"type must be one of {list(USER_FEATURE_TYPES)}, got {self.type!r}"
            )

        if self.type == "numeric":
            allowed_ops = USER_FEATURE_NUMERIC_OPS
        elif self.type == "datetime_diff":
            allowed_ops = USER_FEATURE_DATETIME_DIFF_OPS
        else:  # single
            allowed_ops = USER_FEATURE_SINGLE_OPS
        if self.op not in allowed_ops:
            raise ValueError(
                f"op must be one of {list(allowed_ops)} for type {self.type!r}, got {self.op!r}"
            )

        # Two-column types need col_b; single transforms must not carry one.
        if self.type in ("numeric", "datetime_diff"):
            if not self.col_b or not self.col_b.strip():
                raise ValueError(f"col_b is required for type {self.type!r}")
        elif self.col_b is not None:
            raise ValueError("col_b must be omitted for a single-column feature")

        if self.type == "datetime_diff" and self.unit is not None:
            if self.unit not in USER_FEATURE_DATETIME_UNITS:
                raise ValueError(
                    f"unit must be one of {list(USER_FEATURE_DATETIME_UNITS)}, got {self.unit!r}"
                )

        return self


class RunConfig(BaseModel):
    """Request body for ``POST /api/v1/run`` — the user's run configuration.

    This is the API contract, distinct from the engine's internal ``DEFAULT_CONFIG``: the
    three required fields (``input_file``, ``target``, ``feature_cols``) have no defaults, so
    a request missing any of them is rejected with HTTP 422 before the engine is touched.
    Everything else carries a sensible default matching the engine's own defaults.
    """

    # Reject unknown top-level keys so a typo'd field is a clear 422, not a silent no-op.
    model_config = ConfigDict(extra="forbid")

    # --- required ---
    input_file: str = Field(..., description="Logical key of the dataset (resolved by storage).")
    target: str = Field(..., description="Target column name; must not appear in feature_cols.")
    feature_cols: list[str] = Field(..., description="Feature columns (at least one).")

    # --- problem framing ---
    problem_type: str = "binary"
    test_size: float = 0.2
    stratify: bool = True
    time_split_col: str | None = None

    # --- modelling / preprocessing ---
    algorithms: list[str] = Field(
        default_factory=lambda: ["LogisticRegression", "RandomForest", "XGBoost"]
    )
    class_balance: str = "smote"
    # Missing-value treatment, split by feature type. ``missing_strategy`` is the legacy
    # GLOBAL default (back-compat); the two per-type keys override it when set. None → inherit
    # the global (a numeric-only global falls back to mode for categorical in the engine). The
    # engine's ``build_config`` is the authoritative validator of the allowed per-type values.
    missing_strategy: str = "median"
    missing_strategy_numeric: str | None = None
    missing_strategy_categorical: str | None = None
    # Optional PER-COLUMN overrides: {column_name: strategy}. A named column uses its own
    # strategy instead of the per-type default; unlisted columns keep the per-type behaviour.
    # Default {} → no override. The engine's ``build_config`` is the authoritative validator
    # of the allowed strategy values (and coerces an ill-typed pairing at fit time).
    missing_strategy_by_column: dict[str, str] = Field(default_factory=dict)
    encoding_method: str = "onehot"
    scaling_method: str = "standard"
    outlier_method: str = "iqr"
    high_cardinality_threshold: int = 20
    # Decision policy (binary problems). ``threshold`` is the cutoff used in "fixed" mode;
    # ``threshold_mode`` ∈ {"default","fixed","tuned"}; ``threshold_metric`` is the metric a
    # "tuned" threshold maximises. ``calibrate_probs`` toggles probability calibration.
    # All are forwarded to build_config, the authoritative validator of the allowed values.
    threshold: float = 0.5
    threshold_mode: str = "default"
    threshold_metric: str = "f1"
    calibrate_probs: bool = True
    random_state: int = 42
    # Metric the post-training permutation importance scores the drop in (request-side only;
    # the response shape is unchanged, so NO schema_version bump). build_config is the
    # authoritative validator of the allowed value (config.PERMUTATION_METRICS).
    permutation_metric: str = "f1_weighted"

    # --- nested capability configs ---
    # Input source (Interim 2b). Default ``file`` = today's behaviour (reads ``input_file`` from
    # storage). ``postgres`` materializes a table/query to ``input_file`` under DATA_DIR before the
    # run. Request-side dial only; forwarded to build_config (authoritative validator). The DSN is
    # a server-side env concern (``connection_env`` names the env var, never a credential here).
    input_source: InputSourceConfig = Field(default_factory=InputSourceConfig)
    feature_engineering: FeatureEngineeringConfig = Field(default_factory=FeatureEngineeringConfig)
    interaction_features: InteractionFeaturesConfig = Field(default_factory=InteractionFeaturesConfig)
    tuning: TuningConfig = Field(default_factory=TuningConfig)
    # Per-row SHAP explainability (Explainability page). OFF by default; when enabled the run
    # returns a ``result.explanations`` block. Forwarded to build_config (authoritative validator).
    explainability: ExplainabilityConfig = Field(default_factory=ExplainabilityConfig)
    # MLflow run logging + model persistence (Phase A). OFF by default; when enabled the run is
    # logged to MLflow and the response carries a ``result.mlflow`` pointer. Request-side dial;
    # forwarded to build_config (authoritative validator). The tracking store is server-side env.
    mlflow: MlflowConfig = Field(default_factory=MlflowConfig)
    # User-defined structured features (UserFeatureBuilder). Empty/omitted → no user features
    # (unchanged behaviour). Each spec is validated against the engine's allowlists above.
    user_features: list[UserFeatureSpec] = Field(default_factory=list)

    @field_validator("input_file", "target")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        """Required strings must be non-empty/whitespace (else 422)."""
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("feature_cols")
    @classmethod
    def _at_least_one_feature(cls, value: list[str]) -> list[str]:
        """``feature_cols`` must list at least one column (else 422)."""
        if not value:
            raise ValueError("must list at least one feature column")
        return value

    def to_engine_config(self) -> dict[str, Any]:
        """Translate this web request into a validated engine config dict.

        This is the single bridge between the web shape and the engine's wider config
        contract: it forwards every field to :func:`classifyos.config.build_config`, which
        applies the engine defaults, layers these overrides, and runs the authoritative
        validation (enum checks, ``test_size`` range, target-not-in-features, etc.). Any
        problem there raises ``ValueError``, which the route turns into an HTTP 422 — so the
        engine's validation and the API's validation stay one and the same, never duplicated.
        """
        overrides = self.model_dump(exclude={"input_file", "target", "feature_cols"})
        # The engine reads each user-feature spec as a plain dict and treats a present
        # ``unit``/``col_b`` of ``None`` as invalid; dump each spec with ``exclude_none`` so
        # the optional keys drop out and the shape matches the engine's spec exactly.
        overrides["user_features"] = [
            spec.model_dump(exclude_none=True) for spec in self.user_features
        ]
        return build_config(
            self.input_file,
            self.target,
            self.feature_cols,
            **overrides,
        )


# --------------------------------------------------------------------------- #
# Response models (the LOCKED /api/v1/run schema — see docs/api_contract.md)   #
# --------------------------------------------------------------------------- #


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
    schema_version: str = SCHEMA_VERSION
    result: RunResult | None = None
    error: str | None = None


# --------------------------------------------------------------------------- #
# MLflow read-path models (schema 1.10 — Interim 2a; list + reload past runs)  #
# --------------------------------------------------------------------------- #


class RunSummary(BaseModel):
    """One past MLflow run in ``GET /api/v1/runs`` — a lightweight list-row (NEW in 1.10).

    Derived from the run's MLflow metadata (no artifact download): the flattened-config params
    the engine logs (``target``/``problem_type``/``input_file``), the ``classifyos.*`` provenance
    tags, and the per-model headline metrics (keyed ``<model>.<metric>``) — from which the
    algorithm list and the best F1-weighted are computed. ``reloadable`` is ``true`` when the run
    carries the API's persisted ``/run`` envelope snapshot (set on runs produced via ``/run``);
    :class:`RunResult` for such a run can be reloaded byte-identically via ``GET /runs/{run_id}``.
    """

    run_id: str
    experiment_id: str
    experiment_name: str | None = None
    run_name: str | None = None
    #: MLflow run lifecycle stage — "FINISHED" | "FAILED" | "RUNNING" | "SCHEDULED" | "KILLED".
    status: str
    #: UTC ISO-8601, converted from MLflow's epoch-millis; ``None`` if unset.
    start_time: str | None = None
    end_time: str | None = None
    target: str | None = None
    problem_type: str | None = None
    input_file: str | None = None
    #: Algorithm names logged for this run (from the ``<model>.<metric>`` metric keys).
    algorithms: list[str] = Field(default_factory=list)
    models_logged: int = 0
    #: The headline metric summarised for the list (always ``"f1_weighted"``) + its best value
    #: across models and the model that achieved it (``None`` when no model logged it).
    best_metric: str = "f1_weighted"
    best_value: float | None = None
    best_model: str | None = None
    #: ``true`` when a reloadable ``/run`` envelope snapshot is attached (see ``GET /runs/{id}``).
    reloadable: bool = False


class RunsListResponse(BaseModel):
    """``GET /api/v1/runs`` — past runs read from MLflow, most-recent first (NEW in 1.10).

    Additive read-path endpoint (Interim 2a): the ``/run`` envelope is unchanged. ``runs`` is a
    LIST (renders with ``.map``) of :class:`RunSummary`; ``tracking_uri`` is the store the API
    read from (a local ``./mlruns`` folder, or a Postgres backend store when configured).
    """

    schema_version: str = SCHEMA_VERSION
    tracking_uri: str
    runs: list[RunSummary] = Field(default_factory=list)
