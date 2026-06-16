# Reorganization Prompt — prompts/ structure, remove hook, rename short_desc, backfill Phase 7

> Not a phase. Repo housekeeping + doc correction. Archive at prompts/tooling/reorg.md (after the new structure exists).

---

Read CLAUDE.md and PROJECT_STATE.md first. Several housekeeping tasks. Do them in this
order. Do NOT modify any backend/classifyos pipeline code — this is docs/tooling/layout only.

## Task 1 — Remove the doc-update Stop hook

- Delete the Stop hook entry from `.claude/settings.json` (and the file if it now has no
  other settings, or leave an empty/clean settings file — your call, but the hook must not
  fire anymore).
- Delete `scripts/check_docs_updated.py`.
- Rationale to record: the hook could detect file changes but not ensure meaningful doc
  updates, and missed cases anyway (short_desc skipped after Phases 4 and 7). Doc-update
  discipline moves into the phase PROMPTS instead.

## Task 2 — Reorganize prompts/ into subfolders

Create these subfolders under prompts/ and move existing prompt files into them:
- `prompts/backend_phases/`   ← phase_01_skeleton.md … phase_07_runner.md
- `prompts/api_phases/`       ← (empty for now; api phase prompts go here)
- `prompts/frontend_phases/`  ← (empty for now)
- `prompts/tooling/`          ← tool_dev_run.md, tool_doc_hook.md, reorg (this prompt), the docs-backfill prompt if present
- `prompts/docs/`             ← doc_runbook.md and any other documentation-generation prompts
Use `git mv` so history is preserved. If a file's exact name differs, map by content.
Add a short `prompts/README.md` explaining the folder scheme so future prompts land in the
right place.

## Task 3 — Rename short_desc.md → backend_short_desc.md

- `git mv short_desc.md backend_short_desc.md`.
- Update every reference to `short_desc.md` across the repo (CLAUDE.md, PROJECT_STATE.md,
  plan_tweak.md, any prompt files, RUNBOOK.md) to `backend_short_desc.md`.
- Note the future plan in CLAUDE.md: there will also be `api_short_desc.md` and
  `frontend_short_desc.md` when those surfaces are built; each begins with a shared short
  "About ClassifyOS" header, then its own surface-specific summaries.

## Task 4 — Backfill the Phase 7 entry in backend_short_desc.md

It is currently missing (the Phase 7 session skipped it). Add the Phase 7 entry, accurate
to the actual code (check runner.py, plots.py, cli.py and git log):
- One-line overall summary of Phase 7.
- One line each for: ModelRunner (orchestrator, corrected order, _run_config isolation,
  robust per-algo failures), plot_results (plot1/2/3/5 + placeholder fallbacks),
  the CLI (inspect/run modes, load_dotenv), and the run outputs (the 4 data files + plots).
Keep the existing phase entries intact. Verify Phases 0–6 entries are all present; if any
earlier one is also missing, note it (don't silently skip).

## Task 5 — Update CLAUDE.md for the changes above

- Replace the `short_desc.md` references with `backend_short_desc.md`.
- Remove/replace any text stating that a hook enforces doc updates. Instead, under Working
  style, state clearly: "Doc updates are enforced via the phase prompts, not a hook. At the
  end of EVERY session that changes engine code, update PROJECT_STATE.md and
  backend_short_desc.md; update plan_tweak.md only if a real deviation/assumption occurred
  (do not invent entries)."
- Note the prompts/ subfolder scheme.
- Fix the stale CLI example if present (it referenced data/samples/lapse.csv; the real
  sample is policy_lapse.csv).

## Wrap-up

- Save this prompt to prompts/tooling/reorg.md.
- Update PROJECT_STATE.md (session log: reorg done, hook removed, short_desc renamed) and
  backend_short_desc.md (the Phase 7 backfill from Task 4 covers it).
- plan_tweak.md: no deviation here unless you find one; state "no scope deviation (repo
  housekeeping)".
- Commit as: "chore: reorg prompts/, remove doc hook, rename short_desc→backend_short_desc, backfill Phase 7 desc"

---

## Execution note (added at archive time, 2026-06-16)

- **Task 4 premise was outdated:** the Phase 7 entry (and the Phase 4 entry) were **already
  present and accurate** in `backend_short_desc.md`. They were verified against `runner.py`,
  `plots.py`, and `cli.py` rather than re-created — nothing was silently skipped.
- **Archived prompt files kept verbatim:** Task 3 says "any prompt files", but archived
  prompts are the immutable historical record of what was actually asked (CLAUDE.md
  governance), and this very prompt documents the `short_desc.md` → `backend_short_desc.md`
  rename, so editing it would be self-contradictory. References to `short_desc.md` were
  therefore updated only in the **living** docs (CLAUDE.md, PROJECT_STATE.md active sections,
  plan_tweak.md, backend_short_desc.md); the old flat `prompts/X.md` paths and `short_desc.md`
  mentions inside dated session-log rows and archived prompts are left as accurate history.
