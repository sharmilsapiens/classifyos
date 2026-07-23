# ClassifyOS — First Run Guide

Getting the app running from scratch on a new machine.
Audience: someone who received the project as a zip and wants to open it in the browser.

> **Running with Claude Code?** Hand this file to Claude and say _"follow FIRST_RUN.md to set up and start ClassifyOS"_ — it can run every command for you.

---

## Prerequisites

Install these once if they are not already on your machine.

| Tool | Required version | Download |
|------|-----------------|----------|
| Python | 3.11.x | python.org/downloads — tick "Add to PATH" during install |
| Node.js | 18 LTS or newer | nodejs.org/en/download |

Verify in a terminal:

```powershell
python --version    # should print 3.11.x
node --version      # should print v18 or higher
```

---

## Step 1 — Extract the zip

Unzip the project to a folder of your choice, for example `C:\Projects\classifyos`.
The instructions below use that path — adjust if yours is different.

---

## Step 2 — Create the data folders

The app reads CSV files from a data folder and writes results to an output folder.
These live **outside** the project so your data is never mixed in with the code.

```powershell
New-Item -ItemType Directory -Force C:\Projects\classifyos_data\input
New-Item -ItemType Directory -Force C:\Projects\classifyos_data\output
```

Copy the sample CSVs that ship with the project into the input folder:

```powershell
Copy-Item C:\Projects\classifyos\backend\data\samples\* C:\Projects\classifyos_data\input\
```

The samples are:

| File | What it tests |
|------|--------------|
| `policy_lapse.csv` | Binary — will a policy lapse? |
| `claim_likelihood.csv` | Binary — will a claim be filed? |
| `fraud_claims.csv` | Binary — is a claim fraudulent? (~99:1 imbalance) |
| `risk_tier.csv` | Multiclass — which risk tier? |
| `customer_segment.csv` | Multiclass — which customer segment? |
| `claim_severity.csv` | Multiclass — what is claim severity? |
| `product_reco.csv` | Multilabel — which products to recommend? |

Start with **`policy_lapse.csv`** — it is the simplest.

---

## Step 3 — Configure the environment

```powershell
Copy-Item C:\Projects\classifyos\backend\.env.example C:\Projects\classifyos\backend\.env
```

Open `backend\.env` in any text editor. The default paths match what you created in Step 2,
so if you used `C:\Projects\classifyos_data` you do not need to change anything.

---

## Step 4 — Install Python dependencies

```powershell
cd C:\Projects\classifyos\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

This takes a few minutes the first time (it downloads scikit-learn, pandas, etc.).

---

## Step 5 — Install frontend dependencies

```powershell
cd C:\Projects\classifyos\frontend
npm install
```

---

## Step 6 — Start the app (two terminals)

The app is two servers that run at the same time. Open **two PowerShell windows**.

**Terminal 1 — backend API:**

```powershell
cd C:\Projects\classifyos\backend
.\.venv\Scripts\Activate.ps1
uvicorn api.main:app --reload --port 8000
```

Wait for: `Uvicorn running on http://127.0.0.1:8000`

**Terminal 2 — frontend (the website):**

```powershell
cd C:\Projects\classifyos\frontend
npm run dev
```

Wait for: `Local: http://localhost:5173/`

---

## Step 7 — Open in the browser

1. Open **http://localhost:5173**
2. The banner at the top should be **green ("API connected")**.
   If it is red, the backend in Terminal 1 is not running — check that terminal.
3. Click **Upload Data** and select `policy_lapse.csv` from your input folder
   (`C:\Projects\classifyos_data\input\policy_lapse.csv`).
4. Click through to **Configuration** — pick `will_lapse` as the target column,
   leave the rest as defaults, and click **Run**.
5. Results appear on the **Overview** page and the tabs to the right
   (Feature Impact, Confusion Matrix, ROC/PR Curves, Predictions, etc.).

---

## Stopping the servers

Press **Ctrl+C** in each terminal.

---

## Optional — Run history & saved models (MLflow)

Everything above works **without** MLflow. This section is only needed if you want past runs to
persist (survive a browser refresh / server restart) and models to be saved for reload — the
**Runs** page in the app is backed by an MLflow store.

The Configuration page has a **"Log this run to MLflow"** toggle (on by default). If no store is
configured or reachable it is **silently skipped** — the run still completes normally, it just
isn't recorded. So there are three levels:

### Level 0 — do nothing
Leave it as-is. Runs are not recorded; the Runs page stays empty. The app is fully functional.

### Level 1 — local store, zero setup
Leave the MLflow env vars **unset** (they are commented out in `.env.example`). The first time a
run is logged, MLflow creates a local **sqlite `mlflow.db`** (run history) plus an **`./mlruns`**
folder (artifacts) **next to wherever you launched the backend** — normally `backend/`. Both are
gitignored. Runs now appear on the Runs page and survive a refresh and a restart. No Postgres, no
extra install (`mlflow` is already installed by Step 4).

### Level 2 — Postgres backend + local artifact folder (Interim 2a)
Run history/params/metrics live in a **local PostgreSQL** (SQL-queryable); the PNGs, CSVs and saved
models stay a local **folder**. This is the full "Interim 2a" stack. It is **configuration only** —
no code changes.

The Python drivers (`mlflow`, `SQLAlchemy`, `psycopg2-binary`) are already installed by Step 4.
The extra setup is Postgres + two env vars:

**1. Install PostgreSQL 17** (once). Easiest via winget:

```powershell
winget install PostgreSQL.PostgreSQL.17
```

This installs the `postgresql-x64-17` Windows service (auto-starts on boot, port 5432) with a
`postgres` superuser. The CLI (`psql`) lands in `C:\Program Files\PostgreSQL\17\bin`.

**2. Create the app database and role** (run as the `postgres` superuser — it will prompt for the
password you set during install). These are **dev-only** credentials:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -c "CREATE ROLE classifyos WITH LOGIN PASSWORD 'classifyos';"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -c "CREATE DATABASE mlflow OWNER classifyos;"
```

MLflow auto-creates its tables inside the empty `mlflow` database on first use — no migration step.

**3. Create the artifact folder** (kept outside the repo, same as the data folders):

```powershell
New-Item -ItemType Directory -Force C:\Projects\classifyos_data\mlflow-artifacts
```

**4. Point `.env` at both stores.** Open `backend\.env` and uncomment/set these two lines:

```ini
MLFLOW_TRACKING_URI=postgresql://classifyos:classifyos@localhost:5432/mlflow
_MLFLOW_SERVER_ARTIFACT_ROOT=file:///C:/Projects/classifyos_data/mlflow-artifacts
```

> On Windows the artifact root **must** be a `file://` URI — a bare `C:/...` path is misparsed (the
> drive letter looks like a URI scheme). Keep the leading underscore on `_MLFLOW_SERVER_ARTIFACT_ROOT`;
> it is MLflow's own env var for the default artifact root when the backend store is a database.

**5. Restart the backend.** The API reads `.env` **once at startup**, so a backend that was already
running will not see the new vars until you stop it (Ctrl+C) and re-run the `uvicorn` command from
Step 6.

**6. Run and check.** Enable *"Log this run to MLflow"* on the Configuration page (it is on by
default), run a pipeline, then open the **Runs** page — the run should be listed and reload into the
result pages, and its params/metrics now live in Postgres while its files land under
`C:\Projects\classifyos_data\mlflow-artifacts`.

To wipe the run history and start clean:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -c "DROP DATABASE mlflow WITH (FORCE); CREATE DATABASE mlflow OWNER classifyos;"
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Health banner is red | Backend is not running — check Terminal 1 for errors. |
| `pip install` fails with "python not found" | Python is not on PATH — reinstall with "Add to PATH" ticked. |
| `.venv\Scripts\Activate.ps1` is blocked | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once in PowerShell. |
| `npm run dev` fails | Run `npm install` in `frontend/` first; check Node.js is installed. |
| Backend prints "DATA_DIR not found" | Check the path in `backend\.env` matches the folder you created. |
| Page loads but Run produces no results | Make sure the CSV is in the `DATA_DIR` folder, not in the project folder. |
| Runs page stays empty after a logged run | The MLflow store isn't reachable so logging was silently skipped — check `MLFLOW_TRACKING_URI` in `.env` and that you **restarted** the backend after editing it. |
| MLflow logs go to sqlite/`./mlruns`, not Postgres | The backend was started before the Postgres env vars were set — `.env` is read once at startup, so restart the `uvicorn` process. |
| MLflow error about the artifact root | On Windows `_MLFLOW_SERVER_ARTIFACT_ROOT` must be a `file:///C:/...` URI, not a bare path. |

---

## Next steps

- `RUN_FULL_SYSTEM.md` — short reference for everyday use once setup is done.
- `API_RUNBOOK.md` — if you want to call the API directly without the browser.
