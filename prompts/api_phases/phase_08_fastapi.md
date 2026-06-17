# Phase 8 — FastAPI layer (wrap the ML engine, lock the /run response schema)

> Paste this whole file into a fresh Claude Code session in the ClassifyOS repo.
> This phase WRAPS the existing engine. It must not reimplement any ML logic.

---

## 0. Read first (in this order)

Before writing anything, read these and confirm you understand the current state:

- `CLAUDE.md` — the stable contract (architecture, hard rules, module map, env/`.env` rules).
- `PROJECT_STATE.md` — live status. The ML engine is feature-complete through Phase 7B;
  `ModelRunner(config, storage).run()` runs the whole pipeline end-to-end.
- `PROJECT_WISDOM.md` — how we work, the hard rules, and the lessons learned (esp. the
  `.env`/`load_dotenv()` fallback trap and the pipeline-order correction).
- `plan_tweak.md` — the deviation register (you will add rows to it this phase).
- `backend_short_desc.md` — what the engine does, phase by phase.
- `RUNBOOK.md` — how the CLI drives the engine (the API mirrors this, over HTTP).

The person directing this project is **new to FastAPI**. Every file you generate MUST
teach as it goes: short docstrings and inline comments explaining *what each FastAPI piece
does and why*, in plain terms (what an endpoint is, how a request flows in and a response
flows out, what Pydantic/CORS/uvicorn/lifespan each do). Favor clarity over cleverness.

---

## 1. What this phase is

Build the **FastAPI layer** in `backend/api/` that exposes the existing ML engine over HTTP
for the Phase 9 React frontend. The API is a thin translator: HTTP request in → call
`ModelRunner` (or `inspect_file`) exactly as the CLI does → JSON response out. **It adds no
ML logic.** Think of it as "the CLI, but the caller is a browser instead of a terminal."

**This is where the `/api/v1/run` response schema LOCKS.** The React frontend is generated
against it in Phase 9, so the shape defined here is a contract. Write it to
`docs/api_contract.md` and treat it as frozen after this phase (per CLAUDE.md).

---

## 2. Frozen vs sanctioned — what you may and may not touch

**FROZEN (do not edit):** everything under `backend/classifyos/` EXCEPT the one sanctioned
edit named below. The engine's behavior, pipeline order, wrappers, registry, config
contract, leakage guards, and `_run_config` isolation are all settled. The API calls the
engine; it never modifies or re-implements it.

**SANCTIONED ENGINE EDIT (the only one this phase) — curve points helper:**
Add a new function that computes ROC and PR curve *points* (the coordinate arrays the
frontend's Chart.js needs), so both `plot_results` and the API draw curves from ONE source
of truth instead of the API re-deriving ML math in the web layer.

- Add `compute_curve_points(y_true, y_proba, classes, problem_type) -> dict` to a NEW module
  `backend/classifyos/evaluation/curves.py` (new module = additive; preferred over editing
  `metrics.py`).
- It returns, per class (one-vs-rest for multiclass), the ROC points (`fpr`, `tpr`,
  `thresholds` or a sensible subset) and PR points (`precision`, `recall`), plus the scalar
  AUC/AP already available — computed with `sklearn.metrics.roc_curve` /
  `precision_recall_curve` / `auc` / `average_precision_score`.
- **[RISK] leakage note in the docstring:** this reads the ALREADY-PRODUCED test-set
  predictions/probabilities (`y_true`, `y_proba` from the held-out test set). It fits
  nothing and must never be given training data. Curve points always use the FULL test set
  (never the sampled predictions — see §4 `/run`).
- Refactor `plot_results` (plot2) to call `compute_curve_points` so the PNG and the JSON
  curves can never drift. Do NOT change plot2's output filename, appearance contract, or the
  placeholder-fallback behavior — only its internal source of the points.
- This is a NAMED, SANCTIONED deviation (record it in `plan_tweak.md` and the decisions log).

Everything else the API needs (metrics, predictions, confusion matrix, class report,
feature impact, run profile, artifact files) is ALREADY produced by `ModelRunner` /
`evaluate_model` / the output files — lift and reshape it, do not recompute it.

---

## 3. FastAPI concepts to embed in the code comments (teach the reader)

Put brief versions of these in the actual docstrings/comments as you build each piece:

- **uvicorn** — the always-on server process that keeps the imported engine in memory and
  hands incoming HTTP requests to FastAPI. Started with
  `uvicorn api.main:app --reload --port 8000`.
- **Endpoint** — a URL path bound to a Python function. A request to that path calls the
  function; whatever it returns is serialized to JSON and sent back. GET = "give me
  something, no body"; POST = "here is a body, do something with it."
- **Request/response flow** — browser sends method + path + (JSON) body → uvicorn receives
  → FastAPI matches the path, parses+validates the body into a Pydantic object → your
  function runs (calls the engine) → returns a dict → FastAPI serializes to JSON → back to
  the browser.
- **Pydantic (v2)** — declarative request validation. You declare the expected shape as a
  `BaseModel`; FastAPI validates the incoming body against it BEFORE your function runs and
  auto-returns HTTP 422 with a precise message if it's wrong. This is the web-layer twin of
  the engine's `build_config()` validation.
- **CORS** — browsers block a page on origin A from calling an API on origin B unless the
  API explicitly allows A. We read an allowlist from `CORS_ORIGINS` and NEVER use `["*"]`
  outside local dev (per the hard rules).
- **lifespan** — the modern startup/shutdown hook (the old `@app.on_event("startup")` is
  deprecated). Use an `@asynccontextmanager` `lifespan(app)` passed as
  `FastAPI(lifespan=...)`. Do startup work before `yield`, teardown after.
- **threadpool** — `ModelRunner.run()` is synchronous, CPU/IO-heavy Python. If called
  directly inside an `async def` endpoint it blocks the whole event loop (the server can't
  even answer a health check during a run). Offload it with
  `fastapi.concurrency.run_in_threadpool(...)` so the server stays responsive.

---

## 4. Files to create & their contracts

All under `backend/api/`. Mirror the module map in CLAUDE.md. Use Pydantic **v2** style.
**Every route function gets a docstring** explaining in one or two plain sentences what it
does and what it returns.

### `backend/api/main.py` — app construction
- **FIRST LINE of real work: `load_dotenv()`** (same mandatory caveat as the CLI — the
  engine does NOT auto-load `.env`; without this, `LocalFolderStorage` silently falls back
  to relative defaults and `CORS_ORIGINS` reads empty). Comment this clearly.
- Build the `StorageAdapter` (`LocalFolderStorage`) once and make it available to routes
  (module-level singleton or lifespan state — explain the choice in a comment).
- `lifespan(app)` async context manager: on startup, log the resolved `DATA_DIR`/`OUTPUT_DIR`
  (absolute paths — the same "always glance at these" safety the CLI prints) and confirm
  storage is reachable; nothing to tear down on shutdown beyond a log line. Pass via
  `FastAPI(lifespan=lifespan)`.
- `CORSMiddleware` with `allow_origins` read from `CORS_ORIGINS` (comma-separated env var) —
  **never `["*"]`** unless an explicit local-dev marker is set; comment the security reason.
- Mount the routers under the **`/api/v1`** prefix (CLAUDE.md mandates `/api/v1/`; the scope
  doc's `/api/...` table is superseded — record as a deviation).
- A short module docstring explaining the whole request/response flow for a first-time reader.

### `backend/api/models.py` — Pydantic request/response models
- `RunConfig(BaseModel)` — the **web-facing** request body. Fields mirror the user-settable
  config (target, feature_cols, problem_type, test_size, algorithms, class_balance,
  encoding/scaling/missing strategies, threshold, calibrate, interaction toggle, tuning
  toggle + dials). Sensible v2 defaults + validators for the 3 required fields (target,
  input_file, feature_cols) → these raise 422 when missing/empty. Docstring: explain this is
  the API contract, distinct from the engine's internal `DEFAULT_CONFIG`.
- Response models for the locked schema (below) — define them as Pydantic models too so the
  response shape is self-documenting and validated on the way out. Keep `result.*`
  sub-models small and named (`RunResult`, `ModelMetrics`, `RunMeta`, etc.).
- A `to_engine_config()` / `_make_config()` translator mapping `RunConfig` → the dict
  `build_config()` expects (this is where the web shape meets the engine's wider config
  contract; reconciles plan_tweak row 6).

### `backend/api/routes/` — the endpoints (one concern per file is fine)
All under `/api/v1`:

1. **`GET /api/v1/health`** — liveness check. Returns
   `{"status":"ok","service":"ClassifyOS API","version":"1.0"}`. (Simplest possible endpoint
   — use it to teach the GET flow in comments.)

2. **`POST /api/v1/upload`** — accept a CSV/Excel/Parquet file (`UploadFile`), save it via
   **StorageAdapter** (never `open()` directly), then call the engine's `inspect_file` and
   return its locked-contract keys (columns, dtypes, numeric/categorical/binary/datetime
   cols, n_rows, n_missing, sample, class_distribution, suggested_problem_type) plus the
   `server_path`/key the caller passes back to `/run`. Docstring: explain multipart upload
   and why we inspect on upload (populate the UI dropdowns).

3. **`POST /api/v1/run`** — the main endpoint. `async def`; body is `RunConfig`.
   - Translate `RunConfig` → engine config; build `ModelRunner(cfg, storage)`.
   - Run it via **`run_in_threadpool(runner.run)`** (comment WHY — don't block the loop).
   - Reshape the finished runner's state into the **locked response** (§5). Reuse
     `compute_curve_points` (the sanctioned helper) for `result.curves`, on the FULL test set.
   - **Sample** the predictions table (default cap, e.g. first N rows per model — make N a
     constant with a comment) and point callers at `classification_results.csv` (in
     `artifacts`) for the full table. Curve points and confusion matrix use the FULL test
     set regardless of the sample.
   - JSON-serialize safely: numpy/pandas types must not break `json` (reuse/extend the
     engine's existing `_safe`/`_jsonify` approach rather than inventing a new one).
   - Document the **synchronous + gateway-timeout limitation** in the docstring and point to
     the v1.5 background-job path. (Recorded in plan_tweak.)

4. **`POST /api/v1/explain`** — SHAP for a single row. **Read the statefulness note in §6
   first.** Implement the v1.0 behavior agreed there (re-fit-or-defer). Whatever the chosen
   behavior, the docstring must be honest about the cost/limitation.

5. **`GET /api/v1/outputs`** — list output files via StorageAdapter:
   `[{name, suffix, size_bytes}]`. (This is how the frontend discovers the 11 artifacts.)

6. **`GET /api/v1/outputs/{name}`** — stream one output file (CSV or PNG) back via
   StorageAdapter. Guard against path traversal (StorageAdapter already rejects escapes —
   rely on it, comment it). This is how PNGs are fetched on demand (never inlined in `/run`).

---

## 5. THE LOCKED `/api/v1/run` RESPONSE SCHEMA (write to docs/api_contract.md)

Top-level envelope (gives versioning room without breaking the lock later):

```jsonc
{
  "status": "ok",                  // "ok" | "error"
  "schema_version": "1.0",
  "result": {
    "run": {                       // curated run metadata (subset of run_profile.json)
      "target": "...",
      "problem_type": "binary|multiclass|multilabel",
      "features": ["..."],         // configured
      "active_features": ["..."],  // final engineered cols (incl. interaction cols)
      "interaction_cols": ["..."], // derived: active_features matching _x_/_div_/_minus_
      "class_distribution": {"...": 0},
      "n_rows": 0, "n_train": 0, "n_test": 0,
      "class_balance": "...", "class_weight": {"...": 0.0},
      "models_succeeded": 0,
      "timestamp": "UTC ISO-8601"
    },
    "models": [                    // LIST (renders with .map); includes failed rows
      {
        "name": "RandomForest",
        "status": "ok",            // "ok" | "failed"
        "accuracy": 0.0, "f1_weighted": 0.0, "f1_macro": 0.0,
        "precision_weighted": 0.0, "recall_weighted": 0.0,
        "roc_auc": 0.0, "pr_auc": 0.0, "log_loss": 0.0, "mcc": 0.0,
        "error": null              // string when status == "failed"
      }
    ],
    "predictions": {               // SAMPLED (see /run); full table via artifacts CSV
      "sample_rows": [ {"model": "...", "sample_index": 0, "actual": "...",
                        "predicted": "...", "confidence": 0.0, "correct_flag": true,
                        "probabilities": {"class_a": 0.0, "class_b": 0.0}} ],
      "sampled": true, "rows_returned": 0, "rows_total": 0,
      "full_csv": "classification_results.csv"   // fetch via /outputs/{name}
    },
    "confusion_matrix": {          // per model, FULL test set
      "RandomForest": {"labels": ["..."], "matrix": [[0,0],[0,0]]}
    },
    "class_report": {              // per class per model
      "RandomForest": [ {"class": "...", "precision": 0.0, "recall": 0.0,
                         "f1": 0.0, "support": 0} ]
    },
    "feature_impact": [            // ranked; preserves id_like leakage flag
      {"feature": "...", "dtype_group": "...", "anova_f": 0.0, "anova_p": 0.0,
       "mutual_info": 0.0, "point_biserial": null, "corr_ratio": null,
       "composite_score": 0.0, "id_like": false, "rank": 1}
    ],
    "curves": {                    // FULL test set, via compute_curve_points
      "RandomForest": {
        "roc": {"class_a": {"fpr": [0.0], "tpr": [0.0], "auc": 0.0}},
        "pr":  {"class_a": {"precision": [0.0], "recall": [0.0], "ap": 0.0}}
        // multiclass: one-vs-rest per class; PR may be omitted/placeholder per engine rules
      }
    },
    "artifacts": [                 // the 11 output files; PNGs fetched on demand
      {"name": "plot1_confusion_matrix.png", "suffix": ".png", "size_bytes": 0}
    ]
  }
}
```

Notes to encode in `docs/api_contract.md`:
- The envelope + `schema_version` are the forward-compat seam; bump to `1.1` for additive
  changes, never silently mutate `1.0`.
- `models` is intentionally a list (frontend `.map`), not a dict.
- `predictions` is sampled by design; `curves` and `confusion_matrix` are always full-test.
- PNGs are referenced by name only — fetched via `/outputs/{name}`, never base64-inlined.
- On `status: "error"`, `result` may be null and a top-level `error` string is present.

---

## 6. /explain statefulness — decide and document

A FastAPI process has **no memory between requests**: each request is independent, and
nothing from a previous `/run` is held in RAM (no trained model persists). SHAP needs a
fitted model + the row's processed features. v1.0 has no model persistence/registry (that's
out of scope — MLflow is a v2.0 item). So `/explain` must either:

- **(A) Re-fit on demand** from the same config + cached/known input file, then SHAP one row
  (correct but expensive — repeats training), **or**
- **(B) Ship a clearly-documented stub** that returns a structured "explainability requires a
  persisted model (v2.0)" response, wired and shaped so the full impl drops in later.

**Default to (A) for tree models (XGBoost/LightGBM via `shap.TreeExplainer`) with a hard,
documented cost note, and fall back to (B)'s structured response for models without a cheap
explainer** (SVM/NB/LR → permutation importance is out of scope this phase). Implement (A)
where cheap, (B) otherwise; the docstring states plainly which path ran and why. Record this
as a deviation/assumption in `plan_tweak.md` (the scope listed `/explain` without addressing
the no-persistence reality).

---

## 7. Tests (real data, real engine — no mocks of the engine)

Create `backend/tests/test_api_*.py` using FastAPI's `TestClient` (httpx-based). Run the
real engine on the real sample CSVs (`policy_lapse.csv`, `fraud_claims.csv`,
`risk_tier.csv`) — same fixtures the engine tests use. Redirect `OUTPUT_DIR` to a pytest
temp dir (reuse the existing conftest pattern — tests must never pollute the real output).

Cover at least:
- `GET /health` → 200 + expected body.
- `POST /upload` with each sample file → 200 + inspect keys present + a usable `server_path`.
- 422 validation: `POST /run` with empty/missing target / input_file / feature_cols → 422.
- `POST /run` end-to-end (binary + multiclass) → 200, and the response **matches the locked
  schema** (assert every top-level `result.*` key; `models` is a list; failed-algo row
  carries `status="failed"` + `error`; `predictions.sampled` true with `full_csv` set;
  `curves` present and computed on full test; `artifacts` lists the PNGs).
- JSON-serialization safety: a run whose metrics include NaN/Inf/numpy types serializes
  without error (no 500).
- `GET /outputs` lists files; `GET /outputs/{name}` returns a PNG and a CSV; a traversal
  attempt (`../something`) is rejected.
- `compute_curve_points` unit test in `tests/test_curves.py`: ROC/PR points are monotone/
  well-formed on a known binary split; multiclass returns one-vs-rest per class; it is never
  passed training data (signature/structural check); plot2 still renders (regression).
- `/explain` per the §6 behavior: tree-model path returns SHAP values for one row; non-tree
  path returns the documented structured fallback.

All existing tests must still pass (148 currently). Report the new total.

---

## 8. Hard rules (verbatim — do not violate)

- **StorageAdapter for ALL file I/O.** No `open()`, no `os.path` reads/writes, no hardcoded
  paths anywhere in `api/`. Uploads, output listing, and downloads all go through it.
- **No leakage.** The API only ever calls the engine, which already fits on train-only. The
  curve helper reads the held-out test predictions; it fits nothing.
- **`load_dotenv()` at API startup** (before storage/CORS read env). Same caveat as the CLI.
- **CORS allowlist from env; never `["*"]`** outside an explicit local-dev marker.
- **`_run_config` isolation preserved** — the API constructs a fresh config per request and
  hands it to `ModelRunner`, which deep-copies it; the API never mutates a shared config.
- **Pydantic v2** style throughout. Type hints + docstrings on every public function.
- **Additive.** New code in `api/` + the one new `evaluation/curves.py` module + the sanctioned
  plot2 refactor. No other engine edits.

---

## 9. WRAP-UP BLOCK (mandatory — do all of it before finishing)

1. **Archive this prompt** to `prompts/api_phases/phase_08_fastapi.md` (verbatim), committed
   in the same commit as the code.
2. **Update `PROJECT_STATE.md`:** flip Phase 8 to ✅; add a "Completed this session (Phase 8)"
   entry (endpoints built, schema locked, curve helper added, test count); add decisions-log
   rows (the curve-points sanctioned edit; the sync+threadpool execution model; the
   `/api/v1` prefix superseding the scope's `/api`; the `/explain` v1.0 behavior); update the
   governance checklist (note the API contract is now LOCKED after Phase 8); add a session-log
   row; set "Next steps" to Phase 9 (React generated against the locked contract).
3. **Create `api_short_desc.md`** (NEW): open with the shared short **"About ClassifyOS"**
   header (one short paragraph: GenAI-developed insurance classification engine; React →
   FastAPI → Python engine; this file covers the API surface). Then plain-language,
   one-line-per-component summaries of every endpoint + the locked schema + the curve helper.
   Reference it from `backend_short_desc.md`'s "how to read this project" list.
4. **Update `plan_tweak.md`** — add rows for the REAL deviations this phase (and only these):
   (a) the sanctioned `evaluation/curves.py` helper + plot2 refactor (engine edit during the
   API phase); (b) `/run` is synchronous with a gateway-timeout limitation (background jobs
   deferred to v1.5); (c) `/explain` re-fit-or-stub given no model persistence in v1.0;
   (d) route prefix `/api/v1/` supersedes the scope doc's `/api/...` endpoint table. (If any
   of these ended up NOT actually deviating as built, omit that row — never pad the register.)
5. **Lock `docs/api_contract.md`** — the §5 schema, marked LOCKED (Phase 8), with the notes.
6. **Hallucination check (governance):** verify every web-framework call against the INSTALLED
   versions in the venv before merge — FastAPI (lifespan signature, `CORSMiddleware`,
   `UploadFile`, `run_in_threadpool`, `FileResponse`/`StreamingResponse`), Pydantic v2
   (`BaseModel`, field defaults, validators), Starlette `TestClient`/httpx, and the sklearn
   curve functions (`roc_curve`/`precision_recall_curve`/`auc`/`average_precision_score`).
   Pin any newly added deps in `requirements.txt` + re-freeze `requirements.lock`. Record the
   checked versions in the PROJECT_STATE entry (as prior phases did).
7. **Commit message:**
   `Phase 8: FastAPI layer (health/upload/run/explain/outputs) + locked /api/v1/run schema + curves helper + tests`

When done, report: endpoints implemented, the final locked schema location, new test count
(and that the prior suite still passes), the versions you hallucination-checked, and any
plan_tweak rows you added (or deliberately did not).

---

## Build notes (added by Claude Code at execution — not part of the original prompt)

Two design forks were surfaced to the project owner before building (both resolved to the
recommended option):

- **Upload storage gap.** `StorageAdapter.open_write` targets `OUTPUT_DIR`, but `inspect_file`
  / `data_loader` read from `DATA_DIR`, so a file saved via the existing API could not be
  read back by `/run`. Resolved by adding a small **additive** `save_input(key, fileobj)`
  method to the `StorageAdapter` ABC + `LocalFolderStorage` (writes into the input root,
  traversal-guarded). This honors CLAUDE.md's "ALL file I/O through StorageAdapter"
  NEVER-rule; recorded as a plan_tweak deviation. It is a second sanctioned engine edit
  beyond the curve helper, made necessary by the upload requirement.
- **`/explain` + SHAP.** `shap` is not installed and v1.0 has no model persistence, so the
  prompt's option (A) (re-fit + TreeExplainer) was not viable without a heavy dependency and
  per-request retraining. Shipped option **(B)** — the structured stub for all models —
  per §6's explicit fallback, recorded as a plan_tweak deviation.
