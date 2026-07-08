"""``POST /api/v1/run`` — execute a full classification run and return the locked schema.

This is the heart of the API. The body is a :class:`RunConfig` (validated by FastAPI before
this function runs). The function translates it into an engine config, runs the WHOLE
pipeline through :class:`~classifyos.runner.ModelRunner` (exactly as the CLI does), and then
**reshapes** the finished runner's state into the locked ``/api/v1/run`` response documented
in ``docs/api_contract.md``. It adds no ML — every number here was produced by the engine.

Two design points worth understanding as a reader:

* **Why a threadpool?** ``ModelRunner.run()`` is ordinary synchronous, CPU-heavy Python
  (training models can take seconds to minutes). If we called it directly inside this
  ``async def`` endpoint, it would block FastAPI's single event loop — the server could not
  even answer ``/health`` until the run finished. ``run_in_threadpool`` moves the blocking
  work onto a worker thread so the server stays responsive.
* **Synchronous + gateway-timeout limitation.** This endpoint blocks until the run completes
  and returns the result in one response. A long run (big data, many algorithms, tuning on)
  can exceed a reverse-proxy/gateway timeout. v1.0 accepts this; a background-job path
  (submit → poll → fetch) is deferred to v1.5 (recorded in plan_tweak).
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from classifyos.evaluation.curves import compute_curve_points
from classifyos.io.sql_source import InputSourceError
from classifyos.io.storage import StorageAdapter
from classifyos.runner import RESULTS_CSV_KEY, ModelRunner

from ..artifacts import collect_artifacts
from ..deps import get_storage
from ..models import RunConfig, RunResponse
from ..serialize import safe_jsonify

router = APIRouter(tags=["run"])

#: Per-model cap on the prediction rows returned for DISPLAY. The full per-sample table is
#: always written to classification_results.csv (fetch via /outputs); the JSON carries only
#: a preview so the response stays small. Confusion matrices and curves are NOT sampled —
#: they are always computed on the FULL test set.
PREDICTION_SAMPLE_PER_MODEL = 100

# Substrings that mark an engineered interaction column (the naming convention in CLAUDE.md).
_INTERACTION_MARKERS = ("_x_", "_div_", "_minus_")


@router.post("/run", response_model=None)
async def run_endpoint(
    cfg: RunConfig,
    storage: StorageAdapter = Depends(get_storage),
) -> Any:
    """Run the full pipeline for ``cfg`` and return the locked result envelope.

    On a bad config (missing target, unknown enum, target in features, …) the engine's
    ``build_config`` raises ``ValueError`` → HTTP 422. On a failure while executing
    (e.g. the input file does not exist) we return the ``status="error"`` envelope with the
    message. On success we return the full ``result`` block (run metadata, per-model metrics,
    a sampled predictions preview, full-test confusion matrices, per-class reports, ranked
    feature impact, ROC/PR curve points, and the artifact list).
    """
    # 1. Translate the web request into a validated engine config. build_config is the single
    #    authoritative validator; a problem there is a client error (422), not a 500.
    try:
        engine_config = cfg.to_engine_config()
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    # 2-3. Run the synchronous pipeline off the event loop (see module docstring).
    runner = ModelRunner(engine_config, storage)
    try:
        await run_in_threadpool(runner.run)
    except (FileNotFoundError, ValueError, InputSourceError) as exc:
        # Known input problems surfaced at run time: a missing file, an unparseable column, or a
        # postgres input source that could not be read/materialized (Interim 2b — unset connection
        # env var, unreachable DB, failed query, empty result). All are 400-style run errors.
        body = RunResponse(status="error", result=None, error=f"{type(exc).__name__}: {exc}")
        return JSONResponse(status_code=400, content=body.model_dump())

    # 4. Reshape the finished runner into the locked schema, then make it JSON-safe
    #    (numpy → Python, NaN/Inf → None) so encoding can never 500.
    result = _build_result(runner, storage)
    response = RunResponse(status="ok", result=safe_jsonify(result))

    # 5. If this run was logged to MLflow (opt-in mlflow.enabled succeeded), persist the rendered
    #    envelope as a run artifact so the dashboard's Runs view can reload it byte-identically
    #    (Interim 2a). Report-only — a failure only means the run is not reloadable; the /run
    #    response is unaffected. [RISK] leakage — this writes the already-rendered result; it
    #    reads nothing back into fit/transform.
    mlflow_run = getattr(runner, "mlflow_run_", None)
    if mlflow_run and mlflow_run.get("run_id"):
        from ..mlflow_read import snapshot_result

        # by_alias so the snapshot is byte-identical to the wire response FastAPI sends
        # (e.g. ClassReportRow's ``class`` alias) — a reload then matches the live run exactly.
        snapshot_result(mlflow_run["run_id"], response.model_dump(by_alias=True))

    return response


# --------------------------------------------------------------------------- #
# reshaping helpers — pure data plumbing, no ML                               #
# --------------------------------------------------------------------------- #


def _build_result(runner: ModelRunner, storage: StorageAdapter) -> dict[str, Any]:
    """Assemble the ``result`` block from a completed runner (all values engine-produced)."""
    return {
        "run": _run_meta(runner),
        "models": _models(runner),
        "predictions": _predictions(runner),
        "confusion_matrix": _confusion_matrix(runner),
        "class_report": _class_report(runner),
        "feature_impact": _feature_impact(runner),
        "curves": _curves(runner),
        "artifacts": collect_artifacts(storage),
        "tuning": _tuning(runner),
        "feature_importance": _feature_importance(runner),
        "permutation_importance": _permutation_importance(runner),
        "explanations": _explanations(runner),
        "mlflow": _mlflow(runner),
    }


def _run_meta(runner: ModelRunner) -> dict[str, Any]:
    """``result.run`` — curated metadata, derived from the run profile + active features."""
    profile = runner.run_profile_ or {}
    active = list(runner.active_features_)
    interaction_cols = [c for c in active if any(m in c for m in _INTERACTION_MARKERS)]
    return {
        "target": profile.get("target"),
        "problem_type": profile.get("problem_type"),
        "features": profile.get("features", []),
        "active_features": active,
        "interaction_cols": interaction_cols,
        "class_distribution": profile.get("class_distribution", {}),
        "n_rows": profile.get("n_rows", 0),
        "n_train": profile.get("n_train", 0),
        "n_test": profile.get("n_test", 0),
        "class_balance": profile.get("class_balance"),
        "class_weight": profile.get("class_weight"),
        # run_profile stores the list of succeeded model names; the schema wants a count.
        "models_succeeded": len(profile.get("models_succeeded", [])),
        "timestamp": profile.get("timestamp"),
    }


def _models(runner: ModelRunner) -> list[dict[str, Any]]:
    """``result.models`` — one row per requested algorithm (a LIST; includes failed rows)."""
    if runner.metrics_df_ is None or runner.metrics_df_.empty:
        return []
    rows: list[dict[str, Any]] = []
    for record in runner.metrics_df_.to_dict(orient="records"):
        rows.append(
            {
                "name": record.get("model"),
                "status": record.get("status"),
                # Headline metrics are the HELD-OUT TEST split (unchanged since 1.0).
                "accuracy": record.get("accuracy"),
                "f1_weighted": record.get("f1_weighted"),
                "f1_macro": record.get("f1_macro"),
                "precision_weighted": record.get("precision_weighted"),
                "recall_weighted": record.get("recall_weighted"),
                "roc_auc": record.get("roc_auc"),
                "pr_auc": record.get("pr_auc"),
                "log_loss": record.get("log_loss"),
                "mcc": record.get("mcc"),
                # NEW in 1.2 (additive): the same headline metrics on the PRE-balance TRAIN
                # split, for the overfit gap (test − train). See docs/api_contract.md.
                "train": _train_block(record),
                # NEW in 1.5 (additive): the decision policy applied to this model — the
                # effective binary operating threshold (None for multiclass/multilabel) and
                # whether probabilities are calibrated.
                "decision_threshold": record.get("decision_threshold"),
                "calibrated": record.get("calibrated"),
                "error": record.get("error"),
            }
        )
    return rows


# Headline metric keys mirrored on the train side (engine writes them as ``train_<key>``).
_TRAIN_METRIC_KEYS = (
    "accuracy",
    "f1_weighted",
    "f1_macro",
    "precision_weighted",
    "recall_weighted",
    "roc_auc",
    "pr_auc",
    "log_loss",
    "mcc",
)


def _train_block(record: dict[str, Any]) -> dict[str, Any]:
    """``models[].train`` — pre-balance TRAIN headline metrics (NEW in schema 1.2).

    Reads the ``train_<key>`` columns the engine adds to each metrics row. Always present
    (every value is ``None`` for a failed model, or when train evaluation was unavailable),
    so the block's shape is stable; only the values vary.
    """
    return {key: record.get(f"train_{key}") for key in _TRAIN_METRIC_KEYS}


def _predictions(runner: ModelRunner) -> dict[str, Any]:
    """``result.predictions`` — first-N-per-model preview; full table via the artifacts CSV."""
    df = runner.predictions_df_
    if df is None or df.empty:
        return {
            "sample_rows": [],
            "sampled": False,
            "rows_returned": 0,
            "rows_total": 0,
            "full_csv": RESULTS_CSV_KEY,
        }

    rows_total = int(len(df))
    # First N rows per model (group order preserved) — the display preview.
    sampled_df = df.groupby("model", sort=False).head(PREDICTION_SAMPLE_PER_MODEL)
    prob_cols = [c for c in df.columns if c.startswith("probability_")]

    sample_rows: list[dict[str, Any]] = []
    for record in sampled_df.to_dict(orient="records"):
        probabilities = {
            col[len("probability_"):]: record.get(col) for col in prob_cols
        }
        sample_rows.append(
            {
                "model": record.get("model"),
                "sample_index": record.get("sample_index"),
                "actual": str(record.get("actual")),
                "predicted": str(record.get("predicted")),
                "confidence": record.get("confidence"),
                "correct_flag": bool(record.get("correct_flag")),
                "probabilities": probabilities,
            }
        )

    rows_returned = len(sample_rows)
    return {
        "sample_rows": sample_rows,
        "sampled": rows_returned < rows_total,
        "rows_returned": rows_returned,
        "rows_total": rows_total,
        "full_csv": RESULTS_CSV_KEY,
    }


def _confusion_matrix(runner: ModelRunner) -> dict[str, Any]:
    """``result.confusion_matrix`` — per successful model, on the FULL test set."""
    out: dict[str, Any] = {}
    for name, metrics in runner.metrics_.items():
        cm = metrics.get("confusion_matrix")
        if cm is None:
            continue
        out[name] = {
            "labels": [str(c) for c in (metrics.get("labels") or [])],
            "matrix": cm,
        }
    return out


def _class_report(runner: ModelRunner) -> dict[str, Any]:
    """``result.class_report`` — per class (and avg rows) per successful model."""
    out: dict[str, list[dict[str, Any]]] = {}
    for name, metrics in runner.metrics_.items():
        report = metrics.get("classification_report") or {}
        rows: list[dict[str, Any]] = []
        for label, vals in report.items():
            if not isinstance(vals, dict):  # the scalar "accuracy" entry — skip
                continue
            rows.append(
                {
                    "class": label,
                    "precision": vals.get("precision"),
                    "recall": vals.get("recall"),
                    "f1": vals.get("f1-score"),
                    "support": vals.get("support"),
                }
            )
        out[name] = rows
    return out


def _feature_impact(runner: ModelRunner) -> list[dict[str, Any]]:
    """``result.feature_impact`` — the ranked impact frame as records (preserves id_like)."""
    fi = runner.feature_impact_
    if fi is None or not isinstance(fi, pd.DataFrame) or fi.empty:
        return []
    return fi.to_dict(orient="records")


def _feature_importance(
    runner: ModelRunner,
) -> dict[str, list[dict[str, Any]]] | None:
    """``result.feature_importance`` — native per-model importance (NEW in schema 1.3, additive).

    Reshapes the runner's ``feature_importances_`` ({model: {feature: value} | None}) into
    ``{model: [{feature, importance, rank}, …]}``, ranked descending within each model. Models
    exposing no native importance (RBF-SVM, GaussianNB) are omitted. Returns ``None`` when no
    model exposes any, so the field is null and an SVM/NB-only run matches the earlier schema.
    Post-training and model-derived — distinct from the pre-training ``feature_impact`` screen.
    No ML here — pure plumbing of values the engine already computed.
    """
    by_model = getattr(runner, "feature_importances_", None) or {}
    out: dict[str, list[dict[str, Any]]] = {}
    for name, importances in by_model.items():
        if not importances:  # None (no native importance) or empty dict
            continue
        ranked = sorted(importances.items(), key=lambda kv: kv[1], reverse=True)
        out[name] = [
            {"feature": feature, "importance": float(value), "rank": rank}
            for rank, (feature, value) in enumerate(ranked, start=1)
        ]
    return out or None


def _permutation_importance(
    runner: ModelRunner,
) -> dict[str, list[dict[str, Any]]] | None:
    """``result.permutation_importance`` — model-agnostic permutation importance (NEW in 1.4, additive).

    Reshapes the runner's ``permutation_importances_`` ({model: {feature: value} | None}) into
    ``{model: [{feature, importance, rank}, …]}``, ranked descending within each model. Unlike
    ``feature_importance`` this is present for EVERY model (it only needs ``predict``), so the
    SVM and NaiveBayes that produce no native importance DO appear here. A model whose measure
    could not be computed (``None``) is omitted; returns ``None`` when none could be computed,
    so a run that produced none matches the earlier schema. No ML here — pure plumbing of values
    the engine already computed (post-training, on held-out test predictions; no refit).
    """
    by_model = getattr(runner, "permutation_importances_", None) or {}
    out: dict[str, list[dict[str, Any]]] = {}
    for name, importances in by_model.items():
        if not importances:  # None (not computed) or empty dict
            continue
        ranked = sorted(importances.items(), key=lambda kv: kv[1], reverse=True)
        out[name] = [
            {"feature": feature, "importance": float(value), "rank": rank}
            for rank, (feature, value) in enumerate(ranked, start=1)
        ]
    return out or None


def _explanations(runner: ModelRunner) -> dict[str, dict[str, Any]] | None:
    """``result.explanations`` — per-row SHAP explanations (NEW in schema 1.6, additive).

    Passes through the runner's ``explanations_`` ({model: {"method", "rows": [...]} | None}),
    LOCAL explainability — why the model predicted what it did for individual held-out test
    rows. Present only when the opt-in ``explainability`` config was enabled; a model whose
    explainer failed (or multilabel, unsupported in v1) is omitted. Returns ``None`` when no
    model produced any, so a run without explainability matches the earlier schema exactly.
    No ML here — pure plumbing of values the engine already computed (post-training; no refit).
    """
    by_model = getattr(runner, "explanations_", None) or {}
    out: dict[str, dict[str, Any]] = {}
    for name, result in by_model.items():
        if not result or not result.get("rows"):  # None (failed/off) or no rows
            continue
        out[name] = {
            "method": result["method"],
            "rows": [
                {
                    "sample_index": row["sample_index"],
                    "explained_class": row["explained_class"],
                    "base_value": row["base_value"],
                    "prediction": row["prediction"],
                    "contributions": row["contributions"],
                    # NEW in 1.8 (additive): each feature's original raw value, keyed like
                    # ``contributions``; absent (→ {} default) if values weren't resolved.
                    "feature_values": row.get("feature_values") or {},
                    # NEW in 1.7 (additive): the LLM reason-code narrative when present; absent
                    # (→ None via the Pydantic default) for a SHAP-only row.
                    "narrative": row.get("narrative"),
                }
                for row in result["rows"]
            ],
        }
    return out or None


def _mlflow(runner: ModelRunner) -> dict[str, Any] | None:
    """``result.mlflow`` — pointer to where the run was logged in MLflow (NEW in schema 1.9, additive).

    Passes through the runner's ``mlflow_run_`` ({run_id, experiment_id, tracking_uri, models} or
    ``None``). Present only when the opt-in ``mlflow.enabled`` config was set AND logging
    succeeded; ``None`` otherwise, so a run without MLflow logging matches the earlier schema
    exactly. No ML here — pure plumbing of the pointer the engine already recorded (post-training).
    """
    info = getattr(runner, "mlflow_run_", None)
    if not info or not info.get("run_id"):
        return None
    return {
        "run_id": info.get("run_id"),
        "experiment_id": info.get("experiment_id"),
        "tracking_uri": info.get("tracking_uri"),
        "models": info.get("models", {}) or {},
    }


def _tuning(runner: ModelRunner) -> dict[str, Any] | None:
    """``result.tuning`` — per-model tuned hyperparameters (NEW in schema 1.1, additive).

    The runner already builds this block in ``run_profile.json`` (``tuning`` → ``enabled``,
    the tuning settings, ``tuned_models`` and ``best_params``); we simply copy it out. Returns
    ``None`` when tuning was OFF or produced no tuned params, so the field is null and a
    non-tuning run is unchanged from schema 1.0. No ML here — pure plumbing.
    """
    tuning = (runner.run_profile_ or {}).get("tuning")
    if not tuning or not tuning.get("enabled"):
        return None
    # Enabled but every study failed / returned nothing → no params to show; treat as null.
    if not tuning.get("best_params"):
        return None
    return tuning


def _curves(runner: ModelRunner) -> dict[str, Any]:
    """``result.curves`` — ROC/PR points per successful model, on the FULL test set.

    Uses the sanctioned :func:`compute_curve_points` helper — the SAME source ``plot2`` draws
    from — so the interactive chart and the PNG can never disagree. Always the full test set,
    never the sampled predictions preview.
    """
    out: dict[str, Any] = {}
    if runner.X_test_ is None or runner.y_test_ is None:
        return out
    # Multilabel curves read the binary indicator matrix as each label's truth; binary /
    # multiclass read the 1-D label vector. Both flow through the same helper.
    y_for_curves = (
        runner.y_test_indicator_
        if runner.problem_type_ == "multilabel"
        else runner.y_test_
    )
    if y_for_curves is None:
        return out
    for name, model in runner.models_.items():
        proba = model.predict_proba(runner.X_test_)
        out[name] = compute_curve_points(
            y_for_curves, proba, model.classes_, runner.problem_type_
        )
    return out
