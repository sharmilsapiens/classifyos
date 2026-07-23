"""Tests for ``GET /api/v1/outputs``, ``GET /api/v1/outputs/{name}`` and the run-scoped
``GET /api/v1/outputs/{run_id}/{name}``.

These depend on a completed run (the binary fixture) having written artifacts to the temp
OUTPUT_DIR. They verify the listing shape, that a PNG and a CSV stream back with the right
content type, and that a path-traversal attempt is rejected.

The run-scoped endpoint (additive; like the other ``/outputs`` endpoints it carries no
``schema_version``) serves a Databricks run's artifacts from MLflow. Everything MLflow/Databricks is
MOCKED (``load_artifact`` is stubbed, the backend flipped with ``monkeypatch.setenv``) so CI never
contacts a live workspace or tracking store, and the LOCAL branch is asserted byte-identical to
``/outputs/{name}``.
"""

from __future__ import annotations

import pytest

from .conftest import LAPSE_FEATURES, _run_payload


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


# --------------------------------------------------------------------------- #
# Run-scoped artifacts — GET /api/v1/outputs/{run_id}/{name}                   #
#                                                                              #
# Local backend: serves from OUTPUT_DIR by name (run_id ignored), byte-        #
# identical to /outputs/{name}. Databricks backend: streams from MLflow by run #
# id — fully mocked (load_artifact stubbed) so CI never hits a live workspace. #
# --------------------------------------------------------------------------- #


def test_run_scoped_output_local_is_byte_identical(api_client, binary_run_response) -> None:
    """Local backend: /outputs/{run_id}/{name} serves the SAME OUTPUT_DIR file as /outputs/{name}."""
    flat = api_client.get("/api/v1/outputs/plot2_roc_pr_curves.png")
    scoped = api_client.get("/api/v1/outputs/any-run-id/plot2_roc_pr_curves.png")
    assert scoped.status_code == 200
    assert scoped.headers["content-type"] == "image/png"
    # run_id is ignored locally — the bytes match the flat endpoint exactly (local unchanged).
    assert scoped.content == flat.content


def test_run_scoped_output_local_missing_is_404(api_client) -> None:
    """Local backend: a name absent from OUTPUT_DIR is a 404, exactly like /outputs/{name}."""
    resp = api_client.get("/api/v1/outputs/any-run-id/does_not_exist.png")
    assert resp.status_code == 404


def test_run_scoped_output_databricks_streams_png(api_client, monkeypatch) -> None:
    """Databricks backend: the endpoint streams the bytes load_artifact returns from MLflow (mocked)."""
    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")
    monkeypatch.setattr(
        "api.routes.outputs.load_artifact",
        lambda run_id, name: (b"\x89PNG\r\n\x1a\n-mlflow-bytes", "plot2_roc_pr_curves.png"),
    )
    resp = api_client.get("/api/v1/outputs/abc123def456/plot2_roc_pr_curves.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == b"\x89PNG\r\n\x1a\n-mlflow-bytes"
    # Run artifacts are immutable → cacheable, so re-navigation is instant and the frontend prefetch
    # stays warm (demo smoothness). Local /outputs stays uncached (fixed filenames are mutable).
    assert "immutable" in resp.headers.get("cache-control", "")


def test_run_scoped_output_databricks_streams_csv(api_client, monkeypatch) -> None:
    """A CSV artifact streams back as text/csv in the databricks backend."""
    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")
    monkeypatch.setattr(
        "api.routes.outputs.load_artifact",
        lambda run_id, name: (b"a,b\n1,2\n", "classification_results.csv"),
    )
    resp = api_client.get("/api/v1/outputs/run1/classification_results.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert b"," in resp.content


def test_run_scoped_output_databricks_missing_is_404(api_client, monkeypatch) -> None:
    """A run/artifact MLflow can't find is a clean 404, never a 500."""
    from api.mlflow_read import RunNotFound

    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")

    def _raise(run_id, name):
        raise RunNotFound(f"{run_id}/{name}")

    monkeypatch.setattr("api.routes.outputs.load_artifact", _raise)
    resp = api_client.get("/api/v1/outputs/run1/plot2_roc_pr_curves.png")
    assert resp.status_code == 404


def test_run_scoped_output_databricks_unavailable_is_503(api_client, monkeypatch) -> None:
    """An unreachable tracking/artifact store is a 503 (mirrors the read-path discipline), not a 500."""
    from api.mlflow_read import MlflowUnavailable

    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")

    def _raise(run_id, name):
        raise MlflowUnavailable("store down")

    monkeypatch.setattr("api.routes.outputs.load_artifact", _raise)
    resp = api_client.get("/api/v1/outputs/run1/plot2_roc_pr_curves.png")
    assert resp.status_code == 503


def test_run_scoped_output_traversal_rejected(api_client) -> None:
    """A path-traversal name is rejected (400) before any store/FS access, in either backend."""
    resp = api_client.get("/api/v1/outputs/run1/..%2f..%2fsecret.txt")
    assert resp.status_code in (400, 404)
    assert resp.status_code != 200


def test_load_artifact_targets_databricks_store(monkeypatch, tmp_path) -> None:
    """``load_artifact`` downloads ``classifyos/{name}`` from the DATABRICKS store PER CALL (no
    process-global ``set_tracking_uri`` — thread-safe). The core of the artifact-display fix (§6.2),
    with ``mlflow.artifacts.download_artifacts`` fully mocked."""
    import mlflow.artifacts

    from api import mlflow_read

    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")
    captured: dict = {}

    def _fake_download(run_id, artifact_path, dst_path, tracking_uri):
        captured.update(run_id=run_id, artifact_path=artifact_path, tracking_uri=tracking_uri)
        target = tmp_path / "plot2_roc_pr_curves.png"
        target.write_bytes(b"PNGBYTES")
        return str(target)

    monkeypatch.setattr(mlflow.artifacts, "download_artifacts", _fake_download)
    data, filename = mlflow_read.load_artifact("abc123", "plot2_roc_pr_curves.png")

    assert data == b"PNGBYTES"
    assert filename == "plot2_roc_pr_curves.png"
    assert captured["run_id"] == "abc123"
    assert captured["artifact_path"] == "classifyos/plot2_roc_pr_curves.png"
    assert captured["tracking_uri"] == "databricks"  # managed store, per-call (not the env default)


def test_load_artifact_missing_is_run_not_found(monkeypatch) -> None:
    """A download failure for an absent artifact surfaces as ``RunNotFound`` (→ 404), not 503/500."""
    import mlflow.artifacts

    from api import mlflow_read

    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")

    def _boom(run_id, artifact_path, dst_path, tracking_uri):
        raise FileNotFoundError(artifact_path)

    monkeypatch.setattr(mlflow.artifacts, "download_artifacts", _boom)
    with pytest.raises(mlflow_read.RunNotFound):
        mlflow_read.load_artifact("r1", "plot2_roc_pr_curves.png")


@pytest.fixture
def mlflow_file_store(tmp_path, monkeypatch):
    """Point MLflow at a per-test temp ``file:`` store (same trick as the read-path tests)."""
    uri = "file:" + (tmp_path / "mlruns").as_posix()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.delenv("MLFLOW_ALLOW_FILE_STORE", raising=False)  # the engine sets this itself
    return uri


def test_load_artifact_reads_a_real_logged_artifact(api_client, mlflow_file_store) -> None:
    """End-to-end: a REAL mlflow-logged /run writes its artifacts under ``classifyos/``, and
    ``load_artifact`` downloads them back byte-for-byte from a REAL MLflow store.

    Uses a temp ``file:`` store as a faithful stand-in for Databricks-managed MLflow: the download
    API (``mlflow.artifacts.download_artifacts`` on the ``classifyos/{name}`` path) is identical —
    only the ``tracking_uri``/auth differs, which is unit-tested above (mocked) and confirmed against
    the live workspace in ``docs/databricks_wisdom.md`` §4. This is what proves :data:`ARTIFACT_SUBDIR`
    matches the subdir the engine's ``log_run`` actually writes (so a Databricks run's PNGs/CSVs
    resolve). Runs in the LOCAL backend, so ``_tracking_uri()`` is ``None`` → the env ``file:`` store.
    """
    from api import mlflow_read

    payload = _run_payload(
        "policy_lapse.csv", "will_lapse", LAPSE_FEATURES,
        problem_type="binary", algorithms=["LogisticRegression"],
        mlflow={"enabled": True, "experiment": "classifyos_outputs_test"},
    )
    resp = api_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["result"]["mlflow"]["run_id"]

    # A PNG round-trips as real image bytes (validates classifyos/{name} download from a real store).
    png, png_name = mlflow_read.load_artifact(run_id, "plot2_roc_pr_curves.png")
    assert png_name == "plot2_roc_pr_curves.png"
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic — genuinely the logged plot, not a stub
    assert len(png) > 1000

    # A CSV round-trips too.
    csv, csv_name = mlflow_read.load_artifact(run_id, "metrics_comparison.csv")
    assert csv_name == "metrics_comparison.csv"
    assert b"," in csv

    # An artifact the run never logged is a clean RunNotFound (→ 404 at the route), not a 500.
    with pytest.raises(mlflow_read.RunNotFound):
        mlflow_read.load_artifact(run_id, "not_a_real_artifact.png")
