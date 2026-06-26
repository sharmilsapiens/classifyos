"""Tests for ``POST /api/v1/run`` — validation, the locked response schema, JSON-safety.

The binary + multiclass runs are executed once each (session-scoped fixtures) against the
real engine and sample CSVs; these tests assert the response matches the schema locked in
``docs/api_contract.md``.
"""

from __future__ import annotations

import json
import math

import numpy as np

from api.serialize import safe_jsonify

RESULT_KEYS = {
    "run",
    "models",
    "predictions",
    "confusion_matrix",
    "class_report",
    "feature_impact",
    "curves",
    "artifacts",
    "tuning",  # NEW in schema 1.1 (additive); null on a non-tuning run
    "feature_importance",  # NEW in schema 1.3 (additive); per-model native importance
}

RUN_KEYS = {
    "target",
    "problem_type",
    "features",
    "active_features",
    "interaction_cols",
    "class_distribution",
    "n_rows",
    "n_train",
    "n_test",
    "class_balance",
    "class_weight",
    "models_succeeded",
    "timestamp",
}


# --------------------------------------------------------------------------- #
# 422 validation                                                              #
# --------------------------------------------------------------------------- #

_VALID = {
    "input_file": "policy_lapse.csv",
    "target": "will_lapse",
    "feature_cols": ["age", "annual_premium"],
}


def test_run_missing_target_is_422(api_client) -> None:
    body = {k: v for k, v in _VALID.items() if k != "target"}
    assert api_client.post("/api/v1/run", json=body).status_code == 422


def test_run_empty_target_is_422(api_client) -> None:
    assert api_client.post("/api/v1/run", json={**_VALID, "target": "  "}).status_code == 422


def test_run_missing_input_file_is_422(api_client) -> None:
    body = {k: v for k, v in _VALID.items() if k != "input_file"}
    assert api_client.post("/api/v1/run", json=body).status_code == 422


def test_run_empty_feature_cols_is_422(api_client) -> None:
    assert api_client.post("/api/v1/run", json={**_VALID, "feature_cols": []}).status_code == 422


def test_run_bad_enum_is_422(api_client) -> None:
    """An invalid enum (caught by the engine's build_config) becomes a 422, not a 500."""
    body = {**_VALID, "problem_type": "not-a-type"}
    assert api_client.post("/api/v1/run", json=body).status_code == 422


# --------------------------------------------------------------------------- #
# locked schema (binary)                                                      #
# --------------------------------------------------------------------------- #


def test_binary_run_envelope(binary_run_response) -> None:
    assert binary_run_response.status_code == 200
    body = binary_run_response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == "1.3"
    assert RESULT_KEYS == set(body["result"].keys())


def test_binary_run_feature_importance_block(binary_run_response) -> None:
    """``result.feature_importance`` (1.3) carries ranked native importance per tree/linear model.

    The binary fixture trains LogisticRegression + RandomForest, both of which expose native
    importances, so the block is a non-null dict keyed by model with ranked rows.
    """
    fi = binary_run_response.json()["result"]["feature_importance"]
    assert isinstance(fi, dict) and fi
    rf = fi["RandomForest"]
    assert [r["rank"] for r in rf] == list(range(1, len(rf) + 1))
    importances = [r["importance"] for r in rf]
    assert importances == sorted(importances, reverse=True)  # ranked desc within the model


def test_non_tuning_run_has_null_tuning(binary_run_response) -> None:
    """A run with tuning OFF (the default) carries ``result.tuning`` as null (1.1 additive)."""
    assert binary_run_response.json()["result"]["tuning"] is None


def test_binary_run_meta_block(binary_run_response) -> None:
    run = binary_run_response.json()["result"]["run"]
    assert RUN_KEYS == set(run.keys())
    assert run["problem_type"] == "binary"
    assert run["target"] == "will_lapse"
    assert run["n_rows"] == run["n_train"] + run["n_test"]
    assert isinstance(run["models_succeeded"], int) and run["models_succeeded"] >= 2


def test_binary_models_is_list_with_failed_row(binary_run_response) -> None:
    """models is a LIST; the bogus algorithm appears as a status='failed' row with an error."""
    models = binary_run_response.json()["result"]["models"]
    assert isinstance(models, list)
    by_name = {m["name"]: m for m in models}
    assert "NotAModel" in by_name
    failed = by_name["NotAModel"]
    assert failed["status"] == "failed"
    assert failed["error"]
    # A succeeded model carries real metrics.
    ok = [m for m in models if m["status"] == "ok"]
    assert ok and ok[0]["f1_weighted"] is not None


_TRAIN_KEYS = {
    "accuracy",
    "f1_weighted",
    "f1_macro",
    "precision_weighted",
    "recall_weighted",
    "roc_auc",
    "pr_auc",
    "log_loss",
    "mcc",
}


def test_binary_models_carry_train_block(binary_run_response) -> None:
    """Each model row carries the additive ``train`` block (schema 1.2) — pre-balance metrics."""
    models = binary_run_response.json()["result"]["models"]
    by_name = {m["name"]: m for m in models}

    # A succeeded model: train block present, fully shaped, with real numbers.
    ok = next(m for m in models if m["status"] == "ok")
    assert ok["train"] is not None
    assert _TRAIN_KEYS == set(ok["train"].keys())
    train_f1 = ok["train"]["f1_weighted"]
    assert train_f1 is not None and 0.0 <= train_f1 <= 1.0

    # A failed model still has the block, all values null.
    failed = by_name["NotAModel"]
    assert failed["train"] is not None
    assert all(v is None for v in failed["train"].values())


def test_binary_predictions_sampled(binary_run_response) -> None:
    preds = binary_run_response.json()["result"]["predictions"]
    assert preds["sampled"] is True
    assert preds["full_csv"] == "classification_results.csv"
    assert preds["rows_returned"] < preds["rows_total"]
    assert preds["sample_rows"]
    row = preds["sample_rows"][0]
    assert {"model", "sample_index", "actual", "predicted", "confidence",
            "correct_flag", "probabilities"} <= set(row.keys())


def test_binary_confusion_and_class_report(binary_run_response) -> None:
    result = binary_run_response.json()["result"]
    cm = result["confusion_matrix"]
    assert cm  # at least one successful model
    any_model = next(iter(cm))
    assert set(cm[any_model].keys()) == {"labels", "matrix"}
    report = result["class_report"][any_model]
    assert report and {"class", "precision", "recall", "f1", "support"} <= set(report[0].keys())


def test_binary_curves_full_test(binary_run_response) -> None:
    """curves are present per successful model with ROC/PR sub-structures."""
    curves = binary_run_response.json()["result"]["curves"]
    assert curves
    any_model = next(iter(curves))
    assert "roc" in curves[any_model] and "pr" in curves[any_model]
    roc = curves[any_model]["roc"]
    # binary → positive class entry with fpr/tpr/auc
    entry = next(iter(roc.values()))
    assert {"fpr", "tpr", "auc"} <= set(entry.keys())


def test_binary_artifacts_lists_pngs(binary_run_response) -> None:
    artifacts = binary_run_response.json()["result"]["artifacts"]
    suffixes = {a["suffix"] for a in artifacts}
    assert ".png" in suffixes
    names = {a["name"] for a in artifacts}
    assert "plot2_roc_pr_curves.png" in names
    assert all({"name", "suffix", "size_bytes"} <= set(a.keys()) for a in artifacts)


def test_binary_response_is_strict_json(binary_run_response) -> None:
    """The body round-trips through strict JSON (no NaN/Inf leaked through)."""
    text = json.dumps(binary_run_response.json(), allow_nan=False)
    assert text  # would have raised if a NaN/Inf were present


# --------------------------------------------------------------------------- #
# locked schema (multiclass)                                                  #
# --------------------------------------------------------------------------- #


def test_multiclass_run_schema(multiclass_run_response) -> None:
    assert multiclass_run_response.status_code == 200
    body = multiclass_run_response.json()
    assert body["status"] == "ok"
    result = body["result"]
    assert RESULT_KEYS == set(result.keys())
    assert result["run"]["problem_type"] == "multiclass"
    # multiclass curves → one-vs-rest: more than one ROC entry per model.
    curves = result["curves"]
    any_model = next(iter(curves))
    assert len(curves[any_model]["roc"]) >= 2


# --------------------------------------------------------------------------- #
# locked schema (multilabel — Phase 11)                                        #
# --------------------------------------------------------------------------- #


def test_multilabel_run_schema(multilabel_run_response) -> None:
    """The multilabel envelope is honest within the LOCKED contract (no contract change).

    Per-label metrics/curves/report are populated; the fields that are undefined for a
    multi-hot target (a single confusion matrix, MCC, log-loss) are empty/None — never a
    crash and never a silently-wrong number.
    """
    assert multilabel_run_response.status_code == 200
    body = multilabel_run_response.json()
    assert body["status"] == "ok"
    result = body["result"]
    assert RESULT_KEYS == set(result.keys())
    assert result["run"]["problem_type"] == "multilabel"

    # models: per-label-weighted f1/roc/pr present; mcc None (undefined for multilabel).
    ok_models = [m for m in result["models"] if m["status"] == "ok"]
    assert len(ok_models) >= 2
    assert all(m["f1_weighted"] is not None for m in ok_models)
    assert all(m["roc_auc"] is not None for m in ok_models)
    assert all(m["mcc"] is None for m in ok_models)

    # curves: one-vs-rest entry per LABEL (≥2 labels), with ROC + PR sub-structures.
    curves = result["curves"]
    any_model = next(iter(curves))
    assert len(curves[any_model]["roc"]) >= 2
    assert len(curves[any_model]["pr"]) >= 2

    # confusion_matrix is empty (a single matrix is undefined for multilabel) — the honest
    # "not applicable" state, not a fabricated matrix.
    assert result["confusion_matrix"] == {}

    # class_report: per-label rows render (precision/recall/f1/support per product).
    report = result["class_report"][any_model]
    assert report and {"class", "precision", "recall", "f1", "support"} <= set(report[0].keys())

    # predictions: a per-label probability map + label-SET strings for actual/predicted.
    row = result["predictions"]["sample_rows"][0]
    assert isinstance(row["actual"], str) and isinstance(row["predicted"], str)
    assert len(row["probabilities"]) >= 2

    # strict-JSON round-trip (no NaN/Inf leaked).
    assert json.dumps(body, allow_nan=False)


# --------------------------------------------------------------------------- #
# tuned run — result.tuning is populated (schema 1.1, additive)                #
# --------------------------------------------------------------------------- #


def test_tuned_run_exposes_best_params(api_client) -> None:
    """A tuned run surfaces ``result.tuning`` with the model + its non-empty best_params.

    Tiny Optuna budget (n_trials=3, cv_folds=2) on ONE fast model (XGBoost) keeps this cheap
    while exercising the real engine → run_profile → API path end to end.
    """
    payload = {
        "input_file": "policy_lapse.csv",
        "target": "will_lapse",
        "feature_cols": ["age", "annual_premium"],
        "problem_type": "binary",
        "class_balance": "none",
        "interaction_features": {"max_auto_pairs": 0},
        "algorithms": ["XGBoost"],
        "tuning": {
            "enabled": True,
            "models": ["XGBoost"],
            "n_trials": 3,
            "cv": True,
            "cv_folds": 2,
        },
    }
    resp = api_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == "1.3"

    tuning = body["result"]["tuning"]
    assert tuning is not None
    assert tuning["enabled"] is True
    assert "XGBoost" in tuning["tuned_models"]
    best = tuning["best_params"]["XGBoost"]
    assert best  # non-empty per-model chosen hyperparameters
    # The whole tuning block must be JSON-serializable (no NaN/Inf/numpy leaked).
    assert json.dumps(tuning, allow_nan=False)


# --------------------------------------------------------------------------- #
# user-defined structured features (request-side; response schema unchanged)   #
# --------------------------------------------------------------------------- #

# A small, fast run config reused by the user-feature request tests.
_UF_BASE = {
    "input_file": "policy_lapse.csv",
    "target": "will_lapse",
    "feature_cols": ["age", "annual_premium"],
    "problem_type": "binary",
    "class_balance": "none",
    "interaction_features": {"max_auto_pairs": 0},
    "algorithms": ["LogisticRegression"],
}


def test_run_with_user_features_creates_columns(api_client) -> None:
    """A valid ``user_features`` request runs and the created columns surface in the response.

    Two specs exercise distinct shapes: a numeric ``divide`` (two numeric columns) and a
    ``single`` date-part extraction (the datetime path; the sample data has only one datetime
    column, so a two-column ``datetime_diff`` isn't expressible here). The created columns must
    appear in ``result.run.active_features`` — proving the engine built them — and the response
    schema is UNCHANGED (request-side only, still ``1.2``).
    """
    payload = {
        **_UF_BASE,
        "user_features": [
            {"name": "premium_per_sum", "type": "numeric", "op": "divide",
             "col_a": "annual_premium", "col_b": "sum_assured"},
            {"name": "start_year", "type": "single", "op": "year",
             "col_a": "policy_start_date"},
        ],
    }
    resp = api_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # user_features is request-side only — it adds no response field of its own; the version
    # reflects the current contract default (1.3).
    assert body["schema_version"] == "1.3"
    active = body["result"]["run"]["active_features"]
    assert "premium_per_sum" in active
    assert "start_year" in active


def test_run_with_unknown_user_feature_op_is_422(api_client) -> None:
    """An op outside the type's allowlist is rejected at the API boundary (422)."""
    payload = {
        **_UF_BASE,
        "user_features": [
            {"name": "bad", "type": "numeric", "op": "exponentiate",
             "col_a": "annual_premium", "col_b": "sum_assured"},
        ],
    }
    assert api_client.post("/api/v1/run", json=payload).status_code == 422


def test_run_with_missing_col_b_is_422(api_client) -> None:
    """A two-column ``numeric`` spec missing ``col_b`` is rejected at the API boundary (422)."""
    payload = {
        **_UF_BASE,
        "user_features": [
            {"name": "bad", "type": "numeric", "op": "divide", "col_a": "annual_premium"},
        ],
    }
    assert api_client.post("/api/v1/run", json=payload).status_code == 422


def test_runconfig_no_user_features_maps_to_empty() -> None:
    """Omitting ``user_features`` forwards an empty list to the engine — unchanged behaviour."""
    from api.models import RunConfig

    cfg = RunConfig(input_file="policy_lapse.csv", target="will_lapse", feature_cols=["age"])
    assert cfg.to_engine_config()["user_features"] == []


def test_runconfig_user_feature_spec_drops_none_optionals() -> None:
    """A single-column spec forwards to the engine WITHOUT ``col_b``/``unit`` (None dropped).

    The engine reads each spec as a plain dict and treats a present ``unit=None`` as invalid,
    so ``to_engine_config`` must dump with ``exclude_none`` — the optional keys must be absent,
    not present-as-null.
    """
    from api.models import RunConfig

    cfg = RunConfig(
        input_file="policy_lapse.csv",
        target="will_lapse",
        feature_cols=["age"],
        user_features=[
            {"name": "start_year", "type": "single", "op": "year", "col_a": "policy_start_date"}
        ],
    )
    spec = cfg.to_engine_config()["user_features"][0]
    assert spec == {
        "name": "start_year",
        "type": "single",
        "op": "year",
        "col_a": "policy_start_date",
    }


# --------------------------------------------------------------------------- #
# JSON-safety unit test                                                        #
# --------------------------------------------------------------------------- #


def test_safe_jsonify_handles_nan_inf_numpy() -> None:
    """safe_jsonify maps NaN/Inf→None and numpy scalars/arrays→plain Python."""
    payload = {
        "nan": float("nan"),
        "inf": float("inf"),
        "ninf": float("-inf"),
        "np_float": np.float64(1.5),
        "np_int": np.int64(7),
        "np_nan": np.float64("nan"),
        "arr": np.array([1.0, np.nan, 3.0]),
        "nested": [{"x": np.float32(2.0)}],
    }
    out = safe_jsonify(payload)
    json.dumps(out, allow_nan=False)  # must not raise
    assert out["nan"] is None and out["inf"] is None and out["ninf"] is None
    assert out["np_float"] == 1.5 and out["np_int"] == 7
    assert out["np_nan"] is None
    assert out["arr"] == [1.0, None, 3.0]
    assert out["nested"][0]["x"] == 2.0
    assert all(not isinstance(v, float) or math.isfinite(v)
               for v in [out["np_float"], out["arr"][0]])
