"""Tests for ``GET /api/v1/outputs`` and ``GET /api/v1/outputs/{name}``.

These depend on a completed run (the binary fixture) having written artifacts to the temp
OUTPUT_DIR. They verify the listing shape, that a PNG and a CSV stream back with the right
content type, and that a path-traversal attempt is rejected.
"""

from __future__ import annotations


def test_outputs_lists_artifacts(api_client, binary_run_response) -> None:
    """After a run, /outputs lists files with name/suffix/size."""
    resp = api_client.get("/api/v1/outputs")
    assert resp.status_code == 200
    entries = resp.json()
    assert isinstance(entries, list) and entries
    names = {e["name"] for e in entries}
    assert "metrics_comparison.csv" in names
    assert "plot2_roc_pr_curves.png" in names
    for e in entries:
        assert {"name", "suffix", "size_bytes"} == set(e.keys())
        assert e["size_bytes"] > 0


def test_outputs_streams_png(api_client, binary_run_response) -> None:
    """A PNG artifact streams back with image/png."""
    resp = api_client.get("/api/v1/outputs/plot2_roc_pr_curves.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert len(resp.content) > 1000


def test_outputs_streams_csv(api_client, binary_run_response) -> None:
    """A CSV artifact streams back with text/csv."""
    resp = api_client.get("/api/v1/outputs/metrics_comparison.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert b"," in resp.content


def test_outputs_missing_is_404(api_client) -> None:
    resp = api_client.get("/api/v1/outputs/does_not_exist.csv")
    assert resp.status_code == 404


def test_outputs_traversal_rejected(api_client) -> None:
    """A path-traversal attempt is rejected by the storage guard (400), not served."""
    # %2e%2e%2f == ../ — encoded so it reaches the route as a single path segment.
    resp = api_client.get("/api/v1/outputs/..%2f..%2fsecret.txt")
    assert resp.status_code in (400, 404)
    assert resp.status_code != 200
