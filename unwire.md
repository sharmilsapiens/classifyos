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
