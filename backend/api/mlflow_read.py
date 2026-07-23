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
import tempfile
from datetime import datetime, timezone
from typing import Any

# Snapshot artifact path/tag + the per-user owner tag live in the engine (single source) so the
# Databricks Job notebook can WRITE them from the wheel while this READ side filters/reloads by the
# SAME values — they can never drift. Cheap module import; mlflow itself stays lazily imported.
from classifyos.mlflow_logging import (
    SNAPSHOT_DIR,
    SNAPSHOT_PATH,
    SNAPSHOT_TAG,
    USER_EMAIL_TAG,
)

logger = logging.getLogger(__name__)

#: Cap on how many past runs :func:`list_runs` returns (most-recent first) — a safety bound so a
#: very large store can never return an unbounded list to the dashboard.
DEFAULT_MAX_RUNS = 200


class MlflowUnavailable(RuntimeError):
    """The MLflow tracking store could not be reached or queried (→ HTTP 503)."""


class RunNotFound(LookupError):
    """No run with the given id exists in the tracking store (→ HTTP 404)."""


def _client() -> Any:
    """Return an ``MlflowClient`` bound to the env-configured tracking store (lazy import).

    Reuses the engine's :func:`classifyos.mlflow_logging._maybe_allow_file_store` (the single
    source of truth for the MLflow 3.x file-store "maintenance mode" opt-out) so the READ path
    can read the very same stores the engine WRITES — a bare ``file:`` store or the local default
    — not only the DB / managed stores. It only sets an env var for a file-store URI and never
    touches a ``postgresql`` / ``sqlite`` / ``http`` / ``databricks`` URI.
    """
    from classifyos.mlflow_logging import _maybe_allow_file_store  # noqa: PLC0415 — lazy
    from mlflow.tracking import MlflowClient  # noqa: PLC0415 — lazy by design

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
        tracking_uri = mlflow.get_tracking_uri()
        experiments = client.search_experiments()  # active experiments
        exp_names = {e.experiment_id: e.name for e in experiments}
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
            local = mlflow.artifacts.download_artifacts(
                run_id=run_id, artifact_path=SNAPSHOT_PATH, dst_path=tmp
            )
            with open(local, encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as exc:  # noqa: BLE001 — download/parse failure surfaces as 503
        logger.warning("MLflow: load_run(%s) failed to read snapshot: %s", run_id, exc)
        raise MlflowUnavailable(str(exc)) from exc


def snapshot_result(run_id: str, envelope: dict[str, Any]) -> bool:
    """Persist the rendered ``/run`` envelope as a run artifact + marker tag. Report-only.

    Thin wrapper over the engine's :func:`classifyos.mlflow_logging.snapshot_envelope` (the single
    source, also used by the Databricks Job notebook so it can write from the wheel). The local
    ``/run`` route logs no owner tag — per-user Runs is a Databricks-backend concern — so
    ``user_email`` is omitted here. NEVER raises; the ``/run`` response is unaffected.
    """
    from classifyos.mlflow_logging import snapshot_envelope  # noqa: PLC0415 — lazy

    return snapshot_envelope(run_id, envelope)
