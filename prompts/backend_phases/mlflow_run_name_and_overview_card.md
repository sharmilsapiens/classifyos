# MLflow follow-ups — meaningful default run name (engine) + Overview MLflow card (frontend)

> Archived generation prompt (governance requirement). Two small, additive follow-ups to the
> MLflow work (Phase A / Interim 2a, both merged). Session date: 2026-07-08.

Two small, additive follow-ups to the MLflow work (Phases A/2a are merged; MLflow logging +
Postgres backend + Runs view exist; `result.mlflow` was added in schema 1.9). Read
`docs/databricks_integration.md` §6/§6.5 for context. Neither should change the locked `/run`
schema.

## 1. Meaningful default MLflow run name (engine).
Currently `ModelRunner._log_to_mlflow` forwards `mlflow.run_name` from config, which is unset by
default → MLflow auto-generates a whimsical name ("capable-fox-123") that reads as random in the
Runs view. Default it to something meaningful — e.g. `"<target> · <YYYY-MM-DD HH:MM>"` (target +
run timestamp) — only when the config didn't supply a `run_name` (an explicit `mlflow.run_name`
must still win). Reuse the run's existing timestamp if one is already computed (the run profile
has one) rather than adding a new clock source where avoidable. This changes only the MLflow
run's display name (surfaced via the `mlflow.runName` tag the Runs view already reads) — it must
NOT touch the id-based artifact folder names or the Postgres→file mapping. Pure datetime/stdlib;
no new dependency.

## 2. Surface the result.mlflow block in the dashboard (frontend).
The API already returns `result.mlflow` (`{run_id, experiment_id, tracking_uri, models: {name:
uri}}`) when MLflow logging was on, but no page shows it. Add a small, read-only MLflow card on
the Overview result page (or the most natural existing result surface): the run id, the tracking
store URI, how many models were logged, and the per-model model URIs. It must degrade gracefully
— render nothing (or a subtle "MLflow logging was off" note) when `result.mlflow` is null, so a
non-MLflow run is unchanged. Frontend-only; no API/contract change. Reuse existing card/typography
components; the `MlflowInfo` TS type already exists from 1.9 (add it if missing).

## Scope guard
Additive only. No `schema_version` bump (run_name is internal to the MLflow record; `result.mlflow`
already shipped in 1.9). Do NOT touch the deferred Databricks phases or the `/explain` wiring.

When done: run the relevant tests and make sure they pass (add an engine test for the run-name
default + the config-override-wins case, and a frontend test for the MLflow card rendering when
present / absent when null), then update PROJECT_STATE.md and the appropriate short_desc file(s).
Update plan_tweak.md only if this genuinely deviated from the plan — this is additive polish, so
most likely no entry. Do a hallucination check on any library calls against the installed versions.
Archive this session's generation prompt under prompts/ (per CLAUDE.md) in the same commit as the
code.
