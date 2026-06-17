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
    assert body["schema_version"] == "1.0"
    assert RESULT_KEYS == set(body["result"].keys())


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
