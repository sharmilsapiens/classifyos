# prompts/ — archived generation prompts (governance requirement)

Every generated section / phase / doc / tool is built from a prompt, and that exact prompt
is archived here in the same commit as the work it produced (CLAUDE.md governance rule).
This is the reproducibility record: given a prompt file you can re-derive (or audit) what
was generated.

## Folder scheme

| Folder | What lands here |
|---|---|
| `backend_phases/`  | ML engine phase prompts — `phase_01_skeleton.md` … `phase_NN_*.md` (Sections 1–16). |
| `api_phases/`      | FastAPI layer (Phase 8) prompts. Empty until that work starts. |
| `frontend_phases/` | React dashboard (Phase 9) prompts. Empty until that work starts. |
| `testing_phases/`  | Testing-phase prompts (Phase 10 browser E2E; Phase 11 integration). |
| `tooling/`         | Dev/tooling prompts not tied to a pipeline section (e.g. `tool_dev_run.md`, the prompt-reorg prompt). |
| `docs/`            | Documentation-generation prompts (e.g. `doc_runbook.md`). |

`.gitkeep` files hold the not-yet-used folders in version control so the structure is
visible before the first prompt lands.

## Where a new prompt goes

- Engine section/phase → `backend_phases/` as `phase_NN_<short_name>.md`.
- API or frontend work → `api_phases/` or `frontend_phases/`.
- A testing phase (E2E, integration, suite work) → `testing_phases/`.
- A documentation deliverable (RUNBOOK-style) → `docs/`.
- A dev tool, hook, or repo-housekeeping task → `tooling/`.

Keep the original prompt text verbatim — these files are the historical record of what was
actually asked, not living docs.
