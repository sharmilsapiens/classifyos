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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from classifyos.config import build_config

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
    timeout_seconds: float | None = 600  # hard per-model wall-clock cap; None opts out
    search_space_overrides: dict[str, Any] = Field(default_factory=dict)


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
    missing_strategy: str = "median"
    encoding_method: str = "onehot"
    scaling_method: str = "standard"
    outlier_method: str = "iqr"
    high_cardinality_threshold: int = 20
    threshold: float = 0.5
    calibrate_probs: bool = True
    random_state: int = 42

    # --- nested capability configs ---
    feature_engineering: FeatureEngineeringConfig = Field(default_factory=FeatureEngineeringConfig)
    interaction_features: InteractionFeaturesConfig = Field(default_factory=InteractionFeaturesConfig)
    tuning: TuningConfig = Field(default_factory=TuningConfig)

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


class ModelMetrics(BaseModel):
    """One per-model row in ``result.models`` (a LIST so the frontend can ``.map``)."""

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


class RunResponse(BaseModel):
    """Top-level envelope for ``POST /api/v1/run`` (the forward-compat seam)."""

    status: str = "ok"  # "ok" | "error"
    # 1.1 (additive): adds the optional ``result.tuning`` block; all 1.0 fields are unchanged.
    schema_version: str = "1.1"
    result: RunResult | None = None
    error: str | None = None
