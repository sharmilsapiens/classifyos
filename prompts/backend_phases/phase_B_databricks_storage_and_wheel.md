# Phase B (Steps 1 & 2) — DatabricksVolumeStorage + wheel packaging

> Archived generation prompt (governance requirement). Verbatim task given to Claude Code on
> 2026-07-14. Produced: `DatabricksVolumeStorage` + the updated `get_default_storage()` in
> `classifyos/io/storage.py`, the new `CLASSIFYOS_STORAGE_BACKEND`/`DBRICKS_INPUT_VOLUME`/
> `DBRICKS_OUTPUT_VOLUME` entries in `backend/.env.example`, `tests/test_storage.py`, the new
> `backend/pyproject.toml` (wheel build metadata), the `dist/`/`build/` `.gitignore` entries, and
> the doc updates (`docs/databricks_integration.md` status table, PROJECT_STATE.md,
> backend_short_desc.md). Additive/opt-in — a local run with no new env vars set is byte-identical
> to before; no engine section modified; no `/api/v1/run` contract change. Reference spec:
> `ClassifyOS_Databricks_Enhancement_Guide.md` Enhancements 1 and 4a. Steps 4 (Delta input
> source) and 5 (cluster notebook) are out of scope (need cluster access). Companion to
> Phase A (`phase_A_mlflow_logging.md`) and Interim 2a/2b.
>
> Two corrections to the reference guide were made during implementation and hallucination-checked
> against the installed toolchain (governance requirement):
> 1. `build-backend` — the guide's `setuptools.backends.legacy:build` does not exist (import
>    fails); corrected to the real `setuptools.build_meta` (verified: exposes `build_wheel`).
> 2. Wheel `dependencies` — the guide's list omitted `openai` and `psycopg2-binary`, which are
>    engine (`classifyos`) runtime deps in requirements.txt (lazy-imported by `analysis/llm_explain.py`
>    and the Postgres path of `io/sql_source.py`); both added so the wheel deps match the "ML engine"
>    section of `backend/requirements.txt` exactly.

---

Implement Steps 1 and 2 of the Databricks I/O integration plan documented in docs/databricks_integration.md §6.6. Both steps are locally testable — no cluster access needed.

## Step 1 — DatabricksVolumeStorage in backend/classifyos/io/storage.py

Add DatabricksVolumeStorage as a thin subclass of LocalFolderStorage after the existing class. Unity Catalog volumes expose POSIX paths (/Volumes/<catalog>/<schema>/<vol>/...) that work with plain Python open() — so this adapter is LocalFolderStorage with its two roots pointed at volume paths from env vars.

Constructor resolution order (pick first that is set):
1. data_dir / output_dir passed directly to __init__
2. DBRICKS_INPUT_VOLUME / DBRICKS_OUTPUT_VOLUME env vars
3. Fall back to DATA_DIR / OUTPUT_DIR (existing defaults)

Then update get_default_storage() to select DatabricksVolumeStorage when:
- CLASSIFYOS_STORAGE_BACKEND=databricks is set, or
- DBRICKS_INPUT_VOLUME is present and CLASSIFYOS_STORAGE_BACKEND is not explicitly set to something else

Local runs with neither env var set must continue to get LocalFolderStorage — no behaviour change whatsoever.

New env vars to document in backend/.env.example:
CLASSIFYOS_STORAGE_BACKEND=databricks
DBRICKS_INPUT_VOLUME=/Volumes/main/classifyos/data/input
DBRICKS_OUTPUT_VOLUME=/Volumes/main/classifyos/data/output

The full implementation spec (class docstring, constructor, updated get_default_storage) is in ClassifyOS_Databricks_Enhancement_Guide.md Enhancement 1 — use it as the reference, hallucination-check any calls against the installed versions.

Local test: set DBRICKS_INPUT_VOLUME to any existing local folder (e.g. DATA_DIR's value) — get_default_storage() must return a DatabricksVolumeStorage instance and a real run must complete identically to before.

Write a unit test in backend/tests/ that:
- Verifies get_default_storage() returns LocalFolderStorage when no Databricks env vars are set
- Verifies it returns DatabricksVolumeStorage when CLASSIFYOS_STORAGE_BACKEND=databricks is set
- Verifies it returns DatabricksVolumeStorage when only DBRICKS_INPUT_VOLUME is set
- Verifies the resolved paths are correct in each case
Use monkeypatch to set/clear env vars — no real filesystem or cluster needed.

## Step 2 — Wheel packaging (backend/pyproject.toml)

Create backend/pyproject.toml with build metadata so the engine can be packaged as a .whl. The engine is already a proper Python package — this is purely build tooling, no engine code changes.

Use the spec in ClassifyOS_Databricks_Enhancement_Guide.md Enhancement 4a as the reference for the [project] dependencies list — cross-check every package name and version range against the pinned versions in backend/requirements.txt to make sure they are consistent (hallucination-check requirement).

After creating pyproject.toml, verify the wheel builds cleanly:
cd backend/
pip install build
python -m build --wheel
The wheel must build without errors and the output dist/classifyos-*.whl must exist. Do not commit the dist/ folder — add it to .gitignore if not already there.

No new tests needed for the build tooling itself, but confirm the existing test suite still passes after adding pyproject.toml.

## Scope boundary
Do not implement the Delta table input source (Step 4) or the notebook (Step 5) — those need cluster access. Do not touch the FastAPI layer or any API routes. Do not modify any existing engine sections.
