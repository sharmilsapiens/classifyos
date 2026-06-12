"""Shared pytest fixtures and environment bootstrap for the ClassifyOS test suite.

Tests run against the real sample CSVs under ``DATA_DIR``. We load ``backend/.env``
the same way the app does and normalise the data/output roots to absolute paths so
the suite is independent of the directory pytest is launched from.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from classifyos.io.storage import LocalFolderStorage, StorageAdapter

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Load backend/.env, then resolve relative DATA_DIR/OUTPUT_DIR against the backend
# root so the StorageAdapter points at the sample data regardless of cwd.
load_dotenv(BACKEND_DIR / ".env")
for var, default in (("DATA_DIR", "data/samples"), ("OUTPUT_DIR", "classification_output")):
    value = os.environ.get(var, default)
    path = Path(value)
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    os.environ[var] = str(path)


@pytest.fixture(scope="session")
def storage() -> StorageAdapter:
    """A storage adapter rooted at the configured DATA_DIR / OUTPUT_DIR."""
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
