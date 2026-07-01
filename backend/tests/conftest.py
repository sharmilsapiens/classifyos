"""Shared pytest fixtures and environment bootstrap for the ClassifyOS test suite.

Tests *read* the real sample CSVs under ``DATA_DIR`` but never *write* to the real
``OUTPUT_DIR``: the suite redirects ``OUTPUT_DIR`` to a per-session pytest temp
directory so it cannot pollute the configured output folder with test artifacts
(see the PROJECT_STATE decision, 2026-06-12). We load ``backend/.env`` the same way
the app does and normalise ``DATA_DIR`` to an absolute path so reads are independent
of the directory pytest is launched from.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from dotenv import load_dotenv

from classifyos.config import build_config
from classifyos.io.loader import data_loader
from classifyos.io.storage import LocalFolderStorage, StorageAdapter
from classifyos.preprocessing.balance import handle_class_imbalance
from classifyos.preprocessing.features import FeatureBuilder
from classifyos.preprocessing.interactions import InteractionFeatureBuilder
from classifyos.preprocessing.preprocess import Preprocessor
from classifyos.split import train_test_split_cls

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Load backend/.env, then resolve a relative DATA_DIR against the backend root so the
# StorageAdapter finds the sample data regardless of cwd. OUTPUT_DIR is deliberately
# NOT resolved here — it is overridden per-session to a temp dir by the fixture below.
load_dotenv(BACKEND_DIR / ".env")
_data_value = os.environ.get("DATA_DIR", "data/samples")
_data_path = Path(_data_value)
if not _data_path.is_absolute():
    _data_path = (BACKEND_DIR / _data_path).resolve()
os.environ["DATA_DIR"] = str(_data_path)


@pytest.fixture(scope="session")
def output_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A throwaway, per-session OUTPUT_DIR.

    Points ``OUTPUT_DIR`` at a pytest temp directory and exports it via the
    environment *before* any ``StorageAdapter`` is constructed, so tests never write
    artifacts into the real output folder. Returned as a ``Path`` for assertions.
    """
    path = tmp_path_factory.mktemp("classifyos_output")
    os.environ["OUTPUT_DIR"] = str(path)
    return path


@pytest.fixture(scope="session")
def storage(output_dir: Path) -> StorageAdapter:
    """A storage adapter: reads from the real DATA_DIR, writes to the temp OUTPUT_DIR.

    Depends on ``output_dir`` so the temp ``OUTPUT_DIR`` is exported before
    ``LocalFolderStorage`` reads it at construction time.
    """
    return LocalFolderStorage()


@pytest.fixture(scope="session")
def lapse_csv() -> str:
    """Logical key for the policy-lapse sample (binary)."""
    return "policy_lapse.csv"


@pytest.fixture(scope="session")
def fraud_csv() -> str:
    """Logical key for the fraud sample (binary, ~99:1 imbalance)."""
    return "fraud_claims.csv"


@pytest.fixture(scope="session")
def risk_csv() -> str:
    """Logical key for the risk-tier sample (multiclass)."""
    return "risk_tier.csv"


@pytest.fixture(scope="session")
def product_csv() -> str:
    """Logical key for the product-recommendation sample (multilabel, delimited target)."""
    return "product_reco.csv"


# --- Phase 6 shared fixtures: fully-engineered train/test matrices ----------------
#
# The model/metrics/classify tests all need real train/test matrices produced by the
# full Phase 1–5 pipeline (load → split → preprocess → features → interactions →
# balance). Building them is relatively expensive, so they are session-scoped and the
# matrices are subsampled to keep the SVM's internal probability-calibration CV (and the
# overall suite) fast while still exercising real, engineered insurance data.

LAPSE_FEATURES = [
    "age",
    "occupation",
    "region",
    "policy_type",
    "channel",
    "payment_frequency",
    "policy_tenure_years",
    "annual_premium",
    "sum_assured",
    "num_late_payments",
    "claims_count",
    "has_agent",
]

RISK_FEATURES = [
    "age",
    "bmi",
    "is_smoker",
    "annual_income",
    "credit_score",
    "prior_violations",
    "occupation_class",
    "vehicle_age",
    "region",
]

FRAUD_FEATURES = [
    "claim_amount",
    "policy_age_months",
    "report_delay_days",
    "num_prior_claims",
    "incident_type",
    "has_police_report",
    "has_witness",
    "claimant_age",
    "region",
]

# Product Recommendation (multilabel — "|"-delimited target column). Phase 11.
PRODUCT_FEATURES = [
    "age",
    "annual_income",
    "family_size",
    "num_dependents",
    "owns_home",
    "owns_vehicle",
    "risk_appetite",
    "existing_life_policy",
    "region",
]


def build_matrices(
    storage: StorageAdapter,
    input_file: str,
    target: str,
    features: list[str],
    problem_type: str = "binary",
    class_balance: str = "none",
    sample_n: int | None = 800,
) -> SimpleNamespace:
    """Run the full Phase 1–5 pipeline and return train/test matrices + metadata.

    Auto-interaction discovery is disabled (``max_auto_pairs=0``) for speed. The TRAIN
    matrices are balanced per ``class_balance`` (so ``X_train`` may be SMOTE-resampled).
    ``sample_n`` caps the TRAIN rows (after balancing) and TEST rows to keep model
    fitting fast; pass ``None`` to keep every row.

    Returns a namespace with ``X_train, y_train, X_test, y_test, class_weight,
    classes, config``.
    """
    cfg = build_config(
        input_file,
        target,
        features,
        problem_type=problem_type,
        class_balance=class_balance,
        interaction_features={
            "enabled": True,
            "interaction_pairs": {},
            "default_interactions": ["multiply"],
            "drop_original_if_interacted": False,
            "max_auto_pairs": 0,
            "fill_method": "zero",
        },
    )
    df = data_loader(cfg, storage)
    train, test = train_test_split_cls(df, cfg)

    pp = Preprocessor(cfg)
    train_pp, test_pp = pp.fit_transform(train), pp.transform(test)
    fb = FeatureBuilder(cfg)
    train_f, test_f = fb.fit_transform(train_pp, target), fb.transform(test_pp)
    ib = InteractionFeatureBuilder(cfg)
    train_i, test_i = ib.fit_transform(train_f, target), ib.transform(test_f)

    X_train_full, y_train_full = train_i.drop(columns=[target]), train_i[target]
    X_test, y_test = test_i.drop(columns=[target]), test_i[target]

    X_bal, y_bal, class_weight = handle_class_imbalance(X_train_full, y_train_full, cfg)

    if sample_n is not None:
        X_bal, y_bal = _sample(X_bal, y_bal, sample_n)
        X_test, y_test = _sample(X_test, y_test, sample_n)

    return SimpleNamespace(
        X_train=X_bal,
        y_train=y_bal,
        X_test=X_test,
        y_test=y_test,
        class_weight=class_weight,
        classes=sorted(y_bal.unique()),
        config=cfg,
    )


def _sample(X: Any, y: Any, n: int) -> tuple[Any, Any]:
    """Stratified-ish subsample to ``n`` rows (keeps all rows if fewer than ``n``)."""
    if len(X) <= n:
        return X, y
    # Group-aware sample so every class survives even when one is rare (fraud).
    idx = (
        y.groupby(y, group_keys=False)
        .apply(lambda s: s.sample(max(1, int(round(len(s) * n / len(y)))), random_state=42))
        .index
    )
    return X.loc[idx], y.loc[idx]


@pytest.fixture(scope="session")
def binary_matrices(storage: StorageAdapter) -> SimpleNamespace:
    """Engineered policy-lapse matrices (binary), unbalanced train."""
    return build_matrices(storage, "policy_lapse.csv", "will_lapse", LAPSE_FEATURES)


@pytest.fixture(scope="session")
def multiclass_matrices(storage: StorageAdapter) -> SimpleNamespace:
    """Engineered risk-tier matrices (3-class multiclass), unbalanced train."""
    return build_matrices(
        storage, "risk_tier.csv", "risk_tier", RISK_FEATURES, problem_type="multiclass"
    )


@pytest.fixture(scope="session")
def fraud_smote_matrices(storage: StorageAdapter) -> SimpleNamespace:
    """Engineered fraud matrices (binary, ~99:1) with SMOTE applied to the TRAIN split."""
    return build_matrices(
        storage,
        "fraud_claims.csv",
        "is_fraud",
        FRAUD_FEATURES,
        problem_type="binary",
        class_balance="smote",
    )


# --- Phase 8 API fixtures: a TestClient over the real app + shared end-to-end runs --------
#
# The API tests drive the REAL engine over HTTP (no engine mocks), reusing the same sample
# CSVs and the temp-OUTPUT_DIR isolation as the engine tests. A full /run is expensive, so
# the binary + multiclass runs are executed ONCE at session scope and shared.


@pytest.fixture(scope="session")
def api_client(output_dir: Path):
    """A FastAPI ``TestClient`` whose storage writes to the temp OUTPUT_DIR.

    Depends on ``output_dir`` so the temp ``OUTPUT_DIR`` is exported first, then resets the
    lazily-cached storage singleton so the app rebuilds its adapter against the temp folder
    (never the real output dir).
    """
    from fastapi.testclient import TestClient

    import api.deps as deps

    deps._storage = None  # force the adapter to be rebuilt with the temp OUTPUT_DIR
    from api.main import app

    return TestClient(app)


def _run_payload(input_file: str, target: str, features: list[str], **overrides: Any) -> dict:
    """Build a /run request body; interaction auto-discovery off for test speed."""
    body = {
        "input_file": input_file,
        "target": target,
        "feature_cols": features,
        "class_balance": "none",
        "interaction_features": {"max_auto_pairs": 0},
    }
    body.update(overrides)
    return body


@pytest.fixture(scope="session")
def binary_run_response(api_client) -> Any:
    """Run the binary policy-lapse pipeline once over HTTP (includes a deliberately-bad algo).

    ``NotAModel`` is an unknown algorithm: the engine records it as a ``status="failed"`` row
    rather than aborting, which lets the schema tests assert the failed-row contract.
    """
    payload = _run_payload(
        "policy_lapse.csv",
        "will_lapse",
        LAPSE_FEATURES,
        problem_type="binary",
        algorithms=["LogisticRegression", "RandomForest", "NotAModel"],
    )
    return api_client.post("/api/v1/run", json=payload)


@pytest.fixture(scope="session")
def explain_run_response(api_client) -> Any:
    """Run the binary pipeline once with explainability ON (schema 1.6).

    RandomForest exercises the ``shap.TreeExplainer`` path and LogisticRegression the
    model-agnostic ``shap.KernelExplainer`` path, so both explainer families are covered.
    ``sample_rows`` is kept small so the (slower) kernel path stays cheap in CI.
    """
    payload = _run_payload(
        "policy_lapse.csv",
        "will_lapse",
        LAPSE_FEATURES,
        problem_type="binary",
        algorithms=["RandomForest", "LogisticRegression"],
        explainability={"enabled": True, "sample_rows": 3, "background_size": 40},
    )
    return api_client.post("/api/v1/run", json=payload)


@pytest.fixture(scope="session")
def multiclass_run_response(api_client) -> Any:
    """Run the multiclass risk-tier pipeline once over HTTP."""
    payload = _run_payload(
        "risk_tier.csv",
        "risk_tier",
        RISK_FEATURES,
        problem_type="multiclass",
        algorithms=["LogisticRegression", "RandomForest"],
    )
    return api_client.post("/api/v1/run", json=payload)


@pytest.fixture(scope="session")
def multilabel_run_response(api_client) -> Any:
    """Run the multilabel product-recommendation pipeline once over HTTP (Phase 11).

    ``class_balance="smote"`` exercises the documented multilabel fallback to ``class_weight``
    (resampling is not defined for a multi-hot target) without crashing.
    """
    payload = _run_payload(
        "product_reco.csv",
        "recommended_products",
        PRODUCT_FEATURES,
        problem_type="multilabel",
        class_balance="smote",
        algorithms=["LogisticRegression", "RandomForest"],
    )
    return api_client.post("/api/v1/run", json=payload)
