"""Output-artifact endpoints — how the frontend discovers and fetches run outputs.

* ``GET /api/v1/outputs`` — list the artifacts a run produced (name, suffix, size).
* ``GET /api/v1/outputs/{name}`` — stream one artifact (a CSV or a PNG) from the FastAPI's local
  ``OUTPUT_DIR`` back to the browser. This is where LOCAL runs write; unchanged.
* ``GET /api/v1/outputs/{run_id}/{name}`` — stream one **run-scoped** artifact. In the **databricks**
  backend a run's artifact files live in its managed-MLflow run (not the FastAPI's ``OUTPUT_DIR``),
  so this downloads them from MLflow by run id — the fix that makes a Databricks run's PNGs/CSVs
  display for both a fresh run and one reloaded from the Runs tab (``docs/databricks_wisdom.md``
  §6.2). In the **local** backend it resolves ``name`` against ``OUTPUT_DIR`` exactly like
  ``/outputs/{name}`` (``run_id`` unused), so local behaviour is byte-identical.

PNGs are deliberately NOT inlined into the ``/run`` JSON (that would bloat the response and
couple chart data to image bytes); the dashboard fetches each image here, on demand, by name.
Local path resolution goes through the :class:`StorageAdapter`, whose ``path_for`` rejects
path-traversal escapes (``../etc/passwd``) — we rely on that and surface a clean 400.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from classifyos.io.storage import StorageAdapter

from ..artifacts import collect_artifacts
from ..databricks import execution_backend
from ..deps import get_storage
from ..mlflow_read import MlflowUnavailable, RunNotFound, load_artifact

router = APIRouter(tags=["outputs"])

# Map a file suffix to the Content-Type the browser should receive.
_MEDIA_TYPES = {
    ".csv": "text/csv",
    ".png": "image/png",
    ".json": "application/json",
}


@router.get("/outputs")
def list_outputs(storage: StorageAdapter = Depends(get_storage)) -> list[dict[str, object]]:
    """List the run artifacts currently present in ``OUTPUT_DIR``.

    Returns one ``{name, suffix, size_bytes}`` entry per artifact that exists, so the
    frontend can show exactly what is available to download.
    """
    return collect_artifacts(storage)


def _serve_local_output(name: str, storage: StorageAdapter) -> FileResponse:
    """Resolve ``name`` against the OUTPUT root (traversal-guarded) and stream it.

    The filename is resolved through the storage adapter, which rejects any path-traversal attempt
    (``..`` escaping the root) by raising — we translate that into HTTP 400. A resolved-but-missing
    file is a 404. Shared by ``/outputs/{name}`` and the local branch of ``/outputs/{run_id}/{name}``.
    """
    try:
        # path_for runs the adapter's traversal guard; an escape raises ValueError.
        resolved = Path(storage.path_for(name, output=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid output name: {exc}") from exc

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"output not found: {name!r}")

    media_type = _MEDIA_TYPES.get(resolved.suffix, "application/octet-stream")
    return FileResponse(path=str(resolved), media_type=media_type, filename=resolved.name)


@router.get("/outputs/{name}")
def get_output(
    name: str,
    storage: StorageAdapter = Depends(get_storage),
) -> FileResponse:
    """Stream a single output file (CSV or PNG) from ``OUTPUT_DIR`` back to the caller.

    This is where LOCAL runs write their artifacts; a resolved-but-missing file is a 404 and a
    path-traversal attempt is a 400 (see :func:`_serve_local_output`). A Databricks run's artifacts
    are NOT here — those are fetched run-scoped from MLflow via ``/outputs/{run_id}/{name}``.
    """
    return _serve_local_output(name, storage)


@router.get("/outputs/{run_id}/{name}")
def get_run_output(
    run_id: str,
    name: str,
    storage: StorageAdapter = Depends(get_storage),
) -> Response:
    """Stream ONE run-scoped artifact (a PNG/CSV) for a specific run.

    **Databricks backend:** a Databricks run's artifact files live in its managed-MLflow run (under
    ``classifyos/``) — NOT in the FastAPI's local ``OUTPUT_DIR`` — so this downloads
    ``classifyos/{name}`` from MLflow run ``run_id`` (service token, ``tracking_uri="databricks"``,
    per call) and streams it. This is the fix that makes a Databricks run's plots/CSVs display, for
    both a fresh run and one reloaded from the Runs tab. [RISK] an ``<img>``/``<a>`` request cannot
    carry the user PAT, so isolation is the unguessable 32-hex MLflow run id + the service token
    (app-level), not a per-user ACL (``docs/databricks_wisdom.md`` §6.2). A missing run/artifact is a
    404; an unreachable store is a 503 — never a 500.

    **Local backend:** the frontend never builds a run-scoped URL for a local run (its artifacts are
    served by ``/outputs/{name}`` from ``OUTPUT_DIR``, unchanged). For robustness this still resolves
    ``name`` against ``OUTPUT_DIR`` — byte-identical to ``/outputs/{name}`` — so the endpoint is
    harmless if ever hit; ``run_id`` is not used to locate a local file.
    """
    # Artifact names are bare filenames (see classifyos.envelope.artifacts.ARTIFACT_KEYS); reject any
    # path parts / traversal before using ``name`` as an MLflow artifact path or a local filename.
    if name != Path(name).name or ".." in name:
        raise HTTPException(status_code=400, detail=f"invalid output name: {name!r}")

    if execution_backend() == "databricks":
        try:
            data, filename = load_artifact(run_id, name)
        except RunNotFound:
            raise HTTPException(
                status_code=404, detail=f"artifact not found: {name!r} in run {run_id!r}"
            ) from None
        except MlflowUnavailable as exc:
            return JSONResponse(
                status_code=503,
                content={"detail": f"MLflow artifact store unavailable: {exc}"},
            )
        media_type = _MEDIA_TYPES.get(Path(filename).suffix, "application/octet-stream")
        return Response(
            content=data,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                # A run's MLflow artifacts are IMMUTABLE (write-once per run_id + name), so let the
                # browser cache them hard: re-opening a result tab is then instant (no re-download
                # from MLflow), and the frontend's on-load prefetch stays warm. `private` keeps it
                # out of any shared proxy cache (the run id is the only access guard — §6.2).
                "Cache-Control": "private, max-age=31536000, immutable",
            },
        )

    # Local backend: serve from OUTPUT_DIR by name (run_id ignored), byte-identical to /outputs/{name}.
    return _serve_local_output(name, storage)
