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

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Health banner is red | Backend is not running — check Terminal 1 for errors. |
| `pip install` fails with "python not found" | Python is not on PATH — reinstall with "Add to PATH" ticked. |
| `.venv\Scripts\Activate.ps1` is blocked | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once in PowerShell. |
| `npm run dev` fails | Run `npm install` in `frontend/` first; check Node.js is installed. |
| Backend prints "DATA_DIR not found" | Check the path in `backend\.env` matches the folder you created. |
| Page loads but Run produces no results | Make sure the CSV is in the `DATA_DIR` folder, not in the project folder. |

---

## Next steps

- `RUN_FULL_SYSTEM.md` — short reference for everyday use once setup is done.
- `API_RUNBOOK.md` — if you want to call the API directly without the browser.
