# ClassifyOS — AKS Deployment Guide

> **Audience:** the DevOps engineer deploying ClassifyOS on **Azure Kubernetes Service (AKS)**.
> **Written by:** the dev team, as a handoff. Everything here is a **starting point** — adapt the
> manifests to your cluster's standards (Helm / Kustomize / GitOps, ingress class, secret store).
> **Open questions are collected at the end** in [§11 Decisions we need from you](#11-decisions-we-need-from-you-devops). You don't need the dev team to answer them — they're yours to decide; the defaults are our suggestions.

---

## 1. What ClassifyOS is (30-second version)

A React single-page app (SPA) talks to a FastAPI backend, which wraps a pure-Python ML engine.

```
browser ──▶ frontend (React SPA, static files) ──/api──▶ backend (FastAPI) ──▶ ML engine (in the same image)
```

- The API is **stateless** — no session or model is held between requests.
- **Two images** to build & run: **`backend`** (FastAPI + engine) and **`frontend`** (static SPA behind nginx).
- The ML engine (training XGBoost/LightGBM, Optuna tuning, SHAP) lives **inside the backend image**. Whether it *runs there* or is *offloaded to Databricks* is the single most important choice — see [§3](#3-the-one-decision-that-changes-everything-execution-mode).

---

## 2. Recommended topology — single public host

```
                        ┌────────────────────────── AKS cluster ──────────────────────────┐
   Internet ──TLS──▶ Ingress ──▶ [ Service: frontend :80 ] ──▶ frontend pod (nginx :8080)  │
                                                                 ├─ serves the SPA (static) │
                                                                 └─ proxies /api/ ──▶ [ Service: backend :8000 ] ──▶ backend pod (uvicorn :8000)
                        └──────────────────────────────────────────────────────────────────┘
```

- **Only the frontend is exposed.** nginx inside the frontend pod reverse-proxies `/api/` to the cluster-internal **`backend`** Service.
- Browser sees a **single origin** → **no CORS needed**, and the SPA needs no per-environment rebuild (its API base stays the relative default `/api/v1`).
- **Alternative (split hosts, e.g. `app.host` + `api.host`)** also works but requires routing `/api` at the Ingress to the backend Service **and** setting `CORS_ORIGINS` on the backend. We recommend the single-host proxy layout above.

---

## 3. The one decision that changes everything: execution mode

The backend env var **`CLASSIFYOS_EXECUTION_BACKEND`** decides where the heavy ML work runs:

| Mode | `CLASSIFYOS_EXECUTION_BACKEND` | What the backend pod does | Pod sizing | Storage |
|---|---|---|---|---|
| **Databricks** (recommended for prod) | `databricks` | Submits a Databricks Job and returns `{job_id}`; the UI polls status/results. Databricks does the compute + storage. | **Light** (~0.5 vCPU / 512Mi) | Minimal local; results read back from Databricks |
| **Local** | `local` (default) | Runs the full ML pipeline **in-process**. `POST /api/v1/run` can take **minutes**. | **Heavy** (≥4 vCPU / 8Gi, per concurrent run) | Needs a shared **ReadWriteMany** volume for `DATA_DIR`/`OUTPUT_DIR` |

Given the Databricks integration already built into this app, **prod is most likely `databricks` mode**. Confirm this first — it determines pod resources ([§9](#9-example-kubernetes-manifests-adapt-to-your-cluster)), storage ([§7](#7-storage)), and timeout handling ([§10](#10-long-running-requests--important)).

---

## 4. Images

Both Dockerfiles below are **copy-paste ready**. Create them at `backend/Dockerfile` and `frontend/Dockerfile` (plus `frontend/nginx.conf`). Build contexts are the respective app directories.

### 4a. Backend image — `backend/Dockerfile`

```dockerfile
# ClassifyOS backend — FastAPI HTTP layer + the pure-Python ML engine.
# Build context = the repo's backend/ directory.
FROM python:3.11-slim

# libgomp1 = the OpenMP runtime. REQUIRED: `import lightgbm` / `import xgboost` fail without it.
# No compiler is needed — every ML dep ships a manylinux wheel for cp311. (If some dep on your
# arch lacks a wheel, add build-essential in a builder stage.)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg          
    # matplotlib headless — plot_results writes PNGs, never opens a display.

WORKDIR /app

# Install deps first (better layer caching). requirements.lock is the pinned set (reproducible);
# swap to requirements.txt for the loose ranges.
COPY requirements.lock requirements.txt ./
RUN pip install --no-cache-dir -r requirements.lock

# App source. Both `api` (FastAPI) and `classifyos` (engine) are top-level packages here,
# so `api.main:app` and `import classifyos` resolve with WORKDIR on the path.
COPY . .

# Run as non-root.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
# Prefer horizontal replicas over many --workers: each worker loads the full ML stack into RAM.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

**`backend/.dockerignore`** (keep the local dev cruft and secrets out of the image):

```
.venv/
__pycache__/
*.pyc
build/
dist/
*.egg-info/
data/
classification_output/
tests/
.pytest_cache/
.env
```

### 4b. Frontend image — `frontend/Dockerfile`

```dockerfile
# ClassifyOS frontend — build the Vite/React SPA, serve it with nginx.
# Build context = the repo's frontend/ directory.

# --- Stage 1: build the static bundle ---
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The API base defaults to the RELATIVE "/api/v1" (see src/api/client.ts). Keep the default for
# the single-host layout (nginx proxies /api → backend). For a SPLIT-host setup only, uncomment:
#   ARG VITE_API_BASE_URL
#   ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build          # → /app/dist

# --- Stage 2: serve with nginx (unprivileged image → runs as non-root, listens on 8080) ---
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
```

**`frontend/nginx.conf`** (SPA fallback + `/api` reverse-proxy):

```nginx
server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # SPA: serve the file if it exists, else hand routing to index.html (React Router).
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Reverse-proxy the API to the backend Service (same origin → no CORS).
    # "backend" must match the backend Service name in THIS namespace.
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Local execution mode: a /run can take minutes. Raise these to match §10.
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```
> The app sends a per-user Databricks PAT in the `X-Databricks-Token` header; nginx forwards it upstream unchanged (hyphenated header — no special config needed).

**`frontend/.dockerignore`:**

```
node_modules/
dist/
.env
.env.*
playwright-report/
test-results/
```

---

## 5. Build & push to ACR

```bash
ACR=<youracr>.azurecr.io        # your Azure Container Registry login server
VER=1.0.0

az acr login --name <youracr>

# Backend  (context = backend/)
docker build -t $ACR/classifyos-backend:$VER  -f backend/Dockerfile  backend
docker push  $ACR/classifyos-backend:$VER

# Frontend (context = frontend/)
docker build -t $ACR/classifyos-frontend:$VER -f frontend/Dockerfile frontend
docker push  $ACR/classifyos-frontend:$VER
```
Grant the AKS kubelet identity `AcrPull` on the registry (`az aks update --attach-acr <youracr>`), or use an `imagePullSecret`.

---

## 6. Configuration — environment variables (backend)

Only a few are needed for a basic deploy; the rest enable optional features. Put non-secrets in a **ConfigMap**, secrets in a **Secret** (or Azure Key Vault via the CSI driver). Full annotated reference: [`backend/.env.example`](../../backend/.env.example).

| Variable | Group | Required? | Secret? | Example / notes |
|---|---|---|---|---|
| `DATA_DIR` | Core storage | Yes¹ | No | `/data/input` — mount a volume here (see §7) |
| `OUTPUT_DIR` | Core storage | Yes¹ | No | `/data/output` — models/plots/JSON land here |
| `CORS_ORIGINS` | Core | Only split-host | No | Comma-list of browser origins; **leave empty** in the single-host layout |
| `CLASSIFYOS_EXECUTION_BACKEND` | Execution | Recommended | No | `databricks` or `local` (default). See §3 |
| `DATABRICKS_HOST` | Databricks | If `databricks` | No | `https://adb-XXXX.azuredatabricks.net` |
| `DATABRICKS_TOKEN` | Databricks | If `databricks` | **Yes** | **Service** token (Jobs API only, never data) |
| `DATABRICKS_JOB_NOTEBOOK_PATH` | Databricks | If `databricks` | No | Job entrypoint notebook path |
| `DATABRICKS_JOB_CLUSTER_ID` | Databricks | If `databricks` | No | Existing cluster the Job runs on |
| `DATABRICKS_JOB_WHEEL_PATH` | Databricks | If `databricks` | No | `/Volumes/.../classifyos-1.0.0-py3-none-any.whl` |
| `DATABRICKS_JOB_TIMEOUT_SECONDS` | Databricks | No | No | Wall-clock cap (default 3600) |
| `CLASSIFYOS_STORAGE_BACKEND` | Storage | No | No | `databricks` → use UC volumes instead of `DATA_DIR`/`OUTPUT_DIR` |
| `DBRICKS_INPUT_VOLUME` / `DBRICKS_OUTPUT_VOLUME` | Storage | If UC storage | No | `/Volumes/main/classifyos/data/{input,output}` |
| `MLFLOW_TRACKING_URI` | MLflow | No | No² | `databricks`, or a `postgresql://…` DSN (²secret if it embeds creds) |
| `MLFLOW_REGISTRY_URI` | MLflow | No | No | `databricks-uc` |
| `CLASSIFYOS_PG_DSN` | Postgres input | No | **Yes** | Only if runs use `input_source.type=postgres` |
| `AZURE_OPEN_AI_API_KEY` (+ `_ENDPOINT`, `_API_VERSION`, `_MODEL`, `_DEPLOYMENT_NAME`) | Azure OpenAI | No | **Yes** (key) | Only for optional LLM reason-code narratives |

¹ If `CLASSIFYOS_STORAGE_BACKEND=databricks`, the UC volume vars replace `DATA_DIR`/`OUTPUT_DIR`. In **local** storage mode, if these are unset the app falls back to relative `./data` / `./classification_output` **inside the container** — ephemeral and lost on restart, so **always set them** to a mounted path.

> The backend calls `load_dotenv()` at startup but has **no `.env` in the image** (it's `.dockerignore`d) — all config comes from the k8s env. `load_dotenv()` simply no-ops.

---

## 7. Storage

- **Databricks mode:** the pod needs little/no persistent storage — an `emptyDir` for scratch is typically enough. Inputs/outputs live on Unity Catalog volumes; results are read back from Databricks. *(Confirm against your upload flow — file uploads may still stage to `DATA_DIR` before submission.)*
- **Local mode:** `DATA_DIR` and `OUTPUT_DIR` must be a **shared, persistent, ReadWriteMany** volume so (a) artifacts survive restarts and (b) all backend replicas see the same files. On AKS that's **Azure Files** (`azurefile-csi`, RWX). Size for your datasets + model/plot artifacts. See the optional PVC in §9.

---

## 8. Health, probes, ports

| Component | Container port | Probe |
|---|---|---|
| backend | `8000` | liveness **and** readiness → `GET /api/v1/health` (instant, no I/O; returns `{"status":"ok",...}`) |
| frontend | `8080` | liveness → `GET /` (nginx serves `index.html`) |

For **local** execution mode, keep the readiness probe lightweight (it already is — `/health` does no ML work), and give a generous `terminationGracePeriodSeconds` so an in-flight training run can finish on rolling updates.

---

## 9. Example Kubernetes manifests (adapt to your cluster)

Placeholders in `<…>`. This is the **single-host, Databricks-mode** shape; notes call out what to change for local mode. Namespace assumed `classifyos`.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: classifyos
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: classifyos-config
  namespace: classifyos
data:
  DATA_DIR: "/data/input"
  OUTPUT_DIR: "/data/output"
  CORS_ORIGINS: ""                       # empty in the single-host proxy layout
  CLASSIFYOS_EXECUTION_BACKEND: "databricks"
  DATABRICKS_HOST: "https://adb-XXXX.azuredatabricks.net"
  DATABRICKS_JOB_NOTEBOOK_PATH: "/Repos/classifyos/notebooks/classifyos_job_runner"
  DATABRICKS_JOB_CLUSTER_ID: "0716-XXXXXX-abcd"
  DATABRICKS_JOB_WHEEL_PATH: "/Volumes/main/classifyos/libs/classifyos-1.0.0-py3-none-any.whl"
  # MLFLOW_TRACKING_URI: "databricks"    # + MLFLOW_REGISTRY_URI: "databricks-uc" for Runs history
---
apiVersion: v1
kind: Secret
metadata:
  name: classifyos-secrets
  namespace: classifyos
type: Opaque
stringData:
  DATABRICKS_TOKEN: "<service-pat>"      # ← move to Azure Key Vault (CSI) for prod
  # AZURE_OPEN_AI_API_KEY: "<key>"       # only if LLM narratives are enabled
  # CLASSIFYOS_PG_DSN: "postgresql://…"  # only for postgres input source
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
  namespace: classifyos
spec:
  replicas: 2                            # local mode: size to concurrency; each replica is heavy
  selector:
    matchLabels: { app: classifyos-backend }
  template:
    metadata:
      labels: { app: classifyos-backend }
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
      containers:
        - name: backend
          image: <youracr>.azurecr.io/classifyos-backend:1.0.0
          ports: [{ containerPort: 8000 }]
          envFrom:
            - configMapRef: { name: classifyos-config }
            - secretRef:    { name: classifyos-secrets }
          readinessProbe:
            httpGet: { path: /api/v1/health, port: 8000 }
            initialDelaySeconds: 10
            periodSeconds: 10
          livenessProbe:
            httpGet: { path: /api/v1/health, port: 8000 }
            initialDelaySeconds: 20
            periodSeconds: 20
          resources:                     # Databricks mode. LOCAL mode: bump to 4+ CPU / 8Gi+.
            requests: { cpu: "250m", memory: "512Mi" }
            limits:   { cpu: "1",    memory: "1Gi" }
          # LOCAL mode only — mount shared storage for DATA_DIR/OUTPUT_DIR:
          # volumeMounts: [{ name: data, mountPath: /data }]
      # volumes: [{ name: data, persistentVolumeClaim: { claimName: classifyos-data } }]
---
apiVersion: v1
kind: Service
metadata:
  name: backend                          # ← nginx.conf proxies to http://backend:8000
  namespace: classifyos
spec:
  selector: { app: classifyos-backend }
  ports: [{ port: 8000, targetPort: 8000 }]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  namespace: classifyos
spec:
  replicas: 2
  selector:
    matchLabels: { app: classifyos-frontend }
  template:
    metadata:
      labels: { app: classifyos-frontend }
    spec:
      containers:
        - name: frontend
          image: <youracr>.azurecr.io/classifyos-frontend:1.0.0
          ports: [{ containerPort: 8080 }]
          livenessProbe:
            httpGet: { path: /, port: 8080 }
          resources:
            requests: { cpu: "50m",  memory: "64Mi" }
            limits:   { cpu: "200m", memory: "128Mi" }
---
apiVersion: v1
kind: Service
metadata:
  name: frontend
  namespace: classifyos
spec:
  selector: { app: classifyos-frontend }
  ports: [{ port: 80, targetPort: 8080 }]
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: classifyos
  namespace: classifyos
  annotations:
    # ingress-nginx example. AGIC users: use appgw annotations instead.
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"   # match §10 for local mode
    cert-manager.io/cluster-issuer: "<your-issuer>"          # if using cert-manager for TLS
spec:
  ingressClassName: nginx
  tls:
    - hosts: ["<classify.your-domain>"]
      secretName: classifyos-tls
  rules:
    - host: "<classify.your-domain>"
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: { name: frontend, port: { number: 80 } }
```

**Optional PVC — local execution mode only** (Azure Files, ReadWriteMany):

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: classifyos-data
  namespace: classifyos
spec:
  accessModes: ["ReadWriteMany"]
  storageClassName: azurefile-csi
  resources:
    requests:
      storage: 20Gi
```

Deploy: `kubectl apply -f <file>.yaml` (or fold into your Helm/Kustomize/GitOps pipeline).

---

## 10. Long-running requests — important

In **local** execution mode, `POST /api/v1/run` trains models and runs Optuna/SHAP — this can take **minutes**. If any hop has a short idle/read timeout, the browser gets a 504 mid-run. Raise timeouts consistently:

- **Ingress:** `nginx.ingress.kubernetes.io/proxy-read-timeout: "600"` (or AGIC equivalent).
- **frontend nginx.conf:** `proxy_read_timeout 600s;` (already in §4b).
- **Azure Load Balancer / any WAF** in front: raise idle timeout to match.
- HPA on CPU **won't** speed up a single long request — it only adds capacity for *more* concurrent runs.

**Databricks mode avoids all of this:** `POST /run` returns immediately with a `job_id`; the UI polls `GET /run/{job_id}/status` and `/results`. This is the recommended shape for heavy or bursty workloads.

---

## 11. Decisions we need from you (DevOps)

Recommended defaults in parentheses — override as your platform requires.

1. **Execution mode** (§3): `databricks` or `local`? *(recommend `databricks`)* — drives everything below.
2. **Container registry:** which ACR login server + image naming/tagging? *(`<acr>.azurecr.io/classifyos-{backend,frontend}:<ver>`)*
3. **Public hostname + TLS owner:** what host, and cert-manager vs AGIC-managed vs manual cert? *(`classify.<domain>`, cert-manager)*
4. **Ingress controller:** ingress-nginx or AGIC? Single-host proxy layout or split hosts? *(ingress-nginx, single host)*
5. **Secrets store:** plain k8s `Secret` or Azure Key Vault (CSI)? *(Key Vault CSI for prod)*
6. **Storage (local mode only):** confirm `azurefile-csi` RWX and size. *(20Gi to start)*
7. **Resource requests/limits & replicas:** confirm the §9 numbers against expected load *(light for Databricks; 4+ CPU / 8Gi+ for local)*.
8. **Network egress:** is outbound from AKS to Databricks (and Postgres/MLflow if used) allowed and provisioned?
9. **Namespaces/environments:** dev/staging/prod split and namespace names? *(`classifyos`)*
10. **Databricks prerequisites (if `databricks` mode):** service PAT, target cluster ID, uploaded engine wheel, and the job-runner notebook path — who provisions these?

---

## 12. Smoke test after deploy

```bash
# API is up (through the ingress, via the frontend nginx proxy):
curl -s https://<classify.your-domain>/api/v1/health
# → {"status":"ok","service":"ClassifyOS API","version":"1.0","execution_backend":"databricks"}

# SPA loads:
curl -sI https://<classify.your-domain>/           # 200, text/html
```
Then open `https://<classify.your-domain>` in a browser and run a small classification to confirm the full path (SPA → nginx `/api` → backend → engine/Databricks).

---

*Questions on app internals (endpoints, the run contract, engine behaviour) → see [`../README.md`](../README.md) (docs index), [`../runbooks/API_RUNBOOK.md`](../runbooks/API_RUNBOOK.md), and [`../api_contract.md`](../api_contract.md).*
