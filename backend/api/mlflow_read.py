"""Read (and snapshot) MLflow runs — the persistence READ-path for the dashboard.

Interim 2a of ``docs/databricks_integration.md`` §6.5. Phase A made ``ModelRunner`` *log* each
run to MLflow (params, per-model metrics, artifacts, one saved model per algorithm). Moving the
MLflow **backend store** to a local Postgres (configuration-only, via ``MLFLOW_TRACKING_URI`` —
no engine code change) makes those runs *survive a browser refresh and a server restart*. This
module is the READ side that finally makes that persistence visible:

* :func:`list_runs`      — summarize past runs across the (active) experiments, most-recent first.
* :func:`load_run`       — return the persisted ``/run`` envelope for one run, so the dashboard
                           can reload it **byte-identically** into the existing result pages.
* :func:`snapshot_result` — persist the API's rendered ``/run`` envelope as a run artifact (plus a
                           marker tag) so :func:`load_run` can return it verbatim.

Discipline (mirrors the engine's ``mlflow_logging``):

* **Lazy import** — ``mlflow`` is imported *inside* the functions, so importing this module (and
  starting the API) never requires a reachable tracking store.
* **Clean failure modes** — a store that is down / misconfigured raises :class:`MlflowUnavailable`
  (the route maps it to HTTP 503), and an unknown run id raises :class:`RunNotFound` (HTTP 404) —
  never an opaque 500. :func:`snapshot_result` is fully report-only (a failure just means the run
  is not reloadable) and never affects the ``/run`` response.

[RISK] leakage — this is pure read plumbing over the store the engine already wrote. It touches no
training data, fits nothing, and never feeds anything back into a model.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Snapshot artifact path/tag + the per-user owner tag live in the engine (single source) so the
# Databricks Job notebook can WRITE them from the wheel while this READ side filters/reloads by the
# SAME values — they can never drift. Cheap module import; mlflow itself stays lazily imported.
from classifyos.mlflow_logging import (
    NARRATION_CONTEXT_PATH,
    SNAPSHOT_DIR,
    SNAPSHOT_PATH,
    SNAPSHOT_TAG,
    USER_EMAIL_TAG,
)

# The execution backend gate (read per-call) decides WHICH MLflow store the read-path targets — see
# :func:`_tracking_uri`. Sibling ``api`` module; no import cycle (``api.databricks`` imports neither
# this module nor ``mlflow``), so this stays a cheap top-level import.
from .databricks import execution_backend

logger = logging.getLogger(__name__)

#: Cap on how many past runs :func:`list_runs` returns (most-recent first) — a safety bound so a
#: very large store can never return an unbounded list to the dashboard.
DEFAULT_MAX_RUNS = 200

#: MLflow artifact subdir the engine groups a run's artifact FILES (plots, CSVs, ``run_profile.json``)
#: under — see :func:`classifyos.mlflow_logging.log_run` (``artifact_path="classifyos"``). The
#: run-scoped ``/outputs/{run_id}/{name}`` endpoint reads them from here. Mirrors the engine's WRITE
#: side by convention (the engine write path is unchanged — this is an API-side reader constant); if
#: the engine ever renames that subdir, update both. The ``/run`` envelope snapshot is separate
#: (``SNAPSHOT_DIR``/``SNAPSHOT_PATH``, imported above).
ARTIFACT_SUBDIR = "classifyos"

#: The ClassifyOS MLflow experiment name. The engine default (``api`` ``MlflowConfig.experiment``) is
#: ``"classifyos"``; on Databricks the Job notebook nests it under ``/Shared/`` (managed MLflow rejects
#: a bare name when the cluster runs as a service principal — see the notebook Cell 3), so on the
#: workspace it is ``/Shared/classifyos``. Overridable via ``CLASSIFYOS_MLFLOW_EXPERIMENT`` for a custom
#: experiment. Used ONLY to SCOPE the Databricks Runs read to the ClassifyOS experiment: a workspace can
#: hold hundreds of unrelated experiments, and Databricks caps ``search_runs`` at 100 ``experiment_ids``
#: — and only the ClassifyOS experiment can hold a matching run anyway.
DEFAULT_MLFLOW_EXPERIMENT = "classifyos"


class MlflowUnavailable(RuntimeError):
    """The MLflow tracking store could not be reached or queried (→ HTTP 503)."""


class RunNotFound(LookupError):
    """No run with the given id exists in the tracking store (→ HTTP 404)."""


def _tracking_uri() -> str | None:
    """The MLflow tracking store the READ-path should target, decided PER CALL (thread-safe).

    * **Databricks backend** → ``"databricks"``: the Runs read-path must hit the workspace's
      *managed* MLflow — where the cluster Job logs runs — regardless of the FastAPI process's own
      ``MLFLOW_TRACKING_URI`` (in a Databricks deployment that env var is often still the local dev
      Postgres, which is why the Runs tab used to show the wrong store / no runs — §6.1). Returned
      per-call and passed to ``MlflowClient(tracking_uri=…)`` / ``download_artifacts(tracking_uri=…)``
      (mlflow 3.14 accepts both), so there is NO process-global ``mlflow.set_tracking_uri`` mutation
      under the shared server — thread-safe. The **service token** (``DATABRICKS_TOKEN`` +
      ``DATABRICKS_HOST`` in the FastAPI env) authenticates that read.
    * **Local backend** → ``None``: use the process's env-configured store exactly as before (the
      caller then falls back to :func:`classifyos.mlflow_logging._maybe_allow_file_store` +
      ``mlflow.get_tracking_uri()``), so local dev / CI are byte-identical.

    Read per-call via :func:`api.databricks.execution_backend` (not cached) so a test can flip the
    backend with ``monkeypatch.setenv`` and reuse the shared app.
    """
    return "databricks" if execution_backend() == "databricks" else None


def _classifyos_experiment_basename() -> str:
    """The basename of the ClassifyOS MLflow experiment to scope the Databricks Runs search by.

    Reads ``CLASSIFYOS_MLFLOW_EXPERIMENT`` (default :data:`DEFAULT_MLFLOW_EXPERIMENT`), returning just
    its final path segment, lowercased — so ``/Shared/classifyos`` and a bare ``classifyos`` both
    resolve to ``classifyos``. Read per-call (not cached) for test-friendliness.
    """
    name = (os.environ.get("CLASSIFYOS_MLFLOW_EXPERIMENT") or DEFAULT_MLFLOW_EXPERIMENT).strip()
    return name.rstrip("/").rsplit("/", 1)[-1].lower() or DEFAULT_MLFLOW_EXPERIMENT


def _is_classifyos_experiment(name: str | None) -> bool:
    """True if an MLflow experiment NAME is the ClassifyOS one (matches with or without a path prefix).

    Matched by basename, so the absolute ``/Shared/classifyos`` the Databricks Job logs under and a
    bare ``classifyos`` both count. Used to scope the Databricks Runs search to the ClassifyOS
    experiment (§6.1 follow-up: the workspace holds 100s of experiments; ``search_runs`` caps
    ``experiment_ids`` at 100, and only this experiment can hold a matching run).
    """
    base = (name or "").rstrip("/").rsplit("/", 1)[-1].lower()
    return base == _classifyos_experiment_basename()


def _client() -> Any:
    """Return an ``MlflowClient`` bound to the store the READ-path should target (lazy import).

    Databricks backend → an explicit ``MlflowClient(tracking_uri="databricks")`` (per-call, no
    process-global mutation — see :func:`_tracking_uri`). Local backend → reuses the engine's
    :func:`classifyos.mlflow_logging._maybe_allow_file_store` (the single source of truth for the
    MLflow 3.x file-store "maintenance mode" opt-out) and binds to the env-configured store, so the
    READ path can read the very same stores the engine WRITES — a bare ``file:`` store or the local
    default — not only the DB / managed stores. The opt-out only sets an env var for a file-store URI
    and never touches a ``postgresql`` / ``sqlite`` / ``http`` / ``databricks`` URI.
    """
    from classifyos.mlflow_logging import _maybe_allow_file_store  # noqa: PLC0415 — lazy
    from mlflow.tracking import MlflowClient  # noqa: PLC0415 — lazy by design

    uri = _tracking_uri()
    if uri:
        return MlflowClient(tracking_uri=uri)
    _maybe_allow_file_store()
    return MlflowClient()


def _iso(epoch_ms: int | None) -> str | None:
    """Convert MLflow's epoch-millis timestamp to a UTC ISO-8601 string (``None`` if unset)."""
    if not epoch_ms:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat()


def _summarize(run: Any, exp_names: dict[str, str]) -> dict[str, Any]:
    """Build one :class:`~api.models.RunSummary`-shaped dict from an MLflow ``Run``.

    Pure metadata — no artifact download. Model names and the best F1-weighted are derived from
    the per-model metric keys the engine logs (``<model>.<metric>``).
    """
    info = run.info
    params = run.data.params
    tags = run.data.tags
    metrics = run.data.metrics

    models = sorted({key.split(".", 1)[0] for key in metrics if "." in key})
    best_model: str | None = None
    best_value: float | None = None
    for key, value in metrics.items():
        if key.endswith(".f1_weighted") and (best_value is None or value > best_value):
            best_value, best_model = value, key.rsplit(".", 1)[0]

    return {
        "run_id": info.run_id,
        "experiment_id": info.experiment_id,
        "experiment_name": exp_names.get(info.experiment_id),
        "run_name": tags.get("mlflow.runName") or getattr(info, "run_name", None) or None,
        "status": info.status,
        "start_time": _iso(info.start_time),
        "end_time": _iso(info.end_time),
        "target": params.get("target"),
        "problem_type": params.get("problem_type") or tags.get("classifyos.problem_type"),
        "input_file": params.get("input_file") or tags.get("classifyos.input_file"),
        "algorithms": models,
        "models_logged": len(models),
        "best_metric": "f1_weighted",
        "best_value": best_value,
        "best_model": best_model,
        "reloadable": bool(tags.get(SNAPSHOT_TAG)),
    }


def list_runs(max_results: int = DEFAULT_MAX_RUNS, user_email: str | None = None) -> dict[str, Any]:
    """List past runs across the active experiments, most-recent first.

    When ``user_email`` is given (the per-user Runs view — Databricks backend), only runs tagged
    with that owner are returned, via a server-side tag filter. When ``None`` (local backend) every
    run is listed exactly as before. Returns ``{"tracking_uri": str, "runs": [RunSummary-dict, ...]}``.
    Raises :class:`MlflowUnavailable` if the store cannot be reached/queried.
    """
    try:
        import mlflow  # noqa: PLC0415 — lazy by design
        from mlflow.entities import ViewType  # noqa: PLC0415

        client = _client()
        # Report the store we ACTUALLY read from: "databricks" in the databricks backend (§6.1), else
        # the process's env-configured store. This is what the Runs tab shows as "Tracking store" —
        # so it no longer misreports the local dev Postgres when reading Databricks-managed MLflow.
        tracking_uri = _tracking_uri() or mlflow.get_tracking_uri()
        experiments = client.search_experiments()  # active experiments
        exp_names = {e.experiment_id: e.name for e in experiments}
        # Databricks: scope to the ClassifyOS experiment only. A workspace can hold hundreds of
        # unrelated experiments AND Databricks caps `search_runs` at 100 `experiment_ids` (passing
        # all of them → "Too many experiment_ids … Maximum 100"); only the ClassifyOS experiment can
        # hold a matching run anyway. Local: search every experiment (few, no cap) — unchanged.
        if _tracking_uri():
            exp_names = {eid: n for eid, n in exp_names.items() if _is_classifyos_experiment(n)}
        if not exp_names:
            return {"tracking_uri": tracking_uri, "runs": []}
        # Per-user filter (Databricks): backtick-quote the dotted tag key (verified against the
        # installed MLflow search grammar). The email is SCIM-sanitized to [A-Za-z0-9._-], so it
        # cannot break out of the quoted literal. The SERVICE token authenticates the search; the
        # email only scopes WHICH runs — so this stays thread-safe (no per-request credential swap).
        filter_string = f"tags.`{USER_EMAIL_TAG}` = '{user_email}'" if user_email else ""
        runs = client.search_runs(
            experiment_ids=list(exp_names),
            filter_string=filter_string,
            run_view_type=ViewType.ACTIVE_ONLY,
            order_by=["attributes.start_time DESC"],
            max_results=max_results,
        )
        return {
            "tracking_uri": tracking_uri,
            "runs": [_summarize(run, exp_names) for run in runs],
        }
    except Exception as exc:  # noqa: BLE001 — any store/query failure is a clean 503
        logger.warning("MLflow: list_runs failed: %s", exc)
        raise MlflowUnavailable(str(exc)) from exc


def load_run(run_id: str, user_email: str | None = None) -> dict[str, Any] | None:
    """Return the persisted ``/run`` envelope for ``run_id``, or ``None`` if it has no snapshot.

    Downloads the ``api/run_response.json`` artifact the API attached on ``/run`` and returns it
    verbatim, so the dashboard reloads a past run byte-identically. Raises :class:`RunNotFound`
    if the run id is unknown, or :class:`MlflowUnavailable` if the store cannot be reached.

    When ``user_email`` is given (per-user Runs — Databricks backend), a run tagged with a DIFFERENT
    owner is treated as :class:`RunNotFound`, so a guessed run id can't leak another user's results.
    An untagged run (legacy / local) carries no owner and is not restricted.
    """
    from mlflow.exceptions import MlflowException  # noqa: PLC0415

    client = _client()
    # 1. Confirm the run exists. Only a genuine "does not exist" is a 404 — a store that is down
    #    also raises here, and that must stay a 503 (not be mistaken for a missing run).
    try:
        run = client.get_run(run_id)
    except MlflowException as exc:
        if getattr(exc, "error_code", "") == "RESOURCE_DOES_NOT_EXIST":
            raise RunNotFound(run_id) from exc
        raise MlflowUnavailable(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — store unreachable, bad id shape, etc.
        raise MlflowUnavailable(str(exc)) from exc

    # 1b. Ownership (per-user Runs): another user's run is "not found" for this caller, so a guessed
    #     run id can't leak results. No owner tag (legacy/local) → unrestricted.
    if user_email:
        owner = run.data.tags.get(USER_EMAIL_TAG)
        if owner and owner != user_email:
            raise RunNotFound(run_id)

    # 2. Only download when the snapshot artifact is actually present (cheap listing first).
    try:
        import mlflow  # noqa: PLC0415

        present = any(a.path == SNAPSHOT_PATH for a in client.list_artifacts(run_id, SNAPSHOT_DIR))
        if not present:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            # tracking_uri is passed per-call so a Databricks-backend reload pulls the snapshot from
            # the managed MLflow (§6.1); None in the local backend = the env default (unchanged).
            local = mlflow.artifacts.download_artifacts(
                run_id=run_id, artifact_path=SNAPSHOT_PATH, dst_path=tmp, tracking_uri=_tracking_uri()
            )
            with open(local, encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as exc:  # noqa: BLE001 — download/parse failure surfaces as 503
        logger.warning("MLflow: load_run(%s) failed to read snapshot: %s", run_id, exc)
        raise MlflowUnavailable(str(exc)) from exc


def load_narration_context(run_id: str) -> dict[str, Any] | None:
    """Return the ``api/narration_context.json`` side artifact for ``run_id``, or ``None`` if absent.

    The engine logs this whole-run LLM narration context (config dataset/column context + the
    data-derived schema + sample rows) alongside the ``/run`` envelope snapshot when a run requests
    LLM narratives (see :func:`classifyos.mlflow_logging.log_run`). The off-cluster FastAPI narrate
    step reads it to rebuild the RunContext — the fields it cannot get from the ``/run`` envelope.

    Report-only: returns ``None`` on an absent artifact OR any read failure, so a run without the
    context (or an older run predating it) simply degrades to "not narratable" rather than erroring
    — the narrate route then returns the envelope unchanged. Targets the same store as
    :func:`load_run` (``tracking_uri="databricks"`` in the databricks backend, per call). Never raises.
    """
    try:
        import mlflow  # noqa: PLC0415 — lazy by design

        client = _client()
        present = any(
            a.path == NARRATION_CONTEXT_PATH
            for a in client.list_artifacts(run_id, SNAPSHOT_DIR)
        )
        if not present:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            local = mlflow.artifacts.download_artifacts(
                run_id=run_id,
                artifact_path=NARRATION_CONTEXT_PATH,
                dst_path=tmp,
                tracking_uri=_tracking_uri(),
            )
            with open(local, encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as exc:  # noqa: BLE001 — report-only; absent context / any failure → None
        logger.warning("MLflow: load_narration_context(%s) failed: %s", run_id, exc)
        return None


def load_artifact(run_id: str, name: str) -> tuple[bytes, str]:
    """Download ONE artifact FILE (a plot PNG or a CSV) from an MLflow run; return ``(data, filename)``.

    The engine logs a run's artifact files under the :data:`ARTIFACT_SUBDIR` (``classifyos/``) subdir
    (see :func:`classifyos.mlflow_logging.log_run`), so this reads ``{ARTIFACT_SUBDIR}/{name}`` from
    the run. In the Databricks backend the download targets the workspace's managed MLflow
    (``tracking_uri="databricks"``, passed PER CALL — thread-safe, no process-global mutation); in
    the local backend it reads the process's env-configured store, exactly like :func:`load_run`.

    This backs ``GET /api/v1/outputs/{run_id}/{name}`` so a Databricks run's PNGs/CSVs display in the
    dashboard: those files live in MLflow (+ the UC output volume), NOT the FastAPI's local
    ``OUTPUT_DIR``, which is why the flat ``/outputs/{name}`` 404s them (§6.2). [RISK] the
    ``<img>``/``<a>`` request cannot carry the user PAT, so isolation here is the unguessable 32-hex
    MLflow run id + the service token (app-level), not a per-user ACL — see
    ``docs/databricks_wisdom.md`` §6.2.

    Raises :class:`RunNotFound` (unknown run or the artifact file is absent → HTTP 404) or
    :class:`MlflowUnavailable` (store unreachable / any other download failure → HTTP 503) — never an
    opaque 500. [RISK] leakage — pure read plumbing; downloads an already-logged file, fits nothing.
    """
    from mlflow.exceptions import MlflowException  # noqa: PLC0415

    import mlflow  # noqa: PLC0415 — lazy by design

    artifact_path = f"{ARTIFACT_SUBDIR}/{name}"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            local = mlflow.artifacts.download_artifacts(
                run_id=run_id, artifact_path=artifact_path, dst_path=tmp, tracking_uri=_tracking_uri()
            )
            with open(local, "rb") as fh:
                return fh.read(), Path(local).name
    except MlflowException as exc:
        # A genuinely absent run/artifact is a 404; anything else (store down, auth) stays a 503.
        if getattr(exc, "error_code", "") == "RESOURCE_DOES_NOT_EXIST":
            raise RunNotFound(f"{run_id}/{name}") from exc
        raise MlflowUnavailable(str(exc)) from exc
    except (FileNotFoundError, IsADirectoryError) as exc:
        # download_artifacts surfaces a missing artifact path as an OSError-family error on some stores.
        raise RunNotFound(f"{run_id}/{name}") from exc
    except Exception as exc:  # noqa: BLE001 — any other failure is a clean 503, never a 500
        logger.warning("MLflow: load_artifact(%s, %s) failed: %s", run_id, name, exc)
        raise MlflowUnavailable(str(exc)) from exc


def snapshot_result(run_id: str, envelope: dict[str, Any]) -> bool:
    """Persist the rendered ``/run`` envelope as a run artifact + marker tag. Report-only.

    Thin wrapper over the engine's :func:`classifyos.mlflow_logging.snapshot_envelope` (the single
    source, also used by the Databricks Job notebook so it can write from the wheel). The local
    ``/run`` route logs no owner tag — per-user Runs is a Databricks-backend concern — so
    ``user_email`` is omitted here. NEVER raises; the ``/run`` response is unaffected.

    Routes the write to the SAME store the read-path reads (``_tracking_uri()`` — ``"databricks"`` in
    the databricks backend, per call, thread-safe; ``None`` locally = the env store). This matters for
    the narrate step's RE-persist of the narrated envelope: it must overwrite the ``api/run_response.json``
    that ``load_run`` reloads in the workspace's managed MLflow (§6.1), not the FastAPI process's own
    (possibly stale local) store. The local ``/run`` route is unchanged (``_tracking_uri()`` is ``None``).
    """
    from classifyos.mlflow_logging import snapshot_envelope  # noqa: PLC0415 — lazy

    return snapshot_envelope(run_id, envelope, tracking_uri=_tracking_uri())
