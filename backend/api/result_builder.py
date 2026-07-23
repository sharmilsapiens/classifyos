"""Reshape a completed :class:`~classifyos.runner.ModelRunner` into the locked ``/run`` envelope.

The implementation moved into the engine (:mod:`classifyos.envelope.result_builder`) so there is
exactly ONE reshaper, reusable by both the synchronous ``POST /api/v1/run`` route (local backend)
and the Databricks Job notebook (which has only the installed wheel — no ``backend/`` checkout).
This module re-exports the public names unchanged, so ``from api.result_builder import
build_run_result`` keeps working.

:func:`build_run_result` returns the ``result`` block; :func:`build_run_envelope` returns the whole
``{status, schema_version, result, error}`` wire envelope (what the Databricks notebook writes).
"""

from __future__ import annotations

from classifyos.envelope.result_builder import (
    PREDICTION_SAMPLE_PER_MODEL,
    build_run_envelope,
    build_run_result,
)

__all__ = ["PREDICTION_SAMPLE_PER_MODEL", "build_run_envelope", "build_run_result"]
