"""Shared dependencies for the API routes.

In FastAPI, a *dependency* is a function whose return value is injected into a route by
declaring ``param = Depends(the_function)``. FastAPI calls it for you per request and passes
the result in. We use one here to hand every route the same :class:`StorageAdapter` — the
single object through which ALL file I/O must flow (CLAUDE.md hard rule).

The adapter is built lazily and cached: it is constructed on the FIRST request, not at
import time. That matters for the test suite, which redirects ``OUTPUT_DIR`` to a temp folder
via an environment variable *before* the first request — constructing eagerly at import would
capture the real output folder instead.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

from classifyos.io.storage import LocalFolderStorage, StorageAdapter

_storage: StorageAdapter | None = None


def get_storage() -> StorageAdapter:
    """Return the process-wide storage adapter (constructed once, lazily).

    Today this is always :class:`LocalFolderStorage` (reads ``DATA_DIR``, writes
    ``OUTPUT_DIR``). A future ``DatabricksVolumeStorage`` would slot in here behind the same
    interface without touching any route.
    """
    global _storage
    if _storage is None:
        _storage = LocalFolderStorage()
    return _storage


def get_user_pat(
    x_databricks_token: Annotated[str | None, Header(alias="X-Databricks-Token")] = None,
) -> str | None:
    """Return the caller's Databricks PAT from the ``X-Databricks-Token`` header, or ``None``.

    Used by the Databricks orchestration routes (§6.6 Step 6) so the Job reads Unity Catalog data
    as the requesting user and the UC-browser proxies query as that user. The PAT is **never
    persisted** — it lives only for the duration of the request. Routes that require it raise a
    clean 401 when it is absent (a ``None`` here), rather than FastAPI's generic 422 for a missing
    header, so the UI can prompt for the token.
    """
    return x_databricks_token
