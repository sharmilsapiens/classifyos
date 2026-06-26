"""Tests for ``POST /api/v1/upload`` — multipart upload + inspect.

Each sample CSV is uploaded as if from a browser; the response must carry the locked
``inspect_file`` keys plus a usable ``server_path`` (the storage key /run reads back).
"""

from __future__ import annotations

from pathlib import Path

import pytest

INSPECT_KEYS = {
    "columns",
    "dtypes",
    "numeric_cols",
    "categorical_cols",
    "binary_cols",
    "datetime_cols",
    "n_rows",
    "n_missing",
    "sample",
}


def _upload(api_client, name: str, target: str | None = None):
    """Upload a sample CSV from the real DATA_DIR via the multipart endpoint."""
    import os

    src = Path(os.environ["DATA_DIR"]) / name
    with open(src, "rb") as fh:
        files = {"file": (name, fh, "text/csv")}
        data = {"target": target} if target is not None else None
        return api_client.post("/api/v1/upload", files=files, data=data)


@pytest.mark.parametrize(
    "name,target",
    [
        ("policy_lapse.csv", "will_lapse"),
        ("fraud_claims.csv", "is_fraud"),
        ("risk_tier.csv", "risk_tier"),
    ],
)
def test_upload_returns_inspect_keys_and_server_path(api_client, name, target) -> None:
    """Uploading a sample yields the inspect contract keys + a usable server_path."""
    resp = _upload(api_client, name, target=target)
    assert resp.status_code == 200
    body = resp.json()
    assert INSPECT_KEYS.issubset(body.keys())
    # target given → class preview present.
    assert "class_distribution" in body
    assert "suggested_problem_type" in body
    # server_path is the key /run uses; the upload landed under uploads/.
    assert body["server_path"] == f"uploads/{name}"
    # Data-Profile blocks (additive) are attached for the exploration view.
    assert "column_profiles" in body
    assert len(body["column_profiles"]) == len(body["columns"])
    assert "correlation" in body  # numeric matrix or null
    assert all("dtype_group" in c for c in body["column_profiles"])


def test_upload_server_path_is_runnable(api_client) -> None:
    """The server_path returned by /upload is readable by a subsequent /run."""
    up = _upload(api_client, "policy_lapse.csv", target="will_lapse")
    server_path = up.json()["server_path"]
    payload = {
        "input_file": server_path,
        "target": "will_lapse",
        "feature_cols": ["age", "annual_premium", "num_late_payments", "has_agent"],
        "problem_type": "binary",
        "algorithms": ["LogisticRegression"],
        "class_balance": "none",
        "interaction_features": {"max_auto_pairs": 0},
    }
    resp = api_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_upload_rejects_unsupported_type(api_client) -> None:
    """A non-CSV/Excel/Parquet upload is a 422."""
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    resp = api_client.post("/api/v1/upload", files=files)
    assert resp.status_code == 422
