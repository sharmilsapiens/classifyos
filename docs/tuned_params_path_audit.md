# Tuned-Hyperparameters Data Path — Audit (engine → API → UI)

> **READ-ONLY investigation.** No code, tests, or contract changed. This report traces where
> tuned-hyperparameter data currently travels and where it stops, so the "show the chosen
> hyperparameters in the dashboard" feature can be built coherently across all three layers
> without breaking the locked `/api/v1/run` contract.
>
> Run after Phase 7B.2 (search-space expansion) landed, so `best_params` reflects the expanded
> spaces (LightGBM `max_depth`, XGBoost `gamma`, SVM real `kernel` choice — see
> `backend_short_desc.md` Phase 7B and `backend/classifyos/tuning.py`).
>
> Scope: ONE data path — the per-model tuned hyperparameters (`best_params`).

---

## Section A — Current state

Does the tuned-params data exist at each layer, in what shape, and what is the exact
field/file/type?

| Layer | Exists here? | Shape | Exact field / file / type (source) |
|---|---|---|---|
| **Engine** | **Yes** — produced and held two ways | In-memory dict `{model_name: {param: value}}`; also serialized into the run profile | **In memory:** `ModelRunner.tuned_params_: dict[str, dict[str, Any]]` — set in `run()` from `self._tune(...)` (`backend/classifyos/runner.py:113`, populated at `runner.py:176`). **On disk:** `run_profile.json` → `tuning` block with `tuned_models` (sorted `list[str]`) and `best_params` (`{name: params}`), plus the tuning settings (`enabled/metric/cv/cv_folds/n_trials/timeout_seconds`) — built in `_build_run_profile` (`runner.py:490–502`). Each `tune_model` call returns the best params dict (`backend/classifyos/tuning.py:512`, `tune_model` docstring `tuning.py:410–438`). |
| **API** | **No** (in the typed `/run` response) — **Yes** (only as a downloadable file) | Per-model best params are **absent** from the locked response envelope | The `/run` reshaper `_run_meta` cherry-picks fields from `runner.run_profile_` but **omits the `tuning` block entirely** (`backend/api/routes/run.py:108–128`). Neither `RunMeta` (`backend/api/models.py:151–166`) nor `RunResult` (`models.py:250–262`) declares a tuning field. The data is reachable **only** as the raw artifact: `run_profile.json` is in `ARTIFACT_KEYS` (`backend/api/artifacts.py:21`) and downloadable via `GET /api/v1/outputs/{name}` (served `application/json`, `backend/api/routes/outputs.py:44–65`). |
| **UI** | **No** | Not received, not stored, not displayed | `tuning` appears in the typed client **request-side only** (`TuningConfig`, `frontend/src/api/types.ts:37–48`; sent by `Configure.tsx` via `buildPayload.ts`). The **response** types have no tuning field — `RunMeta` (`types.ts:84–98`), `RunResult` (`types.ts:199–208`). The store holds only `result: RunResponse` (`frontend/src/store/AppStore.tsx`). The only result-page references to "tuning" are **prose** (Overview's running-state text, `Overview.tsx:93`). There is **no model-detail page**. |

---

## Section B — The gap

**The data stops at the API response boundary.**

The engine fully produces the tuned hyperparameters — it both holds them in memory
(`ModelRunner.tuned_params_`) **and** writes them to `run_profile.json`
(`tuning.best_params` + `tuning.tuned_models`). But the `/api/v1/run` response reshaper
(`_build_result` / `_run_meta` in `run.py`) never copies the `tuning` block out of
`runner.run_profile_`, and the locked response models (`RunMeta`, `RunResult` in
`api/models.py`) declare no field to carry it.

Because the typed contract omits it, the React app never receives it: `types.ts` mirrors the
contract exactly (by rule — no invented fields), so there is nothing for the store to hold or
a page to render.

> **One-line gap:** *the engine produces tuned params (in `self.tuned_params_` and
> `run_profile.json`), but the `/run` response model and serializer omit them, so the UI never
> receives a typed tuning field — it can only see them by separately downloading the
> `run_profile.json` artifact.*

The data is **not lost** — it is on disk and fetchable via `/outputs/{name}` — it is simply
not part of the typed, versioned `/run` contract the dashboard is built against.

---

## Section C — Change options

### Option 1 — Additive `result.tuning` field on the locked `/run` response (+ UI panel)

Add one new **optional** block to the response and bump `schema_version` `1.0` → `1.1`.
**No engine change** — the runner already produces everything; the serializer just copies it.

**Exact field shape to add** (mirrors `run_profile.json`'s `tuning` block one-for-one, so the
serializer can copy `runner.run_profile_["tuning"]` directly — or read `runner.tuned_params_`):

```jsonc
"result": {
  // ...existing locked 1.0 fields, unchanged...
  "tuning": {                       // NEW in 1.1 — null/absent when tuning was OFF
    "enabled": true,
    "metric": "f1_weighted",
    "cv": true,
    "cv_folds": 3,
    "n_trials": 30,
    "timeout_seconds": 600,
    "tuned_models": ["XGBoost"],    // models that produced tuned params
    "best_params": {                // per-model chosen hyperparameters
      "XGBoost": { "learning_rate": 0.07, "max_depth": 6, "n_estimators": 450,
                   "gamma": 1.2, "reg_alpha": 0.03 }
    }
  }
}
```

Types: `best_params` values are heterogeneous (float / int / str / bool), so type it
`dict[str, dict[str, Any]]` (Pydantic) and `Record<string, Record<string, unknown>>` (TS).
Make the whole block optional (`tuning: RunTuning | None = None`) so a non-tuning run is
unchanged and old `1.0` behaviour is preserved.

**Files that change (per layer):**
- *Engine:* **none.**
- *API:* `docs/api_contract.md` (add the additive `1.1` block + bump note), `backend/api/models.py`
  (new `RunTuning` response sub-model + `tuning` field on `RunResult` + `RunResponse.schema_version`
  default `"1.0"`→`"1.1"`), `backend/api/routes/run.py` (new `_tuning(runner)` helper + add to
  `_build_result`), `api_short_desc.md` (note the new field), plus an additive API test.
- *UI:* `frontend/src/api/types.ts` (new `RunTuning` interface + optional `tuning` on `RunResult`),
  a host panel (extend `Overview.tsx`, the natural home — see below), fixtures + a render test,
  `frontend_short_desc.md`. `parse.ts` needs **no change** (it structurally checks only the known
  keys and passes `result` through; an extra optional key is ignored — `parse.ts:29–41,69–70`).

**Tradeoffs:** clean, typed, versioned; the dashboard consumes a contract-guaranteed field
instead of scraping an engine artifact; trivial backend change (copy an already-built dict, no
ML, no engine edit). Cost: a one-time additive contract bump touching all three layers.

### Option 2 — UI reads `run_profile.json` via `/api/v1/outputs` (no contract change)

The dashboard fetches `outputUrl("run_profile.json")` (the client already has `outputUrl`),
parses the JSON, and reads `.tuning.best_params` to render the panel. No backend or contract
change at all.

**Files that change:** *frontend only* — a fetch + parse helper and the host panel. Engine and
API untouched; `schema_version` stays `1.0`.

**Tradeoffs / downsides:**
- **Untyped, unguaranteed coupling.** `run_profile.json`'s internal shape is **not** part of the
  locked contract; it could change with engine work and silently break the UI, with no version
  signal. This is exactly the drift the locked contract + `parse.ts` exist to prevent.
- **Extra network round-trip** per result view (a second fetch beyond `/run`), and JSON parsing
  of a file rather than reading a typed, already-validated field.
- **Bypasses the contract discipline** ("the typed client mirrors the contract exactly") — the UI
  would now depend on an engine artifact format the contract makes no promises about.

### Recommendation — **Option 1**

The locked-contract discipline exists precisely so the UI consumes typed, versioned fields
rather than scraping engine artifacts, and the additive change here is genuinely cheap: the
runner **already** holds the data (`tuned_params_`) and **already** writes it
(`run_profile.json`), so the backend work is a copy in the serializer plus an optional response
field — **zero engine change**. The version bump is provably safe (see Section D). Option 2
trades that one-time additive change for permanent untyped coupling and an extra fetch, and
quietly erodes the contract guarantee the rest of the frontend relies on.

---

## Section D — Blast radius (recommended option = Option 1)

Every file that would change, per layer:

**Engine layer — 0 files.**
`ModelRunner.tuned_params_` and `run_profile.json`'s `tuning` block already exist
(`runner.py:113,176,490–502`). Nothing to add.

**API layer — 4 code/doc files (+1 test):**
1. `docs/api_contract.md` — add the additive `result.tuning` block to the response section and a
   `1.1` additive note; leave the existing `1.0` field descriptions intact.
2. `backend/api/models.py` — add a `RunTuning` response model; add `tuning: RunTuning | None = None`
   to `RunResult`; bump `RunResponse.schema_version` default `"1.0"` → `"1.1"`.
3. `backend/api/routes/run.py` — add a `_tuning(runner)` helper (return `runner.run_profile_.get("tuning")`
   or assemble from `runner.tuned_params_`) and include it in `_build_result` (`run.py:94–105`).
4. `api_short_desc.md` — note the new field and the `1.1` bump.
5. *(test)* a backend API test asserting `result.tuning.best_params` is present after a tuned run
   (additive; not part of the locked contract doc itself).

**UI layer — 2 core files + host + fixtures/docs:**
1. `frontend/src/api/types.ts` — add a `RunTuning` interface and `tuning?: RunTuning | null` on
   `RunResult`.
2. **Host panel** — extend `frontend/src/pages/Overview.tsx` with a "Tuned hyperparameters" card
   (Overview already shows the run summary, the active configuration, and the per-model scoreboard,
   so it is the natural home; it reads `result.run` + `result.models` from the store today). *(If a
   dedicated page is preferred instead, that additionally touches the router in `frontend/src/App.tsx`
   and the sidebar nav — but a card on Overview is the lighter, recommended placement.)*
3. `frontend/src/test/fixtures/run_envelope*.json` + a render test (e.g. `resultPages.test.tsx`) —
   add a `tuning` block and assert it renders / is absent when tuning was off.
4. `frontend_short_desc.md` — document the panel.
5. `frontend/src/api/parse.ts` — **no change** (structural check is pass-through; optional key ignored).

**Schema-version bump — required, and how to do it additively:**
- **Required:** yes. Adding `result.tuning` is a response-shape change, so per CLAUDE.md and the
  contract header, bump `schema_version` `1.0` → `1.1`; never mutate the `1.0` fields in place.
- **Additive recipe:** ONLY add the new optional `result.tuning` block and change the envelope's
  `schema_version` default. Touch no existing field's name, type, or meaning.
- **Why it does not break the current frontend:**
  - The frontend doesn't read `tuning` today, so an extra key is inert for existing pages.
  - The response parser does **not** pin the version — it only checks `schema_version` is a string
    (`frontend/src/api/parse.ts:53`) — so `"1.1"` passes. The Overview badge simply renders whatever
    string it receives (`Overview.tsx:172`).
  - `assertResult` validates only the existing known keys (`parse.ts:29–41`); a new optional key is
    not rejected.
  - Old clients ignore the new field; updated clients read it. Backward- and forward-compatible.

---

### Summary

The tuned hyperparameters are fully produced by the engine (in memory and in
`run_profile.json`) but stop at the API response boundary — the locked `/run` envelope omits
them, so the dashboard never receives a typed tuning field. The clean fix is an **additive
`result.tuning` block** on the `/run` response (`schema_version` `1.0` → `1.1`), requiring **no
engine change**, a small serializer + model addition in the API, and a typed field + Overview
panel in the UI. The version bump is safe because the frontend parser is version-tolerant and
validates only existing keys. The artifact-scraping alternative (Option 2) avoids a contract
bump but introduces permanent untyped coupling and an extra fetch, and is not recommended.

_Read-only audit — no code or contract changed._
