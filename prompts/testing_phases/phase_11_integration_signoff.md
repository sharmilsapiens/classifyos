# Phase 11 — Integration, multilabel, performance & governance sign-off (FINAL phase)

> Paste into a fresh Claude Code session in the ClassifyOS repo.
> This is the LAST phase of the sprint. When its work is done and the human sign-offs/demo
> happen, ClassifyOS v1.0 is released.

---

## 0. Read first (in this order)

- `CLAUDE.md` — stable contract, hard rules, the 7 use cases.
- `PROJECT_STATE.md` — live status: Phase 10 done; **184 pytest + 62 vitest + 4 Playwright E2E
  green**; read the **"Testing debt / untested paths"** section — its remaining (un-struck)
  items are this phase's agenda.
- `PROJECT_WISDOM.md` — lessons learned; esp. "real data is messy", the multilabel weak spots,
  the bounded-by-default tuning lesson, and the sync-`/run` timeout note.
- `plan_tweak.md` — existing deviations, esp. #19 (multilabel resampling → class_weight),
  and the multilabel/threshold scope notes.
- `docs/api_contract.md` — the LOCKED contract; multilabel must render against it honestly.
- `RUNBOOK.md` / `API_RUNBOOK.md` — run flows; the perf run uses the CLI/engine.
- The Phase 10 E2E: `frontend/e2e/` + `playwright.config.ts` + the `USE_CASES` parametrization
  (built to be extended to all 7 use cases — that's the point this phase).
- `scripts/generate_sample_data.py` — how the synthetic samples are made (extend for 10k + the
  multilabel set).

The person directing this is **new to web/testing**. New code/tests teach as they go.

---

## 1. What this phase is

Close the sprint. Four workstreams:
1. **7-use-case end-to-end sweep** — drive all seven insurance use cases through the Phase 10
   E2E machinery and confirm each produces its artifacts and renders across the dashboard.
2. **Multilabel's first real run** — Product Recommendation has NEVER run end-to-end; make it
   work honestly (sanctioned bug-fixing allowed — see §3).
3. **Performance baseline** — verify `ModelRunner.run()` on a 10k+ row synthetic dataset.
4. **Governance dossier** — assemble the evidence + checklist that lets the humans sign off
   (Claude Code prepares it; the actual review/demo/signatures are human acts).

---

## 2. Frozen vs sanctioned (READ CAREFULLY — this phase loosens the freeze, narrowly)

- **Normally frozen:** binary + multiclass engine behavior, the API, the contract, the frontend.
  These MUST keep working — the existing 184+62+4 suite stays green at all times.
- **SANCTIONED EDITABLE SURFACE — multilabel only.** You MAY edit engine/frontend code **solely
  to make the multilabel path work end-to-end** (e.g. multilabel resampling handling, per-label
  metric/curve/confusion shaping, the frontend's defensive multilabel rendering). Constraints on
  any such edit:
  - It must NOT change binary or multiclass behavior (prove it: the full existing suite stays
    green after every change).
  - Each fix gets an inline `[RISK]`/explanatory comment, a regression test, and a `plan_tweak.md`
    row.
  - It stays ADDITIVE where possible (new branch/module over rewriting a shared path).
- **Scope boundary (do not cross):** "make multilabel work" = **runs end-to-end and renders
  honestly WITH its already-documented limitations** (per-label thresholds out of scope;
  resampling → class_weight fallback, plan_tweak #19). It does NOT mean full multilabel feature
  parity. If multilabel turns out to need genuinely out-of-scope work to be useful, STOP, document
  it as a v1.x item, and ship v1.0 honest about the limitation — do NOT expand scope on the final
  day. Surface that judgment call in the report.
- The LOCKED contract does not change. If multilabel needs a contract field that doesn't exist,
  STOP and flag it (it's a 1.1 discussion), don't patch.

---

## 3. Workstream 2 — multilabel (do this early; it's the highest-risk item)

- Ensure a **multilabel sample dataset** exists (Product Recommendation, multi-hot target).
  Extend `scripts/generate_sample_data.py` if needed — synthetic, with real multi-label
  structure (rows carrying several labels). Keep it out of git like the other data.
- Run it end-to-end **via the CLI/engine first** (fastest feedback), then **via the API**, then
  **through the browser E2E**. At each layer, fix what breaks — within the §2 boundary.
- Known weak spots to expect (from the docs): resampling falls back to `class_weight`
  (verify the warning + that it doesn't crash); `predict_proba` shape for multilabel; per-class
  one-vs-rest curves/calibration (calibration may be a placeholder); confusion matrix per label;
  the predictions table shape. Make each render honestly or show a clear "preliminary / not
  applicable for multilabel" state — never a crash, never a silent wrong number.
- Add multilabel regression tests at the layer each bug was found (pytest for engine/API,
  vitest/Playwright for frontend). Capture a multilabel `/run` envelope fixture so future render
  tests don't need a live multilabel run.

---

## 4. Workstream 1 — the 7-use-case E2E sweep

- Extend the Phase 10 `USE_CASES` list (the spec was built parametrized for this) to all seven:
  Policy Lapse, Claim Likelihood, Fraud Detection (binary); Risk Tier, Customer Segment,
  Claim Severity (multiclass); Product Recommendation (multilabel).
- For each: upload → configure → run → assert the 11 artifacts are produced and the dashboard
  pages render (Overview KPIs, ROC/PR with the right curve count, confusion heatmap, class
  report, predictions banner, feature impact, interactions). Multilabel asserts the honest
  states from §3.
- Some use cases may need synthetic datasets that don't exist yet (Claim Likelihood, Customer
  Segment, Claim Severity) — generate them via the sample-data script (synthetic, constructed
  signal, kept out of git). Document which datasets back which use case.
- Log any per-use-case issue; fix multilabel ones per §2; for binary/multiclass surprises, STOP
  and report (those paths are frozen + already green — a failure there is a real regression to
  surface, not silently patch).

---

## 5. Workstream 3 — performance baseline

- Generate a **synthetic 10k+ row dataset** (extend the sample-data script). Note real insurance
  data has NOT arrived — real-data revalidation stays a documented post-v1.0 item (plan_tweak #5).
- Time `ModelRunner.run()` on it (CLI, a representative algorithm set, tuning OFF) and record the
  wall-clock against the scope's "< 5 min on a standard laptop" target. Report the actual number;
  if it exceeds 5 min, document it honestly as a known characteristic + the contributing factors
  (which don't block v1.0 — they inform the v1.5 background-job path).
- Optionally note the sync-`/run` + gateway-timeout interaction at this size (tie to the v1.5
  background-job item) — don't fix it (out of scope), just measure/observe.
- A realistic **tuning** sanity run (one model, real-ish budget e.g. 25–30 trials) to confirm the
  hard per-model timeout actually bounds it and the run completes — not a full tuning sweep.

---

## 6. Workstream 4 — governance dossier (Claude Code PREPARES; humans SIGN)

Claude Code cannot sign off, demo, or collect signatures — those are human acts by Naveen +
the stakeholders. What it CAN do is assemble the package that makes that review fast and
credible. Produce a single dossier doc (e.g. `docs/governance_signoff_v1.0.md`) containing:
- **The scope §12 governance checklist** with current status + the EVIDENCE for each:
  - Prompt version control → list the archived prompts under `prompts/**`.
  - Section-level unit tests on real data → the suite counts + what each covers.
  - **[RISK]-comment review** → a table of every `[RISK]` comment in the codebase (file +
    one-line summary) for the team lead to walk and check off.
  - **Leakage audit** → point to the specific tests that enforce train-only fitting (the
    leakage suite, the "test set never passed" structural checks) so the auditor sees the proof,
    not just a claim.
  - Output schema contract locked → `docs/api_contract.md` schema_version 1.0.
  - Hallucination check → the per-phase version verifications already recorded.
  - **Per-phase sign-off (Naveen)** + **final demo** (Amit Shah, DharaniKiran Kavuri,
    Matat Rotbaum) → leave these as explicit unchecked human action items.
- **A short demo script** — the click-through that shows the system working end-to-end
  (start servers → upload → configure → run → tour the result pages → show an artifact), so the
  stakeholder demo is repeatable.
- **An honest v1.0 limitations list** (consolidated from plan_tweak): synthetic-data metrics
  pending real-data revalidation; multilabel preliminary (with whatever §3 concluded); sync
  `/run` gateway-timeout (v1.5 background jobs); `/explain` stub (v2.0 persistence); outputs
  overwritten per run. This is the "what a reviewer must know at sign-off" summary.

---

## 7. Hard rules

- The existing 184 pytest + 62 vitest + 4 E2E suites stay GREEN throughout. Run them after every
  change. A multilabel fix that breaks a binary/multiclass test is not done.
- Only multilabel is editable, narrowly, per §2. Binary/multiclass/API/contract are frozen — a
  failure there is a regression to REPORT, not patch.
- No contract changes. Synthetic data only; throwaway `OUTPUT_DIR`; CORS never `["*"]`.
- Don't expand scope on the last day. Documented honest limitation > rushed half-feature.
- Governance: prepare evidence; never self-certify a human sign-off.

---

## 8. WRAP-UP BLOCK (mandatory — do all of it)

1. **Archive this prompt** to `prompts/testing_phases/phase_11_integration_signoff.md` (verbatim),
   committed with the work.
2. **Update `PROJECT_STATE.md`:** flip Phase 11 → ✅ (engineering complete); "Completed this
   session (Phase 11)" entry (7-use-case sweep results, multilabel outcome + any fixes, perf
   number, tuning sanity result, dossier produced); strike the now-closed "Testing debt" items
   and clearly mark what remains as HUMAN sign-off actions (not code); final test counts;
   session-log row. Set status to "v1.0 ready for sign-off/demo" — NOT "released" (release is the
   human sign-off + tag).
3. **Update `plan_tweak.md`** for every real multilabel fix + the multilabel scope conclusion +
   the perf result if it deviates from the < 5 min target. Don't pad.
4. **Update the relevant `*_short_desc.md`** for any multilabel behavior change (engine →
   backend_short_desc; API → api_short_desc; frontend → frontend_short_desc).
5. **Produce `docs/governance_signoff_v1.0.md`** (the §6 dossier).
6. **Hallucination check (governance):** verify any newly used library calls against installed
   versions; re-confirm the suites' frameworks. Record versions in the PROJECT_STATE entry.
7. **Commit message:**
   `Phase 11: 7-use-case E2E sweep + multilabel end-to-end + 10k perf baseline + governance dossier — v1.0 ready for sign-off`

When done, report: the 7-use-case sweep result (which passed, which needed work), the multilabel
outcome (what broke, what you fixed within scope, what's documented as a limitation), the perf
number vs the 5-min target, the tuning sanity result, the dossier location, the final test
counts (all green), and a clear statement of exactly what HUMAN actions remain before v1.0 is
released (Naveen per-phase sign-off, [RISK] + leakage review, the stakeholder demo, signatures,
repo tag v1.0).
