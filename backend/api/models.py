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
* The read-path (``GET /runs``, the input-source picker) and Databricks orchestration models —
  each backs a specific HTTP endpoint. The RESPONSE models for the **locked** ``/api/v1/run``
  schema now live in the engine (:mod:`classifyos.envelope.schema`) so the Databricks Job notebook
  can build a byte-identical envelope from the wheel; they are re-exported near the top of this
  module, so ``from api.models import RunResponse`` (etc.) keeps working unchanged.
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

# The locked-contract version + all RESPONSE models live in the engine
# (:mod:`classifyos.envelope.schema`) so the Databricks Job notebook can build a byte-identical
# ``/run`` envelope from the installed wheel (no ``backend/`` checkout needed). They are re-exported
# here so the FastAPI layer and its tests keep importing them from ``api.models`` unchanged.
# ``SCHEMA_VERSION`` is also consumed by the read-path / Databricks models defined further down.
from classifyos.envelope.schema import (  # noqa: F401  (re-exported for API compatibility)
    SCHEMA_VERSION,
    ArtifactEntry,
    ClassReportRow,
    ConfusionMatrixEntry,
    ExplanationRow,
    FeatureImpactRow,
    FeatureImportanceRow,
    MlflowInfo,
    ModelExplanation,
    ModelMetrics,
    PermutationImportanceRow,
    PredictionRow,
    PredictionsBlock,
    RunMeta,
    RunResponse,
    RunResult,
    RunTuning,
    TrainMetrics,
)

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

    # Reject unknown keys so a typo'd field is a clear 422, not a silent no-op. ``populate_by_name``
    # lets the ``schema`` delta field be set by its alias ``schema`` (its Python name is ``db_schema``
    # to avoid shadowing ``BaseModel.schema``).
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: str = "file"
    connection_env: str = "CLASSIFYOS_PG_DSN"
    table: str | None = None
    query: str | None = None
    # Databricks Delta source (§6.6 Step 4) — ignored for file/postgres. When ``type="delta"`` the
    # run reads a Unity Catalog table (``catalog.schema.table``) on the cluster and materializes a
    # snapshot to ``input_file`` (which must end in .parquet/.csv). ``build_config`` validates these.
    catalog: str | None = None
    db_schema: str | None = Field(None, alias="schema")
    limit: int | None = None


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

    # --- Databricks orchestration (schema 1.11, additive; not an engine knob) ---
    # Which existing Databricks cluster the training Job runs on. OPTIONAL: a non-empty cluster id
    # (from the UI cluster picker) overrides the server's ``DATABRICKS_JOB_CLUSTER_ID`` env var;
    # ``None``/absent falls back to that env var (server-only deployments are unchanged). Consumed
    # ONLY by the databricks execution backend — it is NOT a ``DEFAULT_CONFIG`` key, so
    # ``to_engine_config`` excludes it (build_config rejects unknown keys) and the LOCAL backend
    # ignores it entirely.
    cluster_id: str | None = None

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
        # ``cluster_id`` is a Databricks-submission knob, not an engine config key — build_config
        # rejects unknown keys, so it is excluded here (the databricks route reads it separately).
        overrides = self.model_dump(exclude={"input_file", "target", "feature_cols", "cluster_id"})
        # The engine reads each user-feature spec as a plain dict and treats a present
        # ``unit``/``col_b`` of ``None`` as invalid; dump each spec with ``exclude_none`` so
        # the optional keys drop out and the shape matches the engine's spec exactly.
        overrides["user_features"] = [
            spec.model_dump(exclude_none=True) for spec in self.user_features
        ]
        # Dump input_source BY ALIAS so the delta ``schema`` field lands under the key the engine
        # expects (``schema``, not the Python field name ``db_schema``). File/postgres runs are
        # unaffected (their extra delta keys default to None and are ignored by build_config).
        overrides["input_source"] = self.input_source.model_dump(by_alias=True)
        return build_config(
            self.input_file,
            self.target,
            self.feature_cols,
            **overrides,
        )


# NOTE: the RESPONSE models (RunMeta ... RunResult, RunResponse) that used to live here were
# moved to the engine (classifyos.envelope.schema) and are re-exported near the top of this
# module. Only the read-path and Databricks orchestration models remain defined below.


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


# --------------------------------------------------------------------------- #
# Input-source read-path models (Interim 2b UI — list + select a DB table)    #
# --------------------------------------------------------------------------- #
#
# These ride the upload/profile side of the API (NOT the locked ``/run`` envelope) so the
# dashboard can offer a "Import from database" picker without a hand-crafted request. They are
# purely additive: no ``/run`` field changes, so ``schema_version`` is unaffected.


class InputTablesResponse(BaseModel):
    """``GET /api/v1/input-sources/tables`` — the tables available in the input DB.

    A lightweight list the dashboard's "Import from database" picker renders. ``connection_env``
    echoes the env var whose DSN was read (never the credential itself). An unreachable /
    unconfigured DB is a clean 503 at the route (mirroring the MLflow read-path discipline), so a
    200 here always carries a real (possibly empty) table list.
    """

    connection_env: str
    tables: list[str] = Field(default_factory=list)


class InputSourceSelectRequest(BaseModel):
    """Body for ``POST /api/v1/input-sources/select`` — pick a DB table/query to run on.

    Materializes the chosen table (or query) to a snapshot file under DATA_DIR via the **exact
    Interim-2b engine path** (:func:`classifyos.io.sql_source.materialize_source`), profiles that
    snapshot with the same ``inspect_file`` the ``/upload`` flow uses, and returns the same
    ``InspectProfile`` shape — so the frontend treats a DB table exactly like an uploaded file.
    The response also carries the ``input_source`` block the frontend sets on the run config, so
    the actual ``/run`` reads from Postgres (the 2b path), not merely the profiling snapshot.

    Provide EXACTLY ONE of ``table`` (→ ``SELECT * FROM <table>``, validated to a safe SQL
    identifier) or ``query`` (a raw SQL SELECT). ``connection_env`` names the server-side env var
    holding the DSN (never a credential here); ``target`` is optional (its class distribution is
    profiled when given, mirroring ``/upload?target=``). The engine's ``build_config`` validator
    (``_validate_input_source``) is the authoritative check — a bad shape is a clean 422.
    """

    # Reject unknown keys so a typo'd field is a clear 422, not a silent no-op.
    model_config = ConfigDict(extra="forbid")

    connection_env: str = "CLASSIFYOS_PG_DSN"
    table: str | None = None
    query: str | None = None
    target: str | None = None


# --------------------------------------------------------------------------- #
# Databricks orchestration models (schema 1.11, §6.6 Step 6 — async Jobs)      #
# --------------------------------------------------------------------------- #
#
# These describe the DATABRICKS execution backend only. When the server runs the default LOCAL
# backend, ``POST /run`` returns the usual :class:`RunResponse` and none of these are emitted.


class RunSubmission(BaseModel):
    """``POST /api/v1/run`` response in the DATABRICKS backend (NEW in 1.11).

    Returned immediately after submitting the Databricks Job — the run does NOT block. ``job_id``
    is our own persistent handle (used in the ``/run/{job_id}/status`` + ``/results`` paths);
    ``run_id`` is the Databricks run id the service polls. ``status`` starts at ``"PENDING"``.
    """

    job_id: str
    run_id: str
    status: str = "PENDING"
    schema_version: str = SCHEMA_VERSION


class JobStatusResponse(BaseModel):
    """``GET /api/v1/run/{job_id}/status`` (NEW in 1.11).

    ``status`` is one of ``PENDING | RUNNING | COMPLETED | FAILED`` (mapped from the Databricks
    ``RunState``); ``message`` is the workspace's human-readable state message (or the error on a
    FAILED run). Fetch results via ``GET /run/{job_id}/results`` once ``status == "COMPLETED"``.
    """

    job_id: str
    run_id: str | None = None
    status: str
    message: str | None = None
    schema_version: str = SCHEMA_VERSION


class CatalogsResponse(BaseModel):
    """``GET /api/v1/databricks/catalogs`` — Unity Catalog catalog names (NEW in 1.11)."""

    catalogs: list[str] = Field(default_factory=list)


class SchemasResponse(BaseModel):
    """``GET /api/v1/databricks/schemas?catalog=`` — schema names in a catalog (NEW in 1.11)."""

    catalog: str
    schemas: list[str] = Field(default_factory=list)


class TablesResponse(BaseModel):
    """``GET /api/v1/databricks/tables?catalog=&schema=`` — table names in a schema (NEW in 1.11)."""

    catalog: str
    schema_name: str = Field(..., alias="schema")
    tables: list[str] = Field(default_factory=list)

    # ``schema`` shadows BaseModel.schema(); expose it via an alias but let callers pass ``schema``.
    model_config = ConfigDict(populate_by_name=True)


class ClusterInfo(BaseModel):
    """One cluster row in ``GET /api/v1/databricks/clusters`` (NEW in 1.11).

    A usable Databricks cluster a run can target: ``cluster_id`` is the handle passed to the Jobs
    API as ``existing_cluster_id`` (and to ``/run`` as the optional ``cluster_id`` field);
    ``cluster_name`` is the display label; ``state`` is the cluster's current lifecycle state (only
    the submittable ``RUNNING``/``TERMINATED`` states are surfaced — see
    :func:`api.databricks.list_clusters`).
    """

    cluster_id: str
    cluster_name: str
    state: str


class ClustersResponse(BaseModel):
    """``GET /api/v1/databricks/clusters`` — usable clusters for the run-config picker (NEW in 1.11)."""

    clusters: list[ClusterInfo] = Field(default_factory=list)
