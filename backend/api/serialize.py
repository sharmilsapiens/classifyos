"""JSON-safety helpers for the API layer.

The ML engine produces values that plain ``json``/HTTP cannot represent: numpy scalars
(``np.float64``, ``np.int64``), numpy arrays, pandas ``NA``, and — crucially — ``NaN`` /
``Infinity`` floats (a degenerate metric, an undefined AUC). ``NaN``/``Inf`` are not valid
JSON, so emitting them would either raise or produce a body a browser's ``JSON.parse``
rejects.

:func:`safe_jsonify` walks any nested structure and returns one built only from plain,
JSON-valid Python types, mapping every non-finite float to ``None``. It deliberately builds
on the engine's own :func:`classifyos.evaluation.metrics._jsonify` (numpy → Python) so the
two stay consistent — the API adds only the NaN/Inf → None step on top.
"""

from __future__ import annotations

import math
from typing import Any

from classifyos.evaluation.metrics import _jsonify as _engine_jsonify


def safe_jsonify(obj: Any) -> Any:
    """Return a deep copy of ``obj`` containing only JSON-serializable Python types.

    numpy scalars/arrays are converted to Python via the engine's ``_jsonify``; then every
    float is checked and any ``NaN``/``Infinity`` is replaced with ``None`` so the result
    survives strict JSON encoding (no 500s, no invalid bodies).
    """
    return _strip_non_finite(_engine_jsonify(obj))


def _strip_non_finite(obj: Any) -> Any:
    """Recursively replace NaN/Inf floats with None (inputs already numpy-free)."""
    if isinstance(obj, dict):
        return {k: _strip_non_finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_strip_non_finite(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj
