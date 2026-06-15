#!/usr/bin/env python3
"""Stop-hook guard: block finishing a turn that changed ML-engine code without
also updating the living docs.

Governance rule (CLAUDE.md working style): any change under backend/classifyos/
(the pipeline "sections") must be reflected in PROJECT_STATE.md AND short_desc.md
in the same session. plan_tweak.md is a reminder only — it cannot be judged
mechanically, so forcing it would produce fake entries.

Contract with the Claude Code Stop hook (verified against v2.1.177):
  exit 2  -> Claude is prevented from stopping; stderr is fed back as the reason.
  exit 0  -> Claude may finish. Any stderr is shown as a non-blocking notice.

Dependency-free (stdlib only), cross-platform, fast (<1s). Any git/tooling
failure exits 0 — we never block the user on our own breakage.
"""

from __future__ import annotations

import subprocess
import sys

# --- classification rules ---------------------------------------------------
ENGINE_PREFIX = "backend/classifyos/"          # the pipeline sections
REQUIRED_DOCS = ("PROJECT_STATE.md", "short_desc.md")  # both must be updated
TWEAK_DOC = "plan_tweak.md"                     # reminder only, never blocking


def _git(*args: str) -> list[str]:
    """Run a git command, return stripped non-empty output lines.

    Raises CalledProcessError / FileNotFoundError on git failure so the caller
    can decide to fail open.
    """
    out = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def changed_files() -> set[str]:
    """Union of tracked changes (staged + unstaged vs HEAD) and untracked files.

    git reports POSIX-style, repo-root-relative paths on every platform, so the
    prefix/name checks below are OS-agnostic.
    """
    files: set[str] = set()
    files.update(_git("diff", "--name-only", "HEAD"))          # staged + unstaged
    files.update(_git("diff", "--name-only", "--cached", "HEAD"))  # staged
    files.update(_git("ls-files", "--others", "--exclude-standard"))  # untracked
    return files


def main() -> int:
    try:
        files = changed_files()
    except Exception:
        # Not a git repo, git missing, no HEAD yet, etc. Never block on tooling.
        return 0

    engine_changed = any(f.startswith(ENGINE_PREFIX) for f in files)
    if not engine_changed:
        return 0  # doc-only / test-only / config-only turn — nothing to enforce.

    missing_docs = [d for d in REQUIRED_DOCS if d not in files]
    if missing_docs:
        names = " and ".join(missing_docs)
        print(
            "ML-engine code under {prefix} changed this session, but the living "
            "docs were not updated to match.\n"
            "Missing update(s): {names}.\n"
            "Update {names} to reflect this session's engine changes "
            "(what changed, decisions, next steps for PROJECT_STATE.md; the "
            "one-line phase summary for short_desc.md), then finish.".format(
                prefix=ENGINE_PREFIX, names=names
            ),
            file=sys.stderr,
        )
        return 2

    # Required docs satisfied. Nudge on plan_tweak.md without blocking.
    if TWEAK_DOC not in files:
        print(
            "plan_tweak.md not updated - if this session deviated from the signed "
            "scope or made an assumption the plan didn't cover, add a row; if not, "
            "no action needed.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
