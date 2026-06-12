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

import pytest
from dotenv import load_dotenv

from classifyos.io.storage import LocalFolderStorage, StorageAdapter

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
