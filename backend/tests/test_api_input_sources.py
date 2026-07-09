"""Tests for the input-source read-path endpoints (Interim 2b UI — list tables + select one).

These exercise ``GET /api/v1/input-sources/tables`` and ``POST /api/v1/input-sources/select``
WITHOUT a live Postgres: the input DB is a per-test **sqlite** file (the same trick
``test_sql_source.py`` uses — the endpoints go through a generic SQLAlchemy engine, so sqlite
exercises the identical ``list_tables`` / ``materialize_source`` path), pointed at by the
``CLASSIFYOS_PG_DSN`` env var the endpoints read. Storage is redirected to a temp dir via a
dependency override so the materialized snapshot never touches the real DATA_DIR.

Covered:

* list tables → the seeded table names (sorted);
* list tables with the DB unconfigured (env unset) → a clean **503**, not a 500;
* select a table → the ``/upload`` ``InspectProfile`` shape + the ``input_source`` block the
  frontend sets on the run, and the snapshot is materialized to DATA_DIR;
* select with the DB unavailable → **503**; a bad request (both table+query, bad target) → **422**.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


def _seed_sqlite(url: str) -> None:
    """Seed a sqlite input DB with an ``iris`` (multiclass) and an ``arizona`` (binary) table."""
    from sqlalchemy import create_engine

    engine = create_engine(url)
    pd.DataFrame(
        {
            "sepal_length": [5.1, 4.9, 6.3, 5.8, 7.1, 6.0],
            "sepal_width": [3.5, 3.0, 3.3, 2.7, 3.0, 2.2],
            "petal_length": [1.4, 1.4, 6.0, 5.1, 5.9, 4.0],
            "petal_width": [0.2, 0.2, 2.5, 1.9, 2.1, 1.0],
            "species": ["setosa", "setosa", "virginica", "virginica", "virginica", "versicolor"],
        }
    ).to_sql("iris", engine, if_exists="replace", index=False)
    pd.DataFrame(
        {"decision_days": [5, 30, 12, 7, 21, 3], "converted": [0, 1, 0, 1, 1, 0]}
    ).to_sql("arizona", engine, if_exists="replace", index=False)
    engine.dispose()


@pytest.fixture
def db_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A TestClient whose input DB is a seeded sqlite file and whose storage is a temp dir.

    Points ``CLASSIFYOS_PG_DSN`` at the sqlite DB (so the endpoints read it) and overrides the
    ``get_storage`` dependency with a throwaway-temp-dir adapter so materialized snapshots never
    land in the real DATA_DIR. Yields ``(client, storage)``.
    """
    from fastapi.testclient import TestClient

    from api.deps import get_storage
    from api.main import app
    from classifyos.io.storage import LocalFolderStorage

    url = f"sqlite:///{(tmp_path / 'input.db').as_posix()}"
    _seed_sqlite(url)
    monkeypatch.setenv("CLASSIFYOS_PG_DSN", url)

    storage = LocalFolderStorage(str(tmp_path / "data"), str(tmp_path / "out"))
    app.dependency_overrides[get_storage] = lambda: storage
    try:
        yield SimpleNamespace(client=TestClient(app), storage=storage)
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# GET /input-sources/tables                                                    #
# --------------------------------------------------------------------------- #


def test_list_tables_returns_seeded_tables(db_input) -> None:
    resp = db_input.client.get("/api/v1/input-sources/tables")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connection_env"] == "CLASSIFYOS_PG_DSN"
    assert body["tables"] == ["arizona", "iris"]  # sorted


def test_list_tables_unconfigured_is_503(db_input, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset/empty DSN is a clean 503 (store unavailable), never a 500."""
    monkeypatch.setenv("CLASSIFYOS_PG_DSN", "")  # override the fixture's sqlite DSN
    resp = db_input.client.get("/api/v1/input-sources/tables")
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# POST /input-sources/select                                                   #
# --------------------------------------------------------------------------- #


def test_select_table_profiles_and_sets_input_source(db_input) -> None:
    """Selecting a table returns the /upload profile shape + the run's input_source block."""
    resp = db_input.client.post(
        "/api/v1/input-sources/select", json={"table": "iris", "target": "species"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Same InspectProfile shape the /upload flow returns (frontend treats it like an upload).
    assert body["columns"] == [
        "sepal_length", "sepal_width", "petal_length", "petal_width", "species",
    ]
    assert body["server_path"] == "db_snapshots/iris.parquet"
    assert body["n_rows"] == 6
    assert "column_profiles" in body and "correlation" in body  # Data-Profile blocks attached
    # Target-driven fields (mirrors /upload?target=).
    assert body["suggested_problem_type"] == "multiclass"
    assert body["class_distribution"] == {"setosa": 2, "versicolor": 1, "virginica": 3}

    # The input_source block the frontend sets on the run → the actual /run reads Postgres (2b).
    assert body["input_source"] == {
        "type": "postgres",
        "connection_env": "CLASSIFYOS_PG_DSN",
        "table": "iris",
        "query": None,
    }

    # The snapshot was materialized to DATA_DIR through the StorageAdapter.
    assert db_input.storage.exists("db_snapshots/iris.parquet")


def test_select_binary_table(db_input) -> None:
    """The arizona table profiles as a binary problem on the converted target."""
    resp = db_input.client.post(
        "/api/v1/input-sources/select", json={"table": "arizona", "target": "converted"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["suggested_problem_type"] == "binary"
    assert body["input_source"]["table"] == "arizona"


def test_select_unavailable_db_is_503(db_input, monkeypatch: pytest.MonkeyPatch) -> None:
    """A DB that cannot be read at select time is a 503 (materialize failed), not a 500."""
    monkeypatch.setenv("CLASSIFYOS_PG_DSN", "")  # unset → materialize raises InputSourceError
    resp = db_input.client.post("/api/v1/input-sources/select", json={"table": "iris"})
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


def test_select_both_table_and_query_is_422(db_input) -> None:
    """Both table and query set → the engine validator rejects it as a 422 (bad request shape)."""
    resp = db_input.client.post(
        "/api/v1/input-sources/select", json={"table": "iris", "query": "SELECT * FROM iris"}
    )
    assert resp.status_code == 422
    assert "exactly one" in resp.json()["detail"].lower()


def test_select_bad_target_is_422(db_input) -> None:
    """A target absent from the materialized table → 422 (from the shared inspect path)."""
    resp = db_input.client.post(
        "/api/v1/input-sources/select", json={"table": "iris", "target": "not_a_column"}
    )
    assert resp.status_code == 422
    assert "not_a_column" in resp.json()["detail"]


def test_select_query_snapshot(db_input) -> None:
    """A raw query is materialized and profiled, keyed by a query-hash snapshot name."""
    resp = db_input.client.post(
        "/api/v1/input-sources/select",
        json={"query": "SELECT sepal_length, species FROM iris", "target": "species"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["columns"] == ["sepal_length", "species"]
    assert body["server_path"].startswith("db_snapshots/query_")
    assert body["input_source"]["query"] == "SELECT sepal_length, species FROM iris"
    assert body["input_source"]["table"] is None
