# ClassifyOS — Unwired Features Registry

> A living log of features that have been **temporarily disabled but NOT deleted** from the
> pipeline. Each entry records, in order: a one-line summary of what was removed, a short
> description of how it was unwired, and the exact steps to wire it back. Nothing listed here
> is gone — every entry is fully reversible. Append a new section per feature as features are
> unwired; never delete an entry, mark it **Restored** with a date instead.

---

## 1. Section 7B — Interaction Features

**One-line:** Temporarily removed Section 7B pairwise interaction features from training and hid
them from the dashboard (engine force-disabled + four UI spots commented out); nothing deleted.

**Status:** Unwired 2026-06-25 (commit `7b592f8`) · still unwired.

### Short description

By owner request, Section 7B interaction features were taken out of the active pipeline:

- **Engine** (`backend/classifyos/runner.py`, `ModelRunner._engineer`): a single line force-disables
  `interaction_features` on the deep-copied run config regardless of what the incoming request asks.
  `InteractionFeatureBuilder` then short-circuits (no pairs discovered, `transform` returns a copy),
  so `result.run.interaction_cols` comes back **empty** and `plot6_interaction_summary.png` is no
  longer written. The LOCKED schema 1.0/1.1 is **unchanged** — `interaction_cols` still exists, it is
  just `[]`.
- **UI** (commented out, files left intact and unreferenced for a trivial restore):
  - `frontend/src/pages/Configure.tsx` — the "Interaction features" config `<Card>` (and its now-unused
    `FILL` const).
  - `frontend/src/lib/nav.ts` — the sidebar nav entry (and its now-unused `Combine` icon import).
  - `frontend/src/App.tsx` — the `/interactions` route + `Interactions` page import; `/interactions`
    now redirects to `/` via `<Navigate to="/" replace />`.
  - `frontend/src/pages/Interactions.tsx` and the `results.ts` decoders are **left intact** but
    unreferenced.
- **Tests** updated to match: `test_runner.py` (no `_x_`/`_minus_` interaction cols, plot6 absent),
  `test_use_case_sweep.py` (plot6 dropped from the expected artifact set → 10).

**Caveat (pre-existing, unchanged):** the API's `interaction_cols` heuristic still matches the `_div_`
marker, which is ALSO used by Section 7 `FeatureBuilder` ratio features — so when
`feature_engineering.ratios` is on, a ratio column like `a_div_b` can still surface in
`interaction_cols`. This is pre-existing marker imprecision, harmless now that the Interactions page
is hidden.

### How to wire back

Easiest path is to revert the commit:

```bash
git revert 7b592f8
```

Or restore manually:

1. **Engine** — in `backend/classifyos/runner.py::ModelRunner._engineer`, delete the force-disable line:
   ```python
   cfg["interaction_features"] = {**cfg.get("interaction_features", {}), "enabled": False}
   ```
   and restore the unconditional plot6 call (remove the `if ib.enabled_ and ib.interaction_cols_:`
   guard so `plot_interaction_summary(...)` runs in its original `try/except`).
2. **UI** — uncomment the four blocks:
   - `Configure.tsx`: the "Interaction features" `<Card>` and the `FILL` const.
   - `nav.ts`: the `Combine` import and the `/interactions` nav item.
   - `App.tsx`: the `import Interactions from "@/pages/Interactions"` line and the
     `<Route path="/interactions" element={<Interactions />} />`; delete the `Navigate` redirect route.
3. **Tests** — revert the edits in `test_runner.py` (re-assert `_x_`/`_minus_` cols + plot6 present)
   and `test_use_case_sweep.py` (expected artifact count back to 11).
4. Run `pytest tests/ -v` (backend) and `tsc -b` / `npm run build` (frontend) to confirm green.
5. Update `PROJECT_STATE.md` and this file: mark entry #1 **Restored** with the date.

---

## 2. Section 7 — Feature Engineering (derived features)

**One-line:** Temporarily removed Section 7 derived features (ratios / binning / polynomial)
from training and hid the "Feature engineering" config card; nothing deleted. The separate
user-defined Feature Builder panel is **unaffected** and stays visible.

**Status:** Unwired 2026-06-26 · still unwired.

### Short description

By owner request (pre-demo), Section 7 `FeatureBuilder` derived features were taken out of the
active pipeline:

- **Engine** (`backend/classifyos/runner.py`, `ModelRunner._engineer`): a single line force-disables
  `feature_engineering` on the deep-copied run config regardless of what the incoming request asks
  (mirroring the Section 7B interaction unwiring in the same method). `FeatureBuilder` then
  short-circuits — `fit` builds nothing (`created_features_` stays empty) and `transform` returns a
  copy — so no `_sq` / `_div_` / `_bin` columns enter `active_features`. Section 7 writes **no plot
  or CSV** of its own, so no artifact disappears. The LOCKED schema is **unchanged** — `active_features`
  still exists, it just contains fewer columns.
- **UI** (commented out, files/fields left intact for a trivial restore):
  - `frontend/src/pages/Configure.tsx` — the "Feature engineering" config `<Card>` (the `fe_enabled`
    / ratios / binning / polynomial switches + max-poly field). The `fe_*` fields remain in
    `ConfigFormState`/`buildPayload` and the form defaults are unchanged (`fe_enabled: true`), so the
    payload still carries them and the engine overrides — exactly the Section 7B pattern.
- **Results:** nothing visible to change. The only result field touched is `active_features`, whose
  sole frontend consumer is the already-hidden `Interactions.tsx`. The `"Feature engineering"` entry
  in `Overview.tsx`'s `PIPELINE_STAGES` run-progress list is **left as-is** (consistent with entry #1,
  which left `"Interaction features"` in the same list — a transient label, not a control).
- **Tests:** `test_runner.py`'s end-to-end assertion was tightened to also forbid `_div_` markers (no
  ratio columns now). `test_features.py` exercises `FeatureBuilder` **directly** (not via the runner
  force-disable) so it stays green and untouched. No other test asserts engineered columns via the runner.

### How to wire back

1. **Engine** — in `backend/classifyos/runner.py::ModelRunner._engineer`, delete the force-disable line:
   ```python
   cfg["feature_engineering"] = {**cfg.get("feature_engineering", {}), "enabled": False}
   ```
2. **UI** — uncomment the "Feature engineering" `<Card>` in `Configure.tsx`.
3. **Tests** — revert the `test_runner.py` assertion to forbid only `"_x_"`/`"_minus_"` (drop the
   `"_div_"` clause) so Section 7 ratio columns are allowed again.
4. Run `pytest tests/ -v` (backend) and `tsc -b` / `npm run build` (frontend) to confirm green.
5. Update `PROJECT_STATE.md` and this file: mark entry #2 **Restored** with the date.

---

## 3. Explainability (single-row SHAP) page

**One-line:** Temporarily hid the "Explainability" Results page from the dashboard (nav entry +
route commented out, stale links redirect to Overview) because the backend explanation is not yet
implemented; nothing deleted.

**Status:** Unwired 2026-06-28 · still unwired.

### Short description

The Explainability page was always a **v1.0 stub** — the API is stateless and has no model
registry, so `/explain` returns a structured `status:"unavailable"` payload and real single-row
SHAP is deferred to v2.0 (model persistence / MLflow). By owner request it is now hidden from the
UI until the backend explanation actually lands, so users aren't shown a feature that can't produce
a result. **This is UI-only** — no engine or API code changed; the `/api/v1/explain` endpoint and
its stub response are untouched, as is the typed `explain` client and `ExplainResponse` type.

- **UI** (commented out, files/types left intact and unreferenced for a trivial restore):
  - `frontend/src/lib/nav.ts` — the `/explainability` nav `NavItem` (and its now-unused `Lightbulb`
    icon import).
  - `frontend/src/App.tsx` — the `import Explainability from "@/pages/Explainability"` line and the
    `<Route path="/explainability" element={<Explainability />} />`; `/explainability` now redirects
    to `/` via `<Navigate to="/" replace />` (same pattern as the hidden `/interactions` route).
  - `frontend/src/pages/Explainability.tsx` is **left intact** but unreferenced by the nav/router.
- **Left as-is (intentional):** `frontend/src/pages/SetupGuide.tsx` still documents the
  `/api/v1/explain` endpoint and its "v2.0 stub" limitation — that is accurate API reference for an
  endpoint that still exists, not the hidden UI feature (consistent with entry #2 leaving the
  Overview pipeline-stage label alone). The `explain` client / `ExplainResponse` type / the engine's
  `/explain` route are unchanged.
- **Tests** updated to match (`frontend/src/pages/referencePages.test.tsx`): the nav-count assertion
  `13 → 12`, and the "reference pages as real routes" test now asserts `/explainability` is **not**
  in the nav paths. The `describe("Explainability (v1.0 stub)")` block still renders the
  `<Explainability />` component **directly** (component intact), so it stays green and untouched.

### How to wire back

1. **UI** — uncomment the three blocks:
   - `nav.ts`: the `Lightbulb` import and the `/explainability` nav item.
   - `App.tsx`: the `import Explainability from "@/pages/Explainability"` line and the
     `<Route path="/explainability" element={<Explainability />} />`; delete the `Navigate` redirect
     route for `/explainability`.
2. **Tests** — in `referencePages.test.tsx`, revert the nav-count assertion to `13`, restore
   `expect(paths).toContain("/explainability")`, and drop the `not.toContain` line.
3. Run `tsc -b` / `npm run build` and `npx vitest run` (frontend) to confirm green.
4. Update `PROJECT_STATE.md` and this file: mark entry #3 **Restored** with the date.

> When the **backend** explanation is implemented, that is a separate (v2.0) piece of work — fill in
> the real `method` / `shap_values` / `base_value` on the `/explain` response and swap
> `Explainability.tsx`'s `<WaterfallPlaceholder>` for the real Recharts waterfall; this entry only
> covers re-showing the page in the nav.
