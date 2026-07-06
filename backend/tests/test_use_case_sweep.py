"""Phase 11 — the 7-use-case integration sweep (engine + API layer).

Drives ALL SEVEN insurance use cases end-to-end through the real ``POST /api/v1/run``
endpoint (the same engine the browser hits) and asserts each produces a contract-valid
envelope and the full 11-artifact set. This is the reliable, CI-friendly half of the
Phase-11 sweep; the Playwright spec (``frontend/e2e/happy-path.spec.ts``, parametrized over
the SAME seven use cases) adds the browser-render half.

One fast model (LogisticRegression) per case keeps the sweep quick while still exercising
every problem type — binary ×3, multiclass ×3, multilabel ×1 — and producing every artifact.
"""

from __future__ import annotations

import pytest

from .conftest import (
    LAPSE_FEATURES,
    PRODUCT_FEATURES,
    RISK_FEATURES,
    _run_payload,
)

# The logical output artifacts every successful run must produce.
# [TEMP — interaction features unwired] plot6_interaction_summary.png is not written
# while interactions are force-disabled; restore it to the set when re-enabling (→ 12).
EXPECTED_ARTIFACTS = {
    "classification_results.csv",
    "metrics_comparison.csv",
    "class_report.csv",
    "feature_impact_summary.csv",
    "feature_importance_summary.csv",  # native per-model importance, post-training (schema 1.3)
    "permutation_importance_summary.csv",  # model-agnostic permutation importance (schema 1.4)
    "run_profile.json",
    "plot1_confusion_matrix.png",
    "plot2_roc_pr_curves.png",
    "plot3_feature_importance.png",
    "plot4_feature_impact.png",
    "plot5_calibration_curve.png",
    # "plot6_interaction_summary.png",
}

CLAIM_LIKELIHOOD_FEATURES = [
    "age", "gender", "region", "vehicle_type", "vehicle_age", "annual_mileage",
    "prior_claims", "policy_tenure_years", "coverage_level", "credit_score", "has_telematics",
]
FRAUD_FEATURES = [
    "claim_amount", "policy_age_months", "report_delay_days", "num_prior_claims",
    "incident_type", "has_police_report", "has_witness", "claimant_age", "region",
]
SEGMENT_FEATURES = [
    "age", "annual_income", "total_premium", "num_policies", "tenure_years",
    "region", "digital_engagement", "claims_ratio", "occupation",
]
SEVERITY_FEATURES = [
    "claim_amount", "incident_type", "region", "policy_age_months", "claimant_age",
    "injuries", "vehicle_damage_score", "num_parties",
]

# (id, file, target, features, problem_type, n_classes) — n_classes is the label count.
USE_CASES = [
    ("policy_lapse", "policy_lapse.csv", "will_lapse", LAPSE_FEATURES, "binary", 2),
    ("claim_likelihood", "claim_likelihood.csv", "will_claim", CLAIM_LIKELIHOOD_FEATURES, "binary", 2),
    ("fraud", "fraud_claims.csv", "is_fraud", FRAUD_FEATURES, "binary", 2),
    ("risk_tier", "risk_tier.csv", "risk_tier", RISK_FEATURES, "multiclass", 3),
    ("customer_segment", "customer_segment.csv", "segment", SEGMENT_FEATURES, "multiclass", 4),
    ("claim_severity", "claim_severity.csv", "severity", SEVERITY_FEATURES, "multiclass", 3),
    ("product_reco", "product_reco.csv", "recommended_products", PRODUCT_FEATURES, "multilabel", 6),
]


@pytest.fixture(scope="module")
def sweep_responses(api_client) -> dict:
    """Run each of the seven use cases once through the real API (LogisticRegression)."""
    out: dict = {}
    for uid, file, target, features, problem_type, _n in USE_CASES:
        payload = _run_payload(
            file,
            target,
            features,
            problem_type=problem_type,
            class_balance="class_weight",  # multilabel falls back to this; harmless for others
            algorithms=["LogisticRegression"],
        )
        out[uid] = api_client.post("/api/v1/run", json=payload)
    return out


@pytest.mark.parametrize(
    "uid,problem_type,n_classes",
    [(u[0], u[4], u[5]) for u in USE_CASES],
    ids=[u[0] for u in USE_CASES],
)
def test_use_case_runs_and_renders(sweep_responses, uid, problem_type, n_classes) -> None:
    """Each use case returns a contract-valid envelope with the right shape per problem type."""
    resp = sweep_responses[uid]
    assert resp.status_code == 200, f"{uid}: HTTP {resp.status_code}"
    body = resp.json()
    assert body["status"] == "ok", f"{uid}: {body.get('error')}"
    assert body["schema_version"] == "1.8"

    result = body["result"]
    assert result["run"]["problem_type"] == problem_type

    # At least one model trained, with real metrics.
    ok_models = [m for m in result["models"] if m["status"] == "ok"]
    assert ok_models, f"{uid}: no successful model"
    assert ok_models[0]["f1_weighted"] is not None

    # Curves: per-class/label one-vs-rest entries (binary → 1 positive class).
    curves = result["curves"]
    any_model = next(iter(curves))
    expected_curves = 1 if problem_type == "binary" else n_classes
    assert len(curves[any_model]["roc"]) == expected_curves, (
        f"{uid}: expected {expected_curves} ROC curves, got {len(curves[any_model]['roc'])}"
    )

    # Confusion matrix: present (n×n) for single-label; intentionally empty for multilabel.
    cm = result["confusion_matrix"]
    if problem_type == "multilabel":
        assert cm == {}, f"{uid}: multilabel should have no single confusion matrix"
    else:
        assert cm, f"{uid}: missing confusion matrix"
        assert len(cm[any_model]["matrix"]) == n_classes


def test_sweep_produces_all_eleven_artifacts(sweep_responses) -> None:
    """Every use case writes the full 11-artifact set (the dashboard relies on each key)."""
    for uid, _resp in sweep_responses.items():
        artifacts = {a["name"] for a in sweep_responses[uid].json()["result"]["artifacts"]}
        missing = EXPECTED_ARTIFACTS - artifacts
        assert not missing, f"{uid}: missing artifacts {missing}"
