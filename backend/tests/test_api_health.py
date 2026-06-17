"""Tests for ``GET /api/v1/health`` — the liveness endpoint."""

from __future__ import annotations


def test_health_ok(api_client) -> None:
    """Health returns 200 and the expected fixed body."""
    resp = api_client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "ClassifyOS API", "version": "1.0"}
