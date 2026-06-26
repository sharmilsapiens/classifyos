"""``POST /api/v1/upload`` — accept a dataset, store it, and profile it.

This is a *multipart/form-data* upload: instead of a JSON body, the browser sends the raw
file bytes (plus optional form fields) the way an HTML ``<input type=file>`` does. FastAPI
hands us the file as an ``UploadFile``.

Why inspect on upload? So the browser's run-setup screen can immediately populate its column
pickers, problem-type suggestion, and class-distribution preview from the real file — the
user configures a run against what's actually in their data, not guesses. We save the file
(through the StorageAdapter, into the INPUT root so a later ``/run`` can read it) and return
both the inspection profile and the ``server_path`` key the caller passes back to ``/run``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from classifyos.io.inspect import inspect_file
from classifyos.io.storage import StorageAdapter

from ..deps import get_storage
from ..serialize import safe_jsonify

router = APIRouter(tags=["upload"])

# Datasets are stored under this input-root subfolder so uploads never clobber the committed
# sample CSVs that seed DATA_DIR.
UPLOAD_PREFIX = "uploads"
_ALLOWED_SUFFIXES = (".csv", ".xlsx", ".xls", ".parquet", ".pq")


@router.post("/upload")
async def upload(
    file: UploadFile = File(..., description="CSV, Excel, or Parquet dataset."),
    target: str | None = Form(None, description="Optional target column for a class preview."),
    storage: StorageAdapter = Depends(get_storage),
) -> dict[str, object]:
    """Save an uploaded dataset and return its inspection profile + storage key.

    The file is written via ``StorageAdapter.save_input`` (into ``DATA_DIR/uploads/``), then
    profiled with the engine's ``inspect_file``. Returns the inspect keys (columns, dtypes,
    the numeric/categorical/binary/datetime column groups, n_rows, n_missing, a small sample,
    and — when ``target`` is given — class_distribution + suggested_problem_type), the
    additive Data-Profile blocks (``column_profiles`` + ``correlation`` for the exploration
    view), plus ``server_path``: the logical key to pass as ``input_file`` to ``/run``.
    """
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=422, detail="uploaded file has no filename")
    if not filename.lower().endswith(_ALLOWED_SUFFIXES):
        raise HTTPException(
            status_code=422,
            detail=f"unsupported file type for {filename!r}; expected csv, xlsx, or parquet",
        )

    # Save through the storage abstraction (never a raw open) into the input root, so the
    # later /run — whose loader reads from DATA_DIR — can find it under this same key.
    key = f"{UPLOAD_PREFIX}/{filename}"
    storage.save_input(key, file.file)

    # Profile the just-saved file. A bad target (not in the file) raises ValueError → 422.
    # profile=True attaches the per-column Data-Profile blocks for the exploration view.
    try:
        result = inspect_file(key, storage, target=target, profile=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # server_path is the key the frontend echoes back to /run as input_file.
    result["server_path"] = key
    # NaN/Inf → null (e.g. the std of a constant column, an undefined correlation) so the
    # body is strict-JSON-valid for the browser parser.
    return safe_jsonify(result)
