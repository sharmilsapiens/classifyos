"""Tests for ``POST /api/v1/explain`` — the v1.0 structured stub (option B).

v1.0 has no model persistence, so /explain never trains; it returns a structured
"unavailable" payload with the final field shape so v2.0 can fill it in without a contract
change. These tests pin that contract.
"""

from __future__ import annotations

import pytest

_BODY = {
    "input_file": "policy_lapse.csv",
    "target": "will_lapse",
    "feature_cols": ["age", "annual_premium"],
    "model": "RandomForest",
    "sample_index": 3,
}


def test_explain_returns_structured_stub(api_client) -> None:
    resp = api_client.post("/api/v1/explain", json=_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["schema_version"] == "1.0"
    assert body["model"] == "RandomForest"
    assert body["sample_index"] == 3
    # The final-shape fields exist but are null in this stub.
    for key in ("method", "shap_values", "base_value"):
        assert key in body and body[key] is None
    # Per-row SHAP now ships via /run (schema 1.6); this endpoint points there.
    assert body["reason"] == "use_run_explanations"
    assert "result.explanations" in body["message"]


@pytest.mark.parametrize("model", ["XGBoost", "LightGBM", "SVM", "NaiveBayes"])
def test_explain_stub_for_all_model_kinds(api_client, model) -> None:
    """The stub is returned uniformly regardless of model (no tree-vs-other branch in v1.0)."""
    resp = api_client.post("/api/v1/explain", json={**_BODY, "model": model})
    assert resp.status_code == 200
    assert resp.json()["status"] == "unavailable"
