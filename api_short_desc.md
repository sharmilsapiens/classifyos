# ClassifyOS — API Surface (Plain-Language Summary)

## About ClassifyOS

ClassifyOS is a GenAI-developed machine-learning framework for the insurance domain: it
predicts categorical outcomes (will a policy lapse? is a claim fraudulent? which risk tier?)
from ordinary tabular data. It is built in three layers — a **React** browser frontend talks
to a **FastAPI** backend, which drives a pure-Python **ML engine**. You set a run up in the
browser, it is sent to the API, the engine executes it, and the results stream back as JSON
to fill charts and tables. This file covers the **API surface** (the FastAPI layer). For the
engine itself see `backend_short_desc.md`.

---

## What the API is

The API is a thin translator: an HTTP request comes in, it calls the existing ML engine
(`ModelRunner` / `inspect_file`) exactly as the command-line tool does, and sends JSON back.
**It adds no machine-learning logic** — think of it as "the CLI, but the caller is a browser
instead of a terminal." It was built in Phase 8 and is the point at which the `/run` response
shape was **locked** (frozen) so the frontend can be built against a stable contract.

## The endpoints (all under `/api/v1/`)

- **`GET /health`** — the simplest check: "is the server up?" Returns a tiny fixed message.
  Monitors poll this.
- **`POST /upload`** — the browser uploads a data file (CSV/Excel/Parquet). The API saves it
  (through the storage gateway, into the input folder so a later run can read it) and
  immediately *inspects* it — returning the columns, types, missing-value counts, a small
  sample, and a guessed problem type — so the setup screen can populate its dropdowns. It
  hands back a `server_path` the browser passes to `/run`.
- **`POST /run`** — the main event. The browser sends the run configuration; the API runs the
  whole pipeline (train every requested model, score them, draw the charts, write all files)
  and returns one big, fixed-shape JSON result: run metadata, a per-model scoreboard, a
  sample of the predictions table, confusion matrices, per-class breakdowns, the ranked
  feature impact, the ROC/PR curve points for charts, and the list of downloadable files.
- **`POST /explain`** — meant for "why did the model predict this for this one row?" (SHAP).
  **In v1.0 this is an honest placeholder**: the server keeps no trained model between
  requests and there's no model store yet, so it returns a clearly-structured "not available
  until v2.0" response shaped so the real feature can drop in later.
- **`GET /outputs`** — lists the result files a run produced (name, type, size).
- **`GET /outputs/{name}`** — downloads one result file (a CSV or a chart PNG). The charts are
  fetched here on demand, never stuffed into the `/run` response.

## The locked `/run` result (the contract)

The `/run` response is **frozen** at version `1.0` (see `docs/api_contract.md`). Key points
the frontend relies on: models come back as a **list** (so a failed model is shown, not
hidden); the predictions table is **sampled** for display (the full table is a downloadable
CSV); the confusion matrices and curves are always computed on the **full** test set; charts
are referenced by filename only; and every number is JSON-safe (undefined values become
`null`, never broken JSON). Future changes must be additive and bump the version number.

## Supporting pieces

- **The curve helper (`evaluation/curves.py`, `compute_curve_points`)** — one shared function
  that turns test predictions into ROC/PR chart coordinates. Both the saved chart image
  (`plot2`) and the interactive chart in the browser use it, so the two can never disagree. It
  only ever reads the held-out test predictions — it trains nothing.
- **Request validation** — the API checks the incoming configuration before doing any work and
  rejects bad requests with a precise "422" error (e.g. a missing target), reusing the engine's
  own validation so the rules can't drift between the two layers.
- **CORS & startup** — the API only allows browser origins from an approved list (never a
  blanket wildcard in production), and on startup it loads its environment settings and logs
  exactly which data/output folders it's using.

---

## How to read this project

- **CLAUDE.md** — the conventions and hard rules.
- **PROJECT_STATE.md** — the live status (done, decisions, issues, next steps).
- **plan_tweak.md** — the honest register of deviations from the signed plan.
- **docs/api_contract.md** — the **locked** `/run` request/response schema (the frozen contract).
- **backend_short_desc.md** — plain-language summary of the ML engine.
- **api_short_desc.md** (this file) — plain-language summary of the API surface.
  (Future sibling: `frontend_short_desc.md`.)
