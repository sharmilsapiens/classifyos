"""Output-artifact endpoints — how the frontend discovers and fetches run outputs.

* ``GET /api/v1/outputs`` — list the artifacts a run produced (name, suffix, size).
* ``GET /api/v1/outputs/{name}`` — stream one artifact (a CSV or a PNG) back to the browser.

PNGs are deliberately NOT inlined into the ``/run`` JSON (that would bloat the response and
couple chart data to image bytes); the dashboard fetches each image here, on demand, by name.
All path resolution goes through the :class:`StorageAdapter`, whose ``path_for`` rejects
path-traversal escapes (``../etc/passwd``) — we rely on that and surface a clean 400.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from classifyos.io.storage import StorageAdapter

from ..artifacts import collect_artifacts
from ..deps import get_storage

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


@router.get("/outputs/{name}")
def get_output(
    name: str,
    storage: StorageAdapter = Depends(get_storage),
) -> FileResponse:
    """Stream a single output file (CSV or PNG) back to the caller.

    The filename is resolved against the OUTPUT root through the storage adapter, which
    rejects any path-traversal attempt (``..`` escaping the root) by raising — we translate
    that into HTTP 400. A resolved-but-missing file is a 404.
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
