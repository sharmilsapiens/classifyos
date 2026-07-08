"""Opt-in MLflow run logging + model persistence (Databricks integration — Phase A).

Design of record: ``docs/databricks_integration.md`` §6 (Phase A). This is the "log a whole
run to MLflow" layer, added with the SAME discipline as the ``shap`` / ``optuna`` / ``openai``
integrations already in the engine:

* **OFF by default** — nothing here runs unless ``config["mlflow"]["enabled"]`` is set.
* **Lazy import** — ``mlflow`` (and the flavor sub-modules) are imported *inside* the
  functions, never at module load, so a run with the flag off — or an install without mlflow —
  never touches the dependency.
* **Report-only** — every failure path (missing package, unreachable tracking store, a single
  model that will not serialize, a bad artifact) is caught and logged; logging NEVER aborts a
  training run. The worst case is "no / partial MLflow record", never a failed run.

What one call to :func:`log_run` records for a run:

* :func:`mlflow.log_params` — a flattened view of the run config (searchable metadata; the full
  config lives in the ``run_profile.json`` artifact logged below).
* :func:`mlflow.log_metrics` — each successful model's headline HELD-OUT TEST metrics the runner
  already computed, namespaced ``<model>.<metric>`` so several models coexist in one run.
* :func:`mlflow.log_artifact` — the existing engine artifacts (the CSVs, ``run_profile.json``,
  the PNGs) exactly as written to ``OUTPUT_DIR``. The caller resolves each concrete path via
  :meth:`StorageAdapter.path_for` and hands them in, so ALL artifact I/O stays behind the
  storage abstraction (CLAUDE.md rule). MLflow's own ``./mlruns`` store is MLflow's internal
  mechanism — like Optuna's study storage — not ClassifyOS artifact I/O.
* ``mlflow.<flavor>.log_model`` — one saved model per fitted algorithm with the flavor-native
  serializer: ``mlflow.xgboost`` for XGBoost, ``mlflow.lightgbm`` for LightGBM, ``mlflow.sklearn``
  for everything else. Each model is UNWRAPPED to its base estimator first (peeling the
  calibration / threshold meta-estimators) exactly the way
  :meth:`ModelWrapper.feature_importance` does — both because that is where the native
  estimator lives and because it is the only object the ``xgboost`` / ``lightgbm`` flavors can
  serialize. The calibration/threshold policy is not lost to the record — it is captured in the
  logged params (it is part of the run config).

[RISK] leakage — every call here happens AFTER training and reads nothing back into
fit/transform. It serializes already-fitted estimators and copies already-written artifact
files; it mutates no ML state and re-fits nothing.

Local store (this phase): this module sets NO tracking URI — it relies entirely on MLflow's own
env-driven resolution, so the store is swappable by ``MLFLOW_TRACKING_URI`` alone (the later
Interim-2a Postgres / Databricks swap is then a pure config change, no code change; design §3.3 /
§6.5). With that env var unset, MLflow 3.x's local default is a sqlite ``mlflow.db`` backend plus
an ``./mlruns`` artifact folder — both local, no server. The one wrinkle: MLflow 3.x puts the
legacy plain-file store (``./mlruns``-only, no DB) in "maintenance mode" and refuses it unless
``MLFLOW_ALLOW_FILE_STORE=true``; :func:`_maybe_allow_file_store` sets that opt-out only for an
explicit ``file:`` (or schemeless-path) tracking URI, and never touches a ``sqlite`` /
``postgresql`` / ``http`` / ``databricks`` URI.
"""

from __future__ import annotations

import logging
import math
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

#: Headline HELD-OUT TEST metrics logged per successful model (a subset of the metrics row the
#: runner computes — the same scalars the API scoreboard shows).
_HEADLINE_METRIC_KEYS = (
    "accuracy",
    "f1_weighted",
    "f1_macro",
    "precision_weighted",
    "recall_weighted",
    "roc_auc",
    "pr_auc",
    "mcc",
    "log_loss",
)

#: Max characters kept per flattened param VALUE. Params are searchable metadata only — the
#: full-fidelity config is logged as the ``run_profile.json`` artifact — so truncating long /
#: nested values (e.g. a free-text ``dataset_context``) keeps well within MLflow's limits.
_PARAM_VALUE_MAX = 250

#: Characters MLflow permits in a param / metric KEY; anything else is replaced with ``_``.
_KEY_SAFE = re.compile(r"[^A-Za-z0-9_\-. /:]")


def _load_mlflow() -> Any | None:
    """Import ``mlflow`` lazily, returning the module or ``None`` if it is unavailable.

    A missing or broken install must never abort a run (report-only), so an import failure is
    logged and swallowed — the caller then simply skips logging.
    """
    try:
        import mlflow  # noqa: PLC0415 — lazy by design (opt-in dependency)

        return mlflow
    except Exception:  # noqa: BLE001 — a missing/broken mlflow must never abort a run
        logger.warning(
            "MLflow logging was requested but the 'mlflow' package is unavailable; "
            "skipping (install 'mlflow' to enable it)."
        )
        return None


def _maybe_allow_file_store() -> None:
    """Opt out of MLflow 3.x plain-file-store "maintenance mode" when a ``file:`` store is in use.

    MLflow 3.x's local *default* is a sqlite backend (``mlflow.db``) + an ``./mlruns`` artifact
    folder, which needs no opt-out. But an explicit plain-file tracking store (``file:`` URI, or a
    bare filesystem path, or nothing yet resolved) is refused unless ``MLFLOW_ALLOW_FILE_STORE=true``.
    We set that opt-out only for those file-store cases and never override a database / managed URI
    (``sqlite://``, ``postgresql://``, ``http(s)://``, ``databricks``). Must run before MLflow
    resolves the store (before ``set_experiment`` / ``start_run``); it only touches ``os.environ``
    so no MLflow import is needed here.
    """
    uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    is_file_store = not uri or uri.startswith("file:") or "://" not in uri
    if is_file_store:
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")


def _safe_key(key: str) -> str:
    """Coerce a param/metric key fragment to MLflow's allowed character set."""
    return _KEY_SAFE.sub("_", str(key))


def _truncate(value: str) -> str:
    """Clip a stringified param value to :data:`_PARAM_VALUE_MAX` characters."""
    return value if len(value) <= _PARAM_VALUE_MAX else value[: _PARAM_VALUE_MAX - 1] + "…"


def _flatten_params(config: dict[str, Any], prefix: str = "", out: dict[str, str] | None = None) -> dict[str, str]:
    """Flatten a nested config into dotted ``{key: str}`` params for :func:`mlflow.log_params`.

    Nested dicts recurse with dotted keys (``feature_engineering.enabled``); lists/tuples are
    JSON-ish joined; ``None`` becomes ``"None"``; every value is truncated. Keys are sanitized so
    an arbitrary user-supplied fragment (e.g. a JSON-flattened column name in ``column_context``)
    can never produce an MLflow-invalid param key.
    """
    import json

    if out is None:
        out = {}
    for raw_key, value in config.items():
        key = f"{prefix}{_safe_key(raw_key)}"
        if isinstance(value, dict):
            if value:
                _flatten_params(value, f"{key}.", out)
            else:
                out[key] = "{}"
        elif isinstance(value, (list, tuple)):
            out[key] = _truncate(json.dumps(list(value), default=str))
        elif value is None:
            out[key] = "None"
        else:
            out[key] = _truncate(str(value))
    return out


def _headline_metrics(metrics_records: list[dict[str, Any]]) -> dict[str, float]:
    """Per-model headline TEST metrics as ``{"<model>.<metric>": value}`` for ``log_metrics``.

    Only successful (``status == "ok"``) rows contribute, and ``None``/``NaN``/``Inf`` values are
    skipped (MLflow cannot log them). Keyed by ``<model>.<metric>`` so several models coexist in
    the one run without clobbering each other.
    """
    out: dict[str, float] = {}
    for record in metrics_records:
        if record.get("status") != "ok":
            continue
        model = _safe_key(record.get("model", "model"))
        for metric in _HEADLINE_METRIC_KEYS:
            value = record.get(metric)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isnan(number) or math.isinf(number):
                continue
            out[f"{model}.{metric}"] = number
    return out


def _log_one_model(mlflow: Any, name: str, wrapper: Any) -> str | None:
    """Log ONE fitted model with the flavor-native serializer; return its model URI or ``None``.

    The wrapper's fitted estimator is unwrapped to its base estimator (peeling the
    calibration / threshold meta-estimators) with the SAME helper
    :meth:`ModelWrapper.feature_importance` uses, then dispatched to the flavor that matches the
    base estimator's type: XGBoost → ``mlflow.xgboost``, LightGBM → ``mlflow.lightgbm``,
    everything else (incl. the multilabel ``OneVsRestClassifier`` wrapper) → ``mlflow.sklearn``
    with cloudpickle serialization (robust across the calibrated / OvR estimators the engine
    produces). Report-only: any failure is logged and yields ``None`` so one bad model never
    aborts the run or the rest of the logging.
    """
    from .models.decision import unwrap_base_estimator

    try:
        fitted = getattr(wrapper, "model", None)
        if fitted is None:
            return None
        base = unwrap_base_estimator(fitted)
        cls = type(base).__name__
        if cls == "XGBClassifier":
            import mlflow.xgboost  # noqa: PLC0415 — lazy flavor import

            info = mlflow.xgboost.log_model(base, name=name)
        elif cls == "LGBMClassifier":
            import mlflow.lightgbm  # noqa: PLC0415

            info = mlflow.lightgbm.log_model(base, name=name)
        else:
            import mlflow.sklearn  # noqa: PLC0415

            # cloudpickle (not the new skops default) so calibrated / OvR / booster-backed
            # sklearn estimators all round-trip without skops "untrusted type" load failures.
            info = mlflow.sklearn.log_model(
                base, name=name, serialization_format="cloudpickle"
            )
        return info.model_uri
    except Exception:  # noqa: BLE001 — report-only; a single model must not break the run
        logger.exception("MLflow: failed to log model %r; continuing without it", name)
        return None


def log_run(
    *,
    config: dict[str, Any],
    metrics_records: list[dict[str, Any]],
    models: dict[str, Any],
    artifact_paths: list[str],
    experiment: str,
    run_name: str | None,
) -> dict[str, Any] | None:
    """Log one completed ClassifyOS run to MLflow. Report-only — never raises.

    Args:
        config: The (effective, deep-copied) run config — logged as flattened params.
        metrics_records: ``ModelRunner.metrics_df_`` as records; the successful rows' headline
            TEST metrics are logged, namespaced by model.
        models: ``{model_name: fitted ModelWrapper}`` — one saved model is logged per entry.
        artifact_paths: Concrete, already-existing OUTPUT_DIR paths (resolved by the caller via
            :meth:`StorageAdapter.path_for`) to attach as run artifacts.
        experiment: MLflow experiment name to log under.
        run_name: Optional MLflow run name (``None`` → MLflow auto-generates one).

    Returns:
        ``{"run_id", "experiment_id", "tracking_uri", "models": {name: model_uri}}`` on success
        (``models`` may be partial if a particular model failed to serialize), or ``None`` if
        MLflow was unavailable or the run could not be opened.
    """
    mlflow = _load_mlflow()
    if mlflow is None:
        return None

    try:
        _maybe_allow_file_store()
        mlflow.set_experiment(experiment)
        model_uris: dict[str, str] = {}
        with mlflow.start_run(run_name=run_name) as run:
            run_id = run.info.run_id
            experiment_id = run.info.experiment_id

            # params (flattened config) — searchable metadata; full config is in run_profile.json
            try:
                mlflow.log_params(_flatten_params(config))
            except Exception:  # noqa: BLE001 — report-only
                logger.exception("MLflow: log_params failed; continuing")

            # a couple of tags for provenance / filtering
            try:
                mlflow.set_tags(
                    {
                        "classifyos.source": "engine",
                        "classifyos.problem_type": str(config.get("problem_type", "")),
                        "classifyos.input_file": str(config.get("input_file", "")),
                    }
                )
            except Exception:  # noqa: BLE001 — report-only
                logger.exception("MLflow: set_tags failed; continuing")

            # metrics (per-model headline test metrics)
            try:
                metrics = _headline_metrics(metrics_records)
                if metrics:
                    mlflow.log_metrics(metrics)
            except Exception:  # noqa: BLE001 — report-only
                logger.exception("MLflow: log_metrics failed; continuing")

            # artifacts (the engine's existing output files) — grouped under a "classifyos" subdir
            for path in artifact_paths:
                try:
                    mlflow.log_artifact(path, artifact_path="classifyos")
                except Exception:  # noqa: BLE001 — report-only
                    logger.exception("MLflow: failed to log artifact %s; continuing", path)

            # one saved model per fitted algorithm (flavor-native)
            for name, wrapper in models.items():
                uri = _log_one_model(mlflow, name, wrapper)
                if uri:
                    model_uris[name] = uri

        logger.info(
            "MLflow: logged run %s (experiment %s) with %d model(s) to %s",
            run_id,
            experiment_id,
            len(model_uris),
            mlflow.get_tracking_uri(),
        )
        return {
            "run_id": run_id,
            "experiment_id": experiment_id,
            "tracking_uri": mlflow.get_tracking_uri(),
            "models": model_uris,
        }
    except Exception:  # noqa: BLE001 — the whole logging layer is report-only
        logger.exception("MLflow logging failed; the training run is unaffected")
        return None
