# ClassifyOS

GenAI-developed ML classification framework for the insurance domain (Sapiens · AI/ML Data).
Predicts categorical outcomes from structured tabular data: **binary, multiclass, multilabel**.

**React frontend → FastAPI backend → pure-Python ML engine.** Config is set in the browser,
POSTed to FastAPI, executed by the ML engine; JSON results stream back and populate charts/tables.

## 📚 Documentation

All docs live in **[`docs/`](docs/README.md)** — open the **[documentation index](docs/README.md)** first; it's the map for the whole project.

Quick links:
- **New here?** → [docs/getting-started/FIRST_RUN.md](docs/getting-started/FIRST_RUN.md)
- **Run the full system** → [docs/getting-started/RUN_FULL_SYSTEM.md](docs/getting-started/RUN_FULL_SYSTEM.md)
- **Operate the engine / API** → [docs/runbooks/](docs/runbooks/)
- **Deploy on AKS** → `docs/deployment/deploy.md` *(added with the deploy files)*
- **Live status** → [PROJECT_STATE.md](PROJECT_STATE.md)

## 🗂️ Repo layout

```
frontend/   React (Vite + TypeScript) dashboard
backend/    classifyos/ (ML engine) · api/ (FastAPI) · tests/
docs/       all documentation — start at docs/README.md
prompts/    archived generation prompts (governance record)
```

`CLAUDE.md` is the Claude Code context file. `PROJECT_STATE.md` / `plan_tweak.md` are the
live status registers kept at the root.
