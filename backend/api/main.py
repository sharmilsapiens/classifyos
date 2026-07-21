"""ClassifyOS FastAPI application — the HTTP layer over the ML engine.

For a first-time reader, here is the whole request/response flow this app implements:

    browser ──HTTP(method + path + JSON body)──▶ uvicorn ──▶ FastAPI
        FastAPI matches the path to a Python function (an "endpoint"),
        validates the JSON body against a Pydantic model (HTTP 422 if it doesn't fit),
        runs the function (which calls the ML engine through ModelRunner / inspect_file),
        serializes whatever the function returns to JSON,
    browser ◀──────────────────────────────────────── and sends it back.

Key pieces and what each does:

* **uvicorn** — the always-on server process (``uvicorn api.main:app --reload --port 8000``).
  It keeps this app (and the imported engine) in memory and feeds it incoming HTTP requests.
* **FastAPI(app)** — the application object. Routers (groups of endpoints) are mounted onto
  it under the ``/api/v1`` prefix.
* **lifespan** — the modern startup/shutdown hook (replaces the deprecated
  ``@app.on_event("startup")``). Code before ``yield`` runs once at startup; code after runs
  at shutdown.
* **CORS** — browser security: a page served from origin A may not call an API on origin B
  unless the API explicitly allows A. We read that allowlist from the ``CORS_ORIGINS`` env
  var and never use ``["*"]`` outside an explicit local-dev marker.

This module adds NO ML logic — it is "the CLI, but the caller is a browser."
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

# [MANDATORY] Load backend/.env as the very first thing, before anything reads an env var.
# The engine does NOT auto-load .env (only the test suite does); without this call,
# LocalFolderStorage silently falls back to its relative ./data and ./classification_output
# defaults and CORS_ORIGINS reads empty. Same caveat the CLI documents.
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from .databricks import execution_backend  # noqa: E402
from .deps import get_storage  # noqa: E402
from .routes import databricks as databricks_routes  # noqa: E402
from .routes import (  # noqa: E402
    explain,
    health,
    input_sources,
    jobs,
    outputs,
    run,
    runs,
    upload,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def _cors_origins() -> list[str]:
    """Resolve the CORS allowlist from the environment.

    ``CORS_ORIGINS`` is a comma-separated list of allowed browser origins (e.g.
    ``http://localhost:5173,https://classify.sapiens.com``). We NEVER fall back to
    ``["*"]`` — a wildcard would let any website call this API from a user's browser —
    unless the explicit local-dev marker ``CLASSIFYOS_CORS_DEV`` is set truthy. That keeps
    the dangerous wildcard opt-in and impossible to ship to production by accident.
    """
    raw = os.environ.get("CORS_ORIGINS", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if not origins and os.environ.get("CLASSIFYOS_CORS_DEV", "").lower() in ("1", "true", "yes"):
        return ["*"]  # local-dev ONLY — never reached unless the dev marker is set
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown hook: log the resolved storage roots and confirm reachability.

    On startup we resolve and log the absolute ``DATA_DIR`` / ``OUTPUT_DIR`` — the same
    "always glance at where I'm reading/writing" safety the CLI prints — and constructing the
    adapter creates both folders, confirming storage is reachable. There is nothing to tear
    down on shutdown beyond a log line.
    """
    storage = get_storage()
    data_dir = getattr(storage, "data_dir", "<n/a>")
    output_dir = getattr(storage, "output_dir", "<n/a>")
    logger.info("ClassifyOS API starting — DATA_DIR=%s OUTPUT_DIR=%s", data_dir, output_dir)
    logger.info("CORS allowlist: %s", _cors_origins() or "(none configured)")
    # Databricks orchestration backend (§6.6 Step 6) is STATELESS: the Databricks run_id is the
    # job_id the UI polls with, so there is no job-state store to initialise here — status/results
    # poll Databricks directly (see routes/jobs.py). Just record the resolved backend.
    logger.info("Execution backend: %s", execution_backend())
    yield
    logger.info("ClassifyOS API shutting down")


app = FastAPI(
    title="ClassifyOS API",
    version="1.0",
    description="HTTP layer over the ClassifyOS ML classification engine.",
    lifespan=lifespan,
)

# CORS must be added as middleware (it runs for every request/response).
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount each router under /api/v1 (CLAUDE.md mandates the /api/v1/ prefix; the scope doc's
# bare /api/... table is superseded — recorded as a plan_tweak deviation).
for router in (
    health.router,
    upload.router,
    input_sources.router,
    run.router,
    jobs.router,
    runs.router,
    databricks_routes.router,
    explain.router,
    outputs.router,
):
    app.include_router(router, prefix=API_PREFIX)
