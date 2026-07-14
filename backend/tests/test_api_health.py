"""Tests for ``GET /api/v1/health`` — the liveness endpoint."""

from __future__ import annotations


def test_health_ok(api_client) -> None:
    """Health returns 200 and the expected fixed body."""
    resp = api_client.get("/api/v1/health")
    assert resp.status_code == 200
    # execution_backend (§6.6 Step 6) is additive; conftest pins the LOCAL backend for the suite.
    assert resp.json() == {
        "status": "ok",
        "service": "ClassifyOS API",
        "version": "1.0",
        "execution_backend": "local",
    }
