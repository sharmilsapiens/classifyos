"""``GET /api/v1/health`` — the simplest possible endpoint (liveness check).

This is the canonical "is the server up?" probe. It is also the clearest example of the GET
flow: a GET request carries no body; the path is matched to this function; the dict it
returns is serialized to JSON and sent back. No engine call, no I/O — it answers instantly,
which is exactly why monitors and load balancers poll it.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..databricks import execution_backend

# An APIRouter is a group of related endpoints. main.py mounts it under the /api/v1 prefix,
# so the path declared here ("/health") becomes "/api/v1/health".
router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return a small fixed payload confirming the API process is alive.

    ``execution_backend`` (``"local"`` | ``"databricks"``, §6.6 Step 6) lets the frontend decide
    whether ``POST /run`` returns results synchronously (local) or a ``{job_id}`` to poll
    (databricks). Additive to the payload; the liveness fields are unchanged.
    """
    return {
        "status": "ok",
        "service": "ClassifyOS API",
        "version": "1.0",
        "execution_backend": execution_backend(),
    }
