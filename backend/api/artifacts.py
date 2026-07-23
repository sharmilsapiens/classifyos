"""The canonical set of output artifacts a run produces.

The implementation moved into the engine (:mod:`classifyos.envelope.artifacts`) so the Databricks
Job notebook can build the ``/run`` envelope from the installed wheel alone. This module re-exports
:data:`ARTIFACT_KEYS` and :func:`collect_artifacts` unchanged, so
``from api.artifacts import collect_artifacts`` keeps working.
"""

from __future__ import annotations

from classifyos.envelope.artifacts import ARTIFACT_KEYS, collect_artifacts

__all__ = ["ARTIFACT_KEYS", "collect_artifacts"]
