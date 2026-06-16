# Tooling Prompt — Doc-Update Enforcement Hook (Claude Code Stop hook)

> Not a phase. Dev tooling / governance automation. Archive at prompts/tool_doc_hook.md.

---

Read CLAUDE.md first. Goal: make it mechanically impossible to finish a turn that changed
ML-engine code without also updating the living docs, while NOT nagging on doc-only,
test-only, or config-only turns. Implement this as a Claude Code Stop hook.

## Step 0 — verify, don't assume

Hook schemas are version-specific. Before writing anything:
- Run `claude --version` and report it.
- Locate and read the hooks reference for THIS installed version (the official docs and/or
  `claude` help for hooks). Confirm: the exact Stop event name, the settings.json nesting
  (event → matcher → handler), the stdin JSON shape, and the exit-code semantics
  (exit 2 / decision:"block" forces continuation; exit 0 allows stop).
- If anything below doesn't match the installed version's schema, ADAPT to the real schema
  and note what you changed. Do not invent fields.

## Step 1 — the check script

Create `scripts/check_docs_updated.py` (cross-platform, stdlib only):
- Determine changed files vs the last commit using:
  `git diff --name-only HEAD` (unstaged+staged tracked changes) plus
  `git diff --name-only --cached HEAD` and untracked via
  `git ls-files --others --exclude-standard`. Union them.
- Define:
  - ENGINE changed  = any path under `backend/classifyos/` (the pipeline sections).
  - DOCS changed    = `PROJECT_STATE.md` AND `short_desc.md` both present in the set.
  - TWEAK changed   = `plan_tweak.md` present.
- Logic:
  - If ENGINE changed and NOT (both required docs changed): exit code 2, print to STDERR
    a clear message naming which of PROJECT_STATE.md / short_desc.md is missing an update,
    and instruct: update them to reflect this session's changes, then finish.
  - Else: exit 0. Additionally, if ENGINE changed and NOT TWEAK changed, print to STDERR a
    NON-blocking reminder: "plan_tweak.md not updated — if this session deviated from the
    signed scope or made an assumption the plan didn't cover, add a row; if not, no action
    needed." (This is a reminder only; still exit 0.)
- Keep it dependency-free and fast (<1s). Handle "not a git repo" / git errors gracefully
  by exiting 0 (never block on tooling failure).

## Step 2 — register the Stop hook

In `.claude/settings.json` (project scope, committed), register a Stop hook that runs
`python scripts/check_docs_updated.py`. Use the matcher/handler shape the installed
version requires (verified in Step 0). Stop hooks have no tool matcher — they fire on
turn end. Ensure the command works on Windows (the user is on Windows/PowerShell) — invoke
via `python` and a repo-relative path; avoid bash-isms.

## Step 3 — prove it works

- Make a trivial change to a file under backend/classifyos/ (e.g. add a harmless comment),
  do NOT touch the docs, and trigger a stop — confirm the hook BLOCKS with the right
  message. Then update PROJECT_STATE.md + short_desc.md and confirm it now PASSES.
- Make a doc-only change (touch only short_desc.md) and confirm the hook does NOT block.
- Revert the throwaway comment afterward. Report the observed behavior for each case.

## Notes / guardrails

- Do NOT make plan_tweak.md a blocking condition (can't be judged mechanically; forcing it
  produces fake entries). Reminder-only, as above.
- Do NOT include CLAUDE.md in the check — it is the stable contract, not a per-session file.
- The hook enforces; the per-phase PROMPTS still ask Claude to actually write good updates.
  Mechanism + reasoning, not mechanism alone.

## Wrap-up

- Save this prompt to prompts/tool_doc_hook.md.
- Update PROJECT_STATE.md (note the hook now exists) and short_desc.md (one line:
  "doc-update enforcement hook added"). This itself satisfies the hook on this turn.
- Commit as: "tooling: Stop hook enforcing PROJECT_STATE + short_desc updates on engine changes"

---

## Implementation notes (filled in by the generating session, 2026-06-15)

- **Step 0 result:** `claude --version` → **2.1.177 (Claude Code)**. Hooks reference
  (code.claude.com/docs/en/hooks) confirmed the prompt's assumptions exactly: event name
  `Stop`; nesting `hooks → Stop → [ { hooks: [ { type:"command", command } ] } ]`; `Stop`
  takes **no matcher** (silently ignored if present, so it was omitted); stdin carries
  `session_id`/`transcript_path`/`cwd`/`hook_event_name`; **exit 2 prevents stopping and
  feeds STDERR back to Claude**, **exit 0 allows**. No schema deviations were needed.
- **One adaptation:** the non-blocking plan_tweak reminder uses an ASCII hyphen, not an
  em-dash — on the Windows (cp1252) console the em-dash garbled to `�` in hook STDERR.
  Wording is otherwise verbatim.
- **Step 3 observed behavior:** (A) engine edit, no docs → exit 2, message named BOTH
  PROJECT_STATE.md and short_desc.md → BLOCKS. (B) engine edit + both docs updated →
  exit 0, plan_tweak reminder printed. (C) doc-only change (engine reverted) → exit 0,
  no block. Throwaway comment in `backend/classifyos/__init__.py` reverted via
  `git checkout`.
