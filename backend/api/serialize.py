"""JSON-safety helpers for the API layer.

The implementation moved into the engine (:mod:`classifyos.envelope.serialize`) so the Databricks
Job notebook can build the ``/run`` envelope from the installed wheel alone. This module re-exports
:func:`safe_jsonify` unchanged, so ``from api.serialize import safe_jsonify`` keeps working.
"""

from __future__ import annotations

from classifyos.envelope.serialize import safe_jsonify

__all__ = ["safe_jsonify"]
