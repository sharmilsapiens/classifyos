# ClassifyOS API Contract

> **STATUS: STUB — NOT LOCKED.** This contract locks after Phase 8 (FastAPI layer).
> Once locked, the frontend is generated against it and the response schema must not
> change silently. See CLAUDE.md → "API contract is locked after Phase 8."

## Conventions

- All routes are prefixed with `/api/v1/`.
- CORS uses an env-configured allowlist (`CORS_ORIGINS`) — never `["*"]` outside local dev.
- Request bodies and responses are JSON. File uploads use `multipart/form-data`.
- `RunConfig` (Pydantic v2) is the canonical request model for a run.

## Endpoints (planned — to be finalized in Phase 8)

| Method | Path | Purpose | Status |
|---|---|---|---|
| `GET`  | `/api/v1/health` | Liveness check | TBD |
| `POST` | `/api/v1/inspect` | Inspect an uploaded/known CSV (Section 3) | TBD |
| `POST` | `/api/v1/run` | Execute a full classification run (ModelRunner) | TBD |

## `POST /api/v1/run`

### Request — `RunConfig`

```jsonc
// TODO (Phase 8): finalize against backend/api RunConfig (Pydantic v2).
{
  "file": "samples/lapse.csv",
  "target": "will_lapse",
  "problem_type": "binary"        // binary | multiclass | multilabel
  // ... preprocessing, feature, model, split options
}
```

### Response

```jsonc
// TODO (Phase 8): finalize. Streams/returns metrics, plots, predictions.
{
  "status": "ok",
  "metrics": {},                  // F1-weighted primary; MCC, PR-AUC, Accuracy
  "plots": {},
  "predictions": []
}
```

---

_This file is a stub. Do not treat any schema above as locked until Phase 8 sign-off._
