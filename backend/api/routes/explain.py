"""``POST /api/v1/explain`` — per-row explainability (v1.0 structured stub).

The honest constraint behind this endpoint: **a FastAPI process has no memory between
requests.** Each request is independent and nothing from a previous ``/run`` is held in RAM —
no trained model persists. A SHAP explanation needs a *fitted* model plus the row's processed
features, and v1.0 has no model persistence or registry (that is a v2.0 item — MLflow).

Two ways to honor that were considered (see PROJECT_STATE / plan_tweak):
    (A) re-fit the model on demand from the same config, then SHAP one row — correct but it
        repeats full training on every call, and SHAP is not even installed; and
    (B) return a clearly-documented structured response that says explainability needs a
        persisted model, shaped so the real implementation drops straight in later.

**v1.0 ships (B) for every model.** This route always returns the structured "unavailable"
payload below — it never trains. The field shape (``method``/``shap_values``/``base_value``)
is the final contract; v2.0 fills the nulls once a persisted model is addressable.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter

router = APIRouter(tags=["explain"])


class ExplainRequest(BaseModel):
    """What a future SHAP impl will need to locate a model + the row to explain.

    Captured now so the request contract is stable: the frontend can build against it today
    even though v1.0 returns a stub. ``input_file``/``target``/``feature_cols`` identify the
    dataset+config to re-fit (path A) or the persisted run to load (path B/v2.0); ``model``
    picks which trained algorithm; ``sample_index`` selects the test row.
    """

    input_file: str
    target: str
    feature_cols: list[str] = Field(default_factory=list)
    model: str = "RandomForest"
    sample_index: int = 0


@router.post("/explain")
def explain(req: ExplainRequest) -> dict[str, object]:
    """Return a structured explainability response (v1.0: a documented stub).

    Path taken: **(B) stub** — no model is trained or loaded. The response states plainly
    that single-row SHAP needs a persisted model, which v1.0 does not have, and carries the
    final field shape so v2.0 can populate it without changing the contract.
    """
    return {
        "status": "unavailable",
        "schema_version": "1.0",
        "model": req.model,
        "sample_index": req.sample_index,
        "method": None,  # v2.0: "shap.TreeExplainer" | "permutation" | ...
        "shap_values": None,  # v2.0: {feature: contribution}
        "base_value": None,  # v2.0: model expected value
        "reason": "no_persisted_model",
        "message": (
            "Single-row SHAP explanations require a fitted model and its processed features. "
            "v1.0 is stateless — no model from a prior /run is held in memory and there is no "
            "model registry — so explainability is deferred to v2.0 (model persistence / "
            "MLflow). This response shape is final; the null fields populate once persistence "
            "lands."
        ),
    }
