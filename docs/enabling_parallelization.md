# Enabling Parallelization — ClassifyOS on Azure + Databricks

Target deployment: Azure-hosted FastAPI + Databricks Jobs for compute.
Input data: Unity Catalog tables (no CSV upload for large datasets).
Output: Unity Catalog volumes + MLflow experiment tracking.

## Cluster spec (confirmed)

| | Driver | Worker |
|---|---|---|
| VM | Standard_E8ds_v5 | Standard_E8ds_v5 |
| RAM | 64 GB | 64 GB |
| Cores | 8 | 8 |
| Count | 1 (fixed) | min 1, max 2 (autoscale) |
| Runtime | Databricks 18.2 — Spark 4.1.0, Scala 2.13 | |

**Total max compute:** 3 nodes × 8 cores = 24 cores, 192 GB RAM.

**Key inference:** The driver runs all sklearn/pandas ML work. At 3M rows (~2–4 GB in
memory) the dataset fits on the driver alone with headroom to spare. Worker nodes sit idle
unless Spark operations or `joblibspark` are used. The autoscale (1→2 workers) primarily
helps when multiple users submit concurrent jobs — each job lands on a separate node —
not for speeding up a single training run.

**Core-level parallelism on the driver (8 cores, n_jobs=-1) is the primary lever.
Cross-node parallelism is available but not the priority for this cluster size.**

---

## Priority order — highest value first

---

### 1. Async API refactor (blocker for everything else)

Current `/api/v1/run` is synchronous — FastAPI waits for the full run to complete before
responding. This will timeout on any run longer than ~30 seconds.

**What to do:**
- `POST /api/v1/run` returns `{ job_id }` immediately after submitting the Databricks Job
- Add `GET /api/v1/run/{job_id}/status` — returns `PENDING | RUNNING | COMPLETED | FAILED`
- Add `GET /api/v1/run/{job_id}/results` — returns full results JSON once complete
- Frontend polls `/status` every 5–10s, switches to results when `COMPLETED`

This is a schema-version bump on the API contract (additive — existing fields unchanged).

---

### 2. Persistent job state

FastAPI is stateless. If it restarts mid-poll, the `job_id` is lost and the user cannot
reconnect to their running job.

**What to do:**
- Store `job_id → { status, submitted_at, user_id, databricks_run_id }` in a lightweight
  persistent store (PostgreSQL — we already have one for MLflow, or Azure Cache for Redis)
- On restart, FastAPI can resume polling any `RUNNING` jobs from the DB
- Also enables a `GET /api/v1/runs` history endpoint per user later

---

### 3. Unity Catalog as data input (replace CSV upload for large data)

Uploading a 3M-row CSV over HTTP is slow, unreliable, and unnecessary when data already
lives in Databricks.

**What to do:**
- Add a `uc_path` field to `RunConfig` alongside the existing `file` field:
  `catalog.schema.table_name` or a UC volume path
- `StorageAdapter` already has the Unity Catalog hook — implement `read_table(uc_path)`
  using the Databricks SQL connector or `spark.read.table()` inside the job
- The Databricks Job reads directly from UC using the user's PAT — no data leaves Databricks

For departments who already have their data in Unity Catalog this eliminates the upload
entirely. CSV upload stays for small/local datasets.

---

### 4. Databricks Jobs integration

Submit ML runs as Databricks Jobs rather than running in-process.

**What to do:**
- Package `classifyos` as a Python wheel, upload to Databricks (or install via cluster
  init script)
- FastAPI calls `POST /api/2.1/jobs/runs/submit` with:
  - The wheel as the task
  - `RunConfig` serialized to JSON as task parameters
  - User's PAT as the data-access credential
- FastAPI polls `GET /api/2.1/jobs/runs/get?run_id=...` for status
- Outputs written to UC volume; FastAPI fetches and returns to UI on completion

**PAT handling:**
- Store PAT in the request session only — never persist to disk or DB
- Validate PAT before submitting the job; surface expiry errors clearly in UI
- Add a test-connection endpoint so users can verify their PAT before running

---

### 5. Fix SMOTE at scale (critical bottleneck at 3M rows)

SMOTE does k-nearest-neighbor on the full training set — O(n²) at 3M rows. It will either
run for hours or OOM.

**Options in priority order:**

| Option | When to use |
|---|---|
| Random oversampling | Fastest — good baseline for large imbalanced sets |
| SMOTE on a sample | Fit SMOTE on 50k–100k rows, apply to full set |
| `imbalanced-learn` `BorderlineSMOTE` | More targeted, faster than vanilla SMOTE |
| Skip balancing, use `class_weight='balanced'` | Built into sklearn/XGBoost — no extra data |

Add a `smote_max_rows` config threshold: if training set exceeds N rows, auto-switch to
`class_weight='balanced'` and warn the user. Default threshold: 500k rows.

---

### 6. Multi-core model training (immediate win — 8 cores on driver)

All sklearn models and XGBoost support `n_jobs` — currently not set explicitly.

**What to do:**
- Pass `n_jobs=-1` (use all 8 driver cores) to every model wrapper at fit time
- Random Forest: set `n_jobs=-1` — trees trained in parallel across cores
- XGBoost: set `nthread=-1` — gradient boosting steps parallelized natively
- Logistic Regression: already benefits from `n_jobs=-1` for multi-class

8 cores gives near-linear speedup on RF and LR with zero architectural change.
This is the single highest-effort-to-reward ratio item in the list.

---

### 7. Optuna parallel trials via ask/tell

Standard Optuna runs one trial at a time. With the ask/tell interface and a shared storage
backend, N workers can run N trials concurrently.

**What to do:**
- Point Optuna study at a shared RDB storage (the existing MLflow PostgreSQL works):
  `study = optuna.create_study(storage="postgresql://...")`
- Use `study.ask()` N times to get N param sets upfront, dispatch to N workers, then
  `study.tell()` results back as each completes
- Recommended concurrency: 4–8 workers (beyond this the constant-liar noise degrades
  TPE quality more than the speedup is worth)

**Note on TPE and parallelism:** TPE is inherently sequential — each trial informs the next.
In parallel mode, workers that ask before prior trials complete receive suggestions based on
a "constant liar" heuristic (in-progress trials treated as bad results). This is Optuna's
official parallel pattern. Quality degrades slightly with more workers; 4 is a good default.

**On this cluster:** run 4–8 concurrent trials using Python `ThreadPoolExecutor` or
`multiprocessing` on the driver (8 cores). Worker nodes are not needed for this.
`SparkTrials` would dispatch to worker nodes but adds Spark overhead for marginal gain
on a 2-worker cluster — use driver-level concurrency first.

**Alternative:** Databricks-native `Hyperopt` with `SparkTrials` — consider only if
the cluster is scaled up significantly (4+ workers) in future.

---

### 8. Databricks-native libraries for parallelization

These libraries integrate with the Spark cluster and can replace or augment existing
Python-only code for large datasets:

| Library | Replaces | Benefit |
|---|---|---|
| `joblibspark` | joblib backend | Routes `n_jobs` parallelism to Spark workers — sklearn/CV folds run across nodes |
| `hyperopt` + `SparkTrials` | Optuna | Native Databricks HPO, trials on separate Spark workers |
| `pyspark.pandas` | pandas in feature engineering | Same pandas API, executes on Spark — handles data larger than single-node RAM |
| `RAPIDS cuML` | sklearn models | GPU-accelerated RF, LR, XGBoost — 10–50x speedup (requires GPU nodes) |
| `Fugue` | pandas pipelines | Run existing pandas/sklearn code on Spark with minimal changes |

**Recommended adoption order for this cluster (1 driver + 1–2 workers):**
1. `n_jobs=-1` on all models — free, no Spark needed, biggest immediate win (item 6 above)
2. `joblibspark` — only worthwhile if scaled to 4+ workers; on 1–2 workers the Spark
   overhead likely outweighs the gain
3. `hyperopt` + `SparkTrials` — same caveat as joblibspark; defer until cluster grows
4. `pyspark.pandas` — not needed; 3M rows fits in 64 GB driver RAM
5. RAPIDS — not applicable; no GPU nodes in current spec

**For this cluster: don't add Spark-based parallelism yet. Core-level (n_jobs) is sufficient.**

---

### 9. inspect_file sampling at scale

`inspect_file` currently loads the full dataset into memory to compute column stats.
At 3M rows this wastes time and memory for a profiling step.

**What to do:**
- If row count exceeds a threshold (e.g. 100k), sample 10k–50k rows for profiling
- Report exact row count (via metadata, not full scan) separately
- Databricks Delta tables expose stats natively — use `DESCRIBE EXTENDED` for fast profiling
  without a full table scan

---

### 10. Job timeout and cost guardrails

No kill switch exists today. A misconfigured run on 3M rows could burn DBUs for hours.

**What to do:**
- Set `timeout_seconds` on every Databricks Job submission (suggested default: 3600s / 1 hour)
- Expose a `POST /api/v1/run/{job_id}/cancel` endpoint that calls the Databricks cancel API
- After job completes, fetch DBU usage from `GET /api/2.1/jobs/runs/get` and return it
  alongside results — surface as cost estimate in UI

---

### 11. Concurrency and job queue

Multiple users submitting simultaneously compete for cluster capacity.

**What to do:**
- Databricks handles basic queuing natively — if cluster is full, jobs queue automatically
- Add a `max_concurrent_runs` setting on the Databricks Job definition (e.g. 5)
- Surface queue position in the status polling response so users know they're waiting
- For longer term: a dedicated job cluster per department, or autoscaling cluster pools

---

### 12. Model artifact size management

A Random Forest trained on 3M rows can produce a pickle file of several GB.

**What to do:**
- Store artifacts in UC volumes, not in FastAPI memory — already planned via StorageAdapter
- Use MLflow model registry for versioned storage (avoids duplicates across runs)
- Add a TTL policy: artifacts older than N days are moved to cold storage or deleted
- For RF specifically: consider `max_leaf_nodes` cap to bound model size at training time

---

## What is NOT needed for this cluster (Standard_E8ds_v5, 1 driver + 1–2 workers)

- Full Spark MLlib rewrite — driver-only sklearn with `n_jobs=-1` handles 3M rows fine
- `joblibspark` / `SparkTrials` — Spark overhead not worth it on 1–2 workers; revisit if cluster grows
- Distributed data processing (`pyspark.pandas`) — 3M rows fits in 64 GB driver RAM
- GPU nodes — not in current spec; standard CPU is sufficient
- Sharding or chunked training — sklearn processes full dataset in one pass
- Cross-node Optuna parallelism — 8 driver cores with ThreadPoolExecutor is sufficient for 4–8 concurrent trials

---

## Dependency order (what unlocks what)

```
1. Async API refactor
   └── 2. Persistent job state
       └── 4. Databricks Jobs integration
           ├── 3. Unity Catalog data input
           ├── 6. Multi-core training (n_jobs)
           ├── 7. Optuna parallel trials
           └── 10. Job timeout + cost guardrails
               └── 11. Concurrency / queue
5. SMOTE fix        ← independent, do in parallel with above
8. DB-native libs   ← layer on after 4 is working
9. inspect sampling ← independent, low effort
12. Artifact TTL    ← independent, do last
```
