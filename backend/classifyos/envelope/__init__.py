"""ClassifyOS run-result envelope — the SINGLE source of the locked ``/api/v1/run`` response.

Reshapes a finished :class:`~classifyos.runner.ModelRunner` into the frozen
``docs/api_contract.md`` shape. It lives in the ENGINE (not the FastAPI layer) so BOTH consumers
build a **byte-identical** envelope from the same code:

* the FastAPI layer (``api.result_builder`` / ``api.serialize`` / ``api.artifacts`` / ``api.models``
  re-export these names, so nothing on the web side changed), and
* the Databricks Job notebook, which has only the installed wheel — no ``backend/`` checkout — and
  calls :func:`build_run_envelope` to produce the whole ``{status, schema_version, result, error}``
  wire response in one line.

Pure data plumbing — **no ML**. Depends on ``pydantic`` for the response models (already present
via ``mlflow``); it imports no web framework, so a pure-engine CLI run never pulls in FastAPI.
"""

from __future__ import annotations

from .artifacts import ARTIFACT_KEYS, collect_artifacts
from .result_builder import (
    PREDICTION_SAMPLE_PER_MODEL,
    build_run_envelope,
    build_run_result,
)
from .schema import SCHEMA_VERSION, RunResponse, RunResult
from .serialize import safe_jsonify

__all__ = [
    "ARTIFACT_KEYS",
    "PREDICTION_SAMPLE_PER_MODEL",
    "SCHEMA_VERSION",
    "RunResponse",
    "RunResult",
    "build_run_envelope",
    "build_run_result",
    "collect_artifacts",
    "safe_jsonify",
]
