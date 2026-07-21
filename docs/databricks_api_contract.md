# ClassifyOS — Databricks API Contract (FastAPI ↔ Databricks)

> **Scope.** This is the SECOND of the project's two API contracts. The first,
> **frontend ↔ FastAPI**, is `docs/api_contract.md` (the locked `/api/v1/run` schema). This one
> documents the **FastAPI ↔ Databricks** interface: every Databricks REST call the Azure-hosted
> FastAPI layer makes when `CLASSIFYOS_EXECUTION_BACKEND=databricks`.
>
> **Source of truth.** Every endpoint path, payload field, and response shape below is derived from
> `backend/api/databricks.py` (the one thin `httpx` client for all Databricks REST) and its two
> callers, `backend/api/routes/run.py` and `backend/api/routes/jobs.py`. Nothing here is invented —
> see the verbatim path check at the end.
>
> **Audience.**
> - **DevOps** — the minimum permissions to grant the service token and the browsing user (§6),
>   and the env vars that wire it up (§7).
> - **Future Claude sessions** — the exact Databricks API shapes actually used, so nothing is guessed.
>
> **Companion docs.** `docs/databricks_how_it_works.md` (practical how-it-works + cluster setup),
> `docs/databricks_integration.md` (design/roadmap), `docs/api_contract.md` (the `1.11` layer that
> exposes this interface to the browser).

---

## 1. Auth model

All Databricks REST calls are **server-side** (from the FastAPI process). Two credentials are used,
and they are **never crossed**:

| Credential | Source | Used by | Why |
|---|---|---|---|
| **Service token** | `DATABRICKS_TOKEN` env var (`_service_token()`) | `submit_run`, `get_run_status`, `list_clusters`, `fetch_uc_file` | The **service identity** submits the Job, polls it, picks the cluster it runs on, and reads the result envelope the Job wrote to the output volume. |
| **User PAT** | `X-Databricks-Token` request header (`get_user_pat` → `_require_pat`) | `list_catalogs`, `list_schemas`, `list_tables`, `get_table_columns` | The **Unity Catalog data browser** must show exactly what the requesting user is entitled to — not the service identity's view. The PAT is passed per request and **never persisted**. |

Both are sent as a bearer credential on the `Authorization: Bearer <token>` header, built in the one
seam `_build_client(token)` (`fetch_uc_file` builds its own request the same way with the service
token). The `Authorization` header is never included in any log line or error message.

**One deliberate crossing — inside the Job, not on the wire.** The user's PAT is *also* forwarded
into the submitted Job's `base_parameters` as `user_token` (see §2). The cluster-side notebook sets
`DATABRICKS_TOKEN` to that value so Unity Catalog **data reads on the cluster run as the user**, not
as the service identity. This keeps FastAPI's REST auth clean (service token for Jobs, user PAT for
browsing) while the Job still reads data with the user's entitlements.

> **[RISK]** (from `databricks.py` module docstring) the user PAT rides in the Job's
> `base_parameters`, which makes it visible in the run's parameters in the Databricks UI. Hardening
> to a secret scope is a documented follow-up; the token is never persisted server-side.

**Error → HTTP mapping** (`_request` + the route handlers):

| Databricks condition | Client exception | HTTP surfaced to the browser |
|---|---|---|
| `401` / `403` from the workspace | `DatabricksAuthError` | `401` |
| Any other non-2xx, transport failure, or non-JSON body | `DatabricksUnavailable` | `503` |
| Backend set to `databricks` but a required env var missing | `DatabricksConfigError` | `500` |
| Missing `X-Databricks-Token` on a UC-browser / `/run` call | `DatabricksAuthError` | `401` |

The per-call HTTP timeout is `_HTTP_TIMEOUT = 30.0s` (one REST call — **not** the Job's own
wall-clock cap, which is `timeout_seconds`, §2).

---

## 2. Jobs API (2.1) — submit + poll

Both calls use the **service token**.

### `POST /api/2.1/jobs/runs/submit` — submit a one-off run

`submit_run(run_config, user_pat, cluster_id=None)` → `_submit_payload(...)` builds the body:

```jsonc
{
  "run_name": "classifyos · <target>",   // run_config["target"] or "run"
  "tasks": [
    {
      "task_key": "classifyos_run",
      "existing_cluster_id": "<resolved cluster id>",   // see cluster resolution below
      "notebook_task": {
        "notebook_path": "<DATABRICKS_JOB_NOTEBOOK_PATH>",
        "base_parameters": {
          "run_config": "<RunConfig JSON string>",   // json.dumps(run_config)
          "user_token": "<user PAT>",                // forwarded for UC data access on the cluster
          "wheel_path": "<DATABRICKS_JOB_WHEEL_PATH or \"\">"
        }
      },
      "libraries": [ { "whl": "<DATABRICKS_JOB_WHEEL_PATH>" } ]   // ONLY present when wheel_path is set
    }
  ],
  "timeout_seconds": 3600   // DATABRICKS_JOB_TIMEOUT_SECONDS, default 3600
}
```

**Each `base_parameter` (all reach the notebook as string widgets):**

| Key | Carries | Built from |
|---|---|---|
| `run_config` | The full web-facing `RunConfig` as a JSON string — the notebook rebuilds the engine config from it. Serialized with `by_alias=True` and `exclude={"cluster_id"}` in `routes/run.py`, so a `delta` `input_source` keeps its wire `schema` key and the submission stays byte-identical to a pre-`cluster_id` request. | `json.dumps(run_config)` |
| `user_token` | The requesting user's PAT — the notebook sets `DATABRICKS_TOKEN` to this so UC data reads run as the user (see §1). | `user_pat` (the `X-Databricks-Token` header) |
| `wheel_path` | UC volume path to the `classifyos` wheel — cell 1 of the notebook pip-installs from it only if the wheel isn't already importable. Empty string when the env var is unset. | `DATABRICKS_JOB_WHEEL_PATH` |

**Cluster resolution** (`_submit_payload`, schema 1.11 additive): a non-empty `cluster_id` argument
(from the UI picker, echoed on `/run`) wins; otherwise the `DATABRICKS_JOB_CLUSTER_ID` env var is
used. If **neither** resolves to a non-empty value → `DatabricksConfigError` (→ 500). A missing
`DATABRICKS_JOB_NOTEBOOK_PATH` is also `DatabricksConfigError`.

**`libraries`** is attached **only when** `wheel_path` is non-empty; the wheel is installed as a
per-task library so the notebook needs no `%pip install` magic.

**Response** (parsed by `submit_run`):

```jsonc
{ "run_id": 55501 }   // read as body["run_id"]; missing → DatabricksUnavailable
```

`submit_run` returns `{"run_id": "<id>"}` (stringified). `routes/run.py` then mints its own
persistent `job_id` (UUID) and stores `{job_id, databricks_run_id, status:"PENDING"}` in the
`classifyos_jobs` Postgres table before returning `RunSubmission` to the browser.

### `GET /api/2.1/jobs/runs/get` — poll a run's status

`get_run_status(databricks_run_id)`:

- **Request:** query param `run_id=<databricks_run_id>`.
- **Response:** the run object. The state is read defensively as
  `body["state"]` → else `body["status"]` → else the whole body, then passed to
  `_status_from_state`. Jobs 2.1 nests it under `state`; this tolerates a flat body or a 2.2-style
  `status`.

The relevant `RunState` sub-fields: `life_cycle_state`, `result_state`, `state_message`.

**`RunState` → the four public statuses** (`_status_from_state` → `JOB_STATUSES`):

| `life_cycle_state` | `result_state` | Public `status` |
|---|---|---|
| `PENDING`, `QUEUED`, `BLOCKED`, `WAITING_FOR_RETRY` | (any) | `PENDING` |
| `RUNNING`, `TERMINATING` | (any) | `RUNNING` |
| `TERMINATED` | `SUCCESS` or `SUCCEEDED` | `COMPLETED` |
| `TERMINATED` | anything else | `FAILED` |
| `INTERNAL_ERROR`, `SKIPPED` | (any) | `FAILED` |
| unknown / absent | (any) | `RUNNING` (never spuriously terminal mid-poll) |

`message` is `state_message`, falling back to `result_state`, then `life_cycle_state`, then
`"unknown"`. `get_run_status` returns `{"status", "message"}`. Both `SUCCESS` (Jobs API) and
`SUCCEEDED` (system tables) count as success.

**Polling resilience** (`routes/jobs.py::_refresh_status`): a transient `DatabricksUnavailable`
during a poll returns the **last-known stored status** rather than failing, so a polling client never
sees the run "reset". A `DatabricksAuthError` still propagates (→ 401).

---

## 3. Files API (2.0) — result fetch

Uses the **service token**. `fetch_uc_file(volume_path)` issues:

```
GET {DATABRICKS_HOST}/api/2.0/fs/files{volume_path}
Authorization: Bearer <service token>
```

`volume_path` must be an absolute UC volume path and is **appended directly** to
`/api/2.0/fs/files` (no separator — the leading `/` of the volume path is the separator), e.g.
`/api/2.0/fs/files/Volumes/aiml_rd/classifyos/output/api/<job_id>/run_response.json`.

**How the path is built** — by the caller `routes/jobs.py::get_results_endpoint`, not by
`fetch_uc_file` itself:

```python
output_volume = os.environ["DBRICKS_OUTPUT_VOLUME"].rstrip("/")   # 500 if unset
uc_path = f"{output_volume}/api/{job_id}/run_response.json"
raw = fetch_uc_file(uc_path)
```

So the fetched key is **`DBRICKS_OUTPUT_VOLUME` + `/api/{job_id}/run_response.json`** — a
**per-`job_id`** result envelope (each run writes its own `api/<job_id>/run_response.json`, so
concurrent runs never collide). The response body is the **exact locked `/run` envelope** the Job
wrote, returned byte-identically to the browser.

> Note: the `fetch_uc_file` docstring shows a generic `…/output/api/run_response.json` example
> without the `job_id` segment — that is illustrative only; the live caller always inserts
> `/{job_id}/` (this is the "correct per-job result path" fix, commit `757048d`).

**Status handling** (`fetch_uc_file`):

| Status | Meaning | Raised | HTTP surfaced by `/results` |
|---|---|---|---|
| `200` | Envelope present | — | `200` (the locked envelope) |
| `404` | **File not found** — the Job finished but hasn't written the envelope yet (or wrote a different key) | `DatabricksUnavailable` | `404` "results envelope is not available yet" |
| `401` | **Service token rejected** — bad/expired `DATABRICKS_TOKEN`, or it lacks `READ VOLUME` on the output volume | `DatabricksAuthError` | `401` |
| other non-2xx | Fetch failed | `DatabricksUnavailable` | `404` (per the `/results` handler) |
| transport error | Workspace unreachable | `DatabricksUnavailable` | `404` (per the `/results` handler) |

So a **404 means "no envelope at that key yet"** (transient — poll again once `COMPLETED`), while a
**401 means "the service token was rejected"** (a real auth/permission problem — check
`DATABRICKS_TOKEN` and its `READ VOLUME` grant). `/results` also returns `409` when the run is not
yet `COMPLETED`, before any fetch is attempted.

---

## 4. Unity Catalog API (2.1) — data-source browser

All four use the **user PAT** (`X-Databricks-Token`); a missing PAT → `DatabricksAuthError` (401)
via `_require_pat`. Each returns names/columns extracted from the payload.

| Call | Function | Query params | Reads from response | Returns |
|---|---|---|---|---|
| `GET /api/2.1/unity-catalog/catalogs` | `list_catalogs` | — | `body["catalogs"][].name` | sorted `list[str]` catalog names |
| `GET /api/2.1/unity-catalog/schemas` | `list_schemas` | `catalog_name=<catalog>` | `body["schemas"][].name` | sorted `list[str]` schema names |
| `GET /api/2.1/unity-catalog/tables` | `list_tables` | `catalog_name=<catalog>` & `schema_name=<schema>` | `body["tables"][].name` | sorted `list[str]` table names |
| `GET /api/2.1/unity-catalog/tables/{full_name}` | `get_table_columns` | — (`full_name` in path) | `body["columns"][]` (`ColumnInfo`) | `list[dict]` column metadata |

**List calls** (`_names`): the helper pulls the `name` field from each list item and drops entries
without one; the API layer then returns them sorted.

**Get-a-table** (`get_table_columns`): `full_name` is the dotted `catalog.schema.table`, built as
`f"{catalog}.{schema}.{table}"` and appended to the tables path
(`f"{_TABLES_PATH}/{full_name}"`). It returns the table's `columns` array — each a `ColumnInfo`
dict verified against the Databricks SDK (`name`, `type_name`, `type_text`, `nullable`, `comment`,
`position`, …). If the response carries **no** `columns` (missing or empty), it raises
`DatabricksUnavailable` (→ 503) rather than falling through to a silent empty profile.

> `catalog`/`schema`/`table` are validated as simple SQL identifiers in
> `routes/databricks.py::table_profile_endpoint` (`_SQL_IDENTIFIER_RE`) **before** interpolation
> into the REST path → a bad identifier is a `422`, never a reshaped URL. The `type_name` values
> are mapped to the `inspect_file` column groups in that route (`_UC_NUMERIC_TYPES` /
> `_UC_DATETIME_TYPES`, `BOOLEAN` → binary); see `docs/api_contract.md` → `/databricks/table-profile`.

---

## 5. Cluster API (2.0) — cluster picker

`GET /api/2.0/clusters/list`, `list_clusters()`, uses the **service token** (NOT a user PAT) — the
service identity is what submits the Job and picks the cluster (`existing_cluster_id`), so the picker
must reflect the clusters that identity can actually run on.

**Fields read** from each `body["clusters"][]` entry: `cluster_id`, `state`, `spark_context_id`,
`cluster_name`.

**Usable-cluster filter** (only submittable clusters survive):

1. `cluster_id` must be present.
2. `state` (upper-cased) must be in `_USABLE_CLUSTER_STATES = {RUNNING, TERMINATED}` — `RUNNING` is
   live; `TERMINATED` can be auto-started by the Jobs API. Every other state (`TERMINATING`,
   `ERROR`, `UNKNOWN`, `PENDING`, `RESTARTING`, `RESIZING`) is excluded because a submit against it
   would fail or hang.
3. A belt-and-braces guard: the cluster is live (`spark_context_id` present) **or** in one of those
   restartable states — always true for the states above, so it never removes a state-2 survivor.

Each survivor is reduced to exactly the three fields the picker needs and the list is sorted
case-insensitively by `cluster_name`:

```jsonc
[ { "cluster_id": "0421-071516-3h9grzl1",
    "cluster_name": "shared-ml",         // falls back to cluster_id when the cluster is unnamed
    "state": "RUNNING" } ]
```

If `body["clusters"]` is missing or not a list, `list_clusters` returns `[]`.

---

## 6. Unity Catalog / workspace permissions required

Grants split by **which credential makes the call** (§1). Nothing below is inferred beyond what each
call touches.

### Service token (`DATABRICKS_TOKEN`)

| Call | Minimum grants on the service principal |
|---|---|
| `POST /api/2.1/jobs/runs/submit` | `CAN_ATTACH_TO` on the target cluster (`existing_cluster_id`); `CAN_RESTART` on it too if you want a `TERMINATED` cluster auto-started. No job ACL needed — a one-off submit is owned by the submitter. |
| `GET /api/2.1/jobs/runs/get` | Ability to view the run it submitted (implicit for the submitter). |
| `GET /api/2.0/clusters/list` | Cluster **view** access — a cluster shows up only if the principal has at least `CAN_ATTACH_TO` on it (workspace admins see all). Grant `CAN_ATTACH_TO` on every cluster the picker should offer. |
| `GET /api/2.0/fs/files{...}` (read the result envelope on the output volume) | `USE CATALOG` on the output volume's catalog (`aiml_rd`) + `USE SCHEMA` on its schema (`classifyos`) + **`READ VOLUME`** on the output volume (`aiml_rd.classifyos.output`). |

> The Job **writes** its artifacts/envelope to the output volume as the **user** (the notebook sets
> `DATABRICKS_TOKEN` to the forwarded PAT), so the writing identity needs `WRITE VOLUME` on the
> output volume — that is a **user-PAT** grant, listed below, not a service-token one.

### User PAT (`X-Databricks-Token`) — UC data browsing + cluster-side data access

| Call / activity | Minimum grants on the browsing user |
|---|---|
| `GET /api/2.1/unity-catalog/catalogs` | `USE CATALOG` (or `BROWSE`) on the catalogs to be listed. |
| `GET /api/2.1/unity-catalog/schemas` | `USE CATALOG` on the catalog + `USE SCHEMA` (or `BROWSE`) on the schemas to be listed. |
| `GET /api/2.1/unity-catalog/tables` | `USE CATALOG` + `USE SCHEMA` + `SELECT` (or `BROWSE`) on the tables to be listed. |
| `GET /api/2.1/unity-catalog/tables/{full_name}` (column metadata) | `USE CATALOG` + `USE SCHEMA` + `SELECT` (or `BROWSE`) on that table. |
| Cluster-side Delta read at run time (the Job, as the user) | `USE CATALOG` + `USE SCHEMA` + **`SELECT`** on the source Delta table, and `WRITE VOLUME` on `aiml_rd.classifyos.output` (+ `READ VOLUME` on `…input`/`…libs` as the notebook uses them). |

`USE CATALOG` / `USE SCHEMA` are the traversal privileges — without them the parent object is not
even visible, so a list returns nothing. `BROWSE` grants metadata visibility without data access;
`SELECT` is required to actually read table data on the cluster.

---

## 7. Env vars that control this interface

Only the vars that affect the **FastAPI → Databricks REST** calls in `databricks.py` / `jobs.py`.
(Cluster-side vars — `DATABRICKS_HTTP_PATH`, `DBRICKS_INPUT_VOLUME`, `CLASSIFYOS_STORAGE_BACKEND`,
`MLFLOW_*` — configure the Job's own runtime, not this client; see `docs/databricks_how_it_works.md`
§2.)

| Env var | Which call(s) it affects | If unset |
|---|---|---|
| `CLASSIFYOS_EXECUTION_BACKEND` | Master gate (`execution_backend()`). Only `=databricks` (case-insensitive) turns this interface on. | Treated as `local` — none of these calls run; `/run` executes in-process and the UC picker / `/results` (databricks branch) are inert. |
| `DATABRICKS_HOST` | `base_url` for **every** call (and the `fetch_uc_file` URL). Must include `https://`. | `DatabricksConfigError` → **500** on the first call. |
| `DATABRICKS_TOKEN` | Service-token auth for `submit_run`, `get_run_status`, `list_clusters`, `fetch_uc_file`. | `DatabricksConfigError` → **500** on any service-token call. |
| `DATABRICKS_JOB_NOTEBOOK_PATH` | `notebook_task.notebook_path` in the submit payload. | `DatabricksConfigError` → **500** at submit. |
| `DATABRICKS_JOB_CLUSTER_ID` | Default `existing_cluster_id` in the submit payload (overridden by a request `cluster_id`). | If **no** request `cluster_id` either → `DatabricksConfigError` → **500** at submit. A live picker selection avoids this. |
| `DATABRICKS_JOB_WHEEL_PATH` | The `wheel_path` base_parameter **and** the `libraries: [{whl}]` entry. | Empty string: no `libraries` attached and `wheel_path=""` — the notebook must fall back to installing the wheel itself (cell 1). |
| `DATABRICKS_JOB_TIMEOUT_SECONDS` | `timeout_seconds` (the Job's wall-clock cap) in the submit payload. | Defaults to `3600` (also on a non-integer value). |
| `DBRICKS_OUTPUT_VOLUME` | Base of the `fetch_uc_file` path built by `/results` (`+ /api/{job_id}/run_response.json`). | **500** from `/run/{job_id}/results` ("DBRICKS_OUTPUT_VOLUME is not set") — status polling still works; only result fetch is blocked. |

---

## Appendix — verbatim endpoint-path check

Every Databricks endpoint path in this doc, checked against `backend/api/databricks.py`:

| Path used in this doc | In `databricks.py` | How |
|---|---|---|
| `/api/2.1/jobs/runs/submit` | ✅ verbatim | `_SUBMIT_PATH` (line 41) |
| `/api/2.1/jobs/runs/get` | ✅ verbatim | `_GET_RUN_PATH` (line 42) |
| `/api/2.1/unity-catalog/catalogs` | ✅ verbatim | `_CATALOGS_PATH` (line 43) |
| `/api/2.1/unity-catalog/schemas` | ✅ verbatim | `_SCHEMAS_PATH` (line 44) |
| `/api/2.1/unity-catalog/tables` | ✅ verbatim | `_TABLES_PATH` (line 45) |
| `/api/2.0/clusters/list` | ✅ verbatim | `_CLUSTERS_PATH` (line 47) |
| `/api/2.0/fs/files{volume_path}` | ✅ verbatim | `fetch_uc_file` URL (line 406) |
| `/api/2.1/unity-catalog/tables/{full_name}` | ✅ verbatim | appears in the `get_table_columns` docstring (line 377); the runtime path is also composed at line 389 (`f"{_TABLES_PATH}/{full_name}"`). |

**Result: no mismatches.** Every Databricks endpoint path in this doc appears verbatim in
`backend/api/databricks.py`. Two are additionally assembled at call time from a verbatim base:
the get-a-table path (`f"{_TABLES_PATH}/{full_name}"`, line 389) and the Files API per-job key
(`DBRICKS_OUTPUT_VOLUME + /api/{job_id}/run_response.json`), the latter assembled in
`routes/jobs.py` — but both endpoint *paths* still match the source exactly.
