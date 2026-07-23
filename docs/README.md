# ClassifyOS — Documentation

GenAI-developed ML classification framework for the insurance domain (Sapiens · AI/ML Data):
React frontend → FastAPI backend → pure-Python ML engine.

This folder is the map for the whole project. Start with **Getting started**, then jump to what
you need. Live project status lives at the repo root: [`PROJECT_STATE.md`](../PROJECT_STATE.md).

---

## 🚀 Getting started
- [getting-started/FIRST_RUN.md](getting-started/FIRST_RUN.md) — set the app up from scratch on a new machine.
- [getting-started/RUN_FULL_SYSTEM.md](getting-started/RUN_FULL_SYSTEM.md) — run the full system (website + API) together.

## 🛠️ Operating (runbooks)
- [runbooks/RUNBOOK.md](runbooks/RUNBOOK.md) — operator's manual for the CLI / `ModelRunner`.
- [runbooks/API_RUNBOOK.md](runbooks/API_RUNBOOK.md) — operator's manual for the FastAPI layer.

## 📦 Deployment (AKS)
- `deployment/deploy.md` — Azure Kubernetes Service deploy guide *(added together with the Docker/K8s files)*.

## ☁️ Databricks
- [databricks/ClassifyOS_Databricks_Enhancement_Guide.md](databricks/ClassifyOS_Databricks_Enhancement_Guide.md) — storage & compute enhancement guide.
- [databricks_integration.md](databricks_integration.md) — integration design & phased roadmap. *(pinned at docs/ root — code-referenced)*
- [databricks_how_it_works.md](databricks_how_it_works.md) — how the Databricks path works end to end.
- [databricks_api_contract.md](databricks_api_contract.md) — FastAPI ↔ Databricks contract additions.
- [databricks_wisdom.md](databricks_wisdom.md) — wisdom & gotchas. *(pinned at docs/ root — code-referenced)*
- [enabling_parallelization.md](enabling_parallelization.md) — parallel execution on Azure + Databricks.

## 📖 Reference
- [api_contract.md](api_contract.md) — **LOCKED** `/api/v1/run` request/response schema. *(pinned at docs/ root — code-referenced)*
- [reference/backend_short_desc.md](reference/backend_short_desc.md) — plain-language build summary (ML engine).
- [reference/api_short_desc.md](reference/api_short_desc.md) — plain-language API-surface summary.
- [reference/frontend_short_desc.md](reference/frontend_short_desc.md) — plain-language frontend-surface summary.
- [reference/data_profile.md](reference/data_profile.md) — sample-data profiling / logic notes.

## ✅ Governance & audits
- [governance_signoff_v1.0.md](governance_signoff_v1.0.md) — v1.0 governance sign-off dossier.
- [tuning_audit.md](tuning_audit.md) — hyperparameter search-space audit.
- [tuned_params_path_audit.md](tuned_params_path_audit.md) — tuned-params data path audit (engine → API → UI).

## 🐞 Tracking
- [reference/bugs.md](reference/bugs.md) — known bugs.
- [reference/unwire.md](reference/unwire.md) — unwired-features registry.

## 📌 Live status (repo root)
- [../PROJECT_STATE.md](../PROJECT_STATE.md) — current progress, decisions, known issues, next steps.
- [../plan_tweak.md](../plan_tweak.md) — plan deviation & assumption register.

---

> **Why some files sit at the `docs/` root instead of a subfolder:** `api_contract.md`,
> `databricks_integration.md`, and `databricks_wisdom.md` are referenced by path from source
> code (docstrings/comments). They are intentionally kept at stable paths so those references
> stay valid.
>
> `CLAUDE.md` (Claude Code context) stays at the repo root by convention.
