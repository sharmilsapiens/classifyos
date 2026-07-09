"""Tests for the opt-in Postgres input source (Interim 2b — materialize-to-file, Option B).

What is covered:

* **Config validation** of the ``input_source`` block (the API forwards to ``build_config``, the
  authoritative validator — a bad value → ``ValueError`` → HTTP 422).
* **The pure ``materialize_source`` helper** against a **sqlite** DSN. The helper is a generic
  SQLAlchemy engine, so no live Postgres is needed in CI (sqlite exercises the very same
  ``create_engine`` → ``read_sql`` → snapshot-write path); a real Postgres run is verified live and
  recorded in PROJECT_STATE.md. Writes a parquet and a csv snapshot and round-trips each through
  ``data_loader``.
* **Report-clean failure modes** — an unset connection env var, an empty result, and a bad DSN all
  raise :class:`InputSourceError` (never an opaque error).
* **End-to-end equivalence** — a full ``ModelRunner`` run with ``input_source=postgres`` produces
  metrics **identical** to the same run reading the original CSV directly (the core acceptance
  check: materialize-to-file changes nothing downstream).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from classifyos.config import build_config
from classifyos.io.loader import data_loader
from classifyos.io.sql_source import InputSourceError, list_tables, materialize_source
from classifyos.io.storage import LocalFolderStorage
from classifyos.runner import ModelRunner

# A small numeric feature subset keeps the end-to-end run cheap while staying realistic.
LAPSE_FEATURES = [
    "age",
    "annual_premium",
    "num_late_payments",
    "policy_tenure_years",
    "claims_count",
]


# --------------------------------------------------------------------------- #
# config validation (build_config is the authoritative validator → 422)       #
# --------------------------------------------------------------------------- #


def test_build_config_defaults_input_source_file() -> None:
    cfg = build_config("f.csv", "t", ["a"])
    assert cfg["input_source"] == {
        "type": "file",
        "connection_env": "CLASSIFYOS_PG_DSN",
        "table": None,
        "query": None,
    }


def test_build_config_accepts_postgres_table() -> None:
    cfg = build_config(
        "snap.parquet",
        "t",
        ["a"],
        input_source={"type": "postgres", "connection_env": "X", "table": "schema.policy_lapse"},
    )
    assert cfg["input_source"]["type"] == "postgres"
    assert cfg["input_source"]["table"] == "schema.policy_lapse"


def test_build_config_accepts_postgres_query_csv() -> None:
    cfg = build_config(
        "snap.csv",
        "t",
        ["a"],
        input_source={"type": "postgres", "connection_env": "X", "query": "SELECT * FROM t"},
    )
    assert cfg["input_source"]["query"] == "SELECT * FROM t"


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-dict",
        {"type": "bogus"},                                                 # unknown type
        {"type": "postgres", "connection_env": "X"},                       # neither table nor query
        {"type": "postgres", "connection_env": "X", "table": "t", "query": "q"},  # both
        {"type": "postgres", "table": "t"},                                # no connection_env
        {"type": "postgres", "connection_env": "", "table": "t"},          # empty connection_env
        {"type": "postgres", "connection_env": "X", "table": "a; DROP TABLE b"},  # unsafe identifier
    ],
)
def test_build_config_bad_input_source_raises(bad) -> None:
    with pytest.raises(ValueError):
        build_config("snap.parquet", "t", ["a"], input_source=bad)


def test_build_config_postgres_requires_parquet_or_csv_destination() -> None:
    with pytest.raises(ValueError, match="parquet"):
        build_config(
            "snap.xlsx",
            "t",
            ["a"],
            input_source={"type": "postgres", "connection_env": "X", "table": "t"},
        )


# --------------------------------------------------------------------------- #
# materialize_source — sqlite DSN (no live Postgres needed)                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def temp_storage(tmp_path: Path) -> LocalFolderStorage:
    """A storage whose input+output roots are throwaway temp dirs (no real DATA_DIR touched)."""
    return LocalFolderStorage(
        data_dir=str(tmp_path / "data"), output_dir=str(tmp_path / "out")
    )


def _sqlite_url(tmp_path: Path) -> str:
    """A SQLAlchemy sqlite URL for a temp DB file (forward slashes for Windows)."""
    return f"sqlite:///{(tmp_path / 'src.db').as_posix()}"


def _seed_sqlite(url: str, df: pd.DataFrame, table: str) -> None:
    from sqlalchemy import create_engine

    engine = create_engine(url)
    df.to_sql(table, engine, if_exists="replace", index=False)
    engine.dispose()


def test_materialize_file_source_is_noop(temp_storage: LocalFolderStorage) -> None:
    """The default file source returns input_file unchanged and writes nothing."""
    cfg = build_config("x.csv", "t", ["a"])
    assert materialize_source(cfg, temp_storage) == "x.csv"
    assert list(temp_storage.list()) == []


def test_materialize_postgres_table_parquet_roundtrip(
    tmp_path: Path, temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"], "will_lapse": [0, 1, 0]})
    url = _sqlite_url(tmp_path)
    _seed_sqlite(url, df, "policy")
    monkeypatch.setenv("TEST_DSN", url)

    cfg = build_config(
        "snap.parquet",
        "will_lapse",
        ["a", "b"],
        input_source={"type": "postgres", "connection_env": "TEST_DSN", "table": "policy"},
    )
    key = materialize_source(cfg, temp_storage)
    assert key == "snap.parquet"
    assert temp_storage.exists("snap.parquet")

    # data_loader reads the snapshot exactly as a normal file (leakage discipline unchanged).
    loaded = data_loader(cfg, temp_storage)
    assert list(loaded.columns) == ["a", "b", "will_lapse"]
    assert len(loaded) == 3


def test_materialize_postgres_query_csv_applies_filter(
    tmp_path: Path, temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    df = pd.DataFrame({"a": [1, 2, 3, 4], "y": [0, 1, 0, 1]})
    url = _sqlite_url(tmp_path)
    _seed_sqlite(url, df, "t")
    monkeypatch.setenv("TEST_DSN", url)

    cfg = build_config(
        "snap.csv",
        "y",
        ["a"],
        input_source={
            "type": "postgres",
            "connection_env": "TEST_DSN",
            "query": "SELECT a, y FROM t WHERE a <= 3",
        },
    )
    materialize_source(cfg, temp_storage)
    loaded = data_loader(cfg, temp_storage)
    assert len(loaded) == 3  # the query's WHERE clause was honoured


def test_materialize_unset_connection_env_raises(
    temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MISSING_DSN", raising=False)
    cfg = build_config(
        "snap.parquet",
        "t",
        ["a"],
        input_source={"type": "postgres", "connection_env": "MISSING_DSN", "table": "t"},
    )
    with pytest.raises(InputSourceError, match="MISSING_DSN"):
        materialize_source(cfg, temp_storage)


def test_materialize_empty_result_raises(
    tmp_path: Path, temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    df = pd.DataFrame({"a": [1, 2], "y": [0, 1]})
    url = _sqlite_url(tmp_path)
    _seed_sqlite(url, df, "t")
    monkeypatch.setenv("TEST_DSN", url)
    cfg = build_config(
        "snap.parquet",
        "y",
        ["a"],
        input_source={
            "type": "postgres",
            "connection_env": "TEST_DSN",
            "query": "SELECT * FROM t WHERE a < 0",
        },
    )
    with pytest.raises(InputSourceError, match="no rows"):
        materialize_source(cfg, temp_storage)


def test_materialize_bad_dsn_raises(
    temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_DSN", "not-a-valid-url")
    cfg = build_config(
        "snap.parquet",
        "t",
        ["a"],
        input_source={"type": "postgres", "connection_env": "TEST_DSN", "table": "t"},
    )
    with pytest.raises(InputSourceError):
        materialize_source(cfg, temp_storage)


# --------------------------------------------------------------------------- #
# list_tables — read-only introspection for the "Import from database" picker  #
# --------------------------------------------------------------------------- #


def test_list_tables_returns_seeded_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """list_tables returns the table names in the DB named by the connection env var (sorted)."""
    url = _sqlite_url(tmp_path)
    _seed_sqlite(url, pd.DataFrame({"a": [1]}), "beta")
    _seed_sqlite(url, pd.DataFrame({"a": [1]}), "alpha")
    monkeypatch.setenv("TEST_DSN", url)
    assert list_tables("TEST_DSN") == ["alpha", "beta"]


def test_list_tables_unset_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset connection env var raises InputSourceError (the route maps it to a 503)."""
    monkeypatch.delenv("MISSING_DSN", raising=False)
    with pytest.raises(InputSourceError, match="MISSING_DSN"):
        list_tables("MISSING_DSN")


def test_list_tables_bad_dsn_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable/bad DSN raises InputSourceError rather than an opaque driver error."""
    monkeypatch.setenv("TEST_DSN", "not-a-valid-url")
    with pytest.raises(InputSourceError):
        list_tables("TEST_DSN")


# --------------------------------------------------------------------------- #
# end-to-end equivalence — postgres source == reading the CSV directly        #
# --------------------------------------------------------------------------- #


def test_end_to_end_postgres_source_matches_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full run with input_source=postgres yields the SAME metrics as the direct CSV run.

    The sqlite table is seeded from the very same ``pd.read_csv`` frame the direct run also loads,
    and the snapshot is written as typed Parquet — so the materialized data is bit-identical and
    the deterministic (random_state=42) pipeline produces identical per-model metrics. This is the
    Interim-2b acceptance check at the engine level (a live Postgres run is verified separately).
    """
    src_csv = Path(os.environ["DATA_DIR"]) / "policy_lapse.csv"
    frame = pd.read_csv(src_csv)

    # Temp storage with a copy of the CSV in its input root (never touches the real DATA_DIR).
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy(src_csv, data_dir / "policy_lapse.csv")

    url = _sqlite_url(tmp_path)
    _seed_sqlite(url, frame, "policy_lapse")
    monkeypatch.setenv("TEST_DSN", url)

    common = dict(
        problem_type="binary",
        algorithms=["LogisticRegression"],
        class_balance="none",
        interaction_features={"max_auto_pairs": 0},
        random_state=42,
    )

    file_storage = LocalFolderStorage(str(data_dir), str(tmp_path / "out_csv"))
    file_cfg = build_config("policy_lapse.csv", "will_lapse", LAPSE_FEATURES, **common)
    file_runner = ModelRunner(file_cfg, file_storage).run()

    pg_storage = LocalFolderStorage(str(data_dir), str(tmp_path / "out_pg"))
    pg_cfg = build_config(
        "pg_snapshot.parquet",
        "will_lapse",
        LAPSE_FEATURES,
        input_source={"type": "postgres", "connection_env": "TEST_DSN", "table": "policy_lapse"},
        **common,
    )
    pg_runner = ModelRunner(pg_cfg, pg_storage).run()

    file_metrics = file_runner.metrics_df_.set_index("model")
    pg_metrics = pg_runner.metrics_df_.set_index("model")
    for metric in ("accuracy", "f1_weighted", "roc_auc", "pr_auc", "mcc", "log_loss"):
        assert pg_metrics.loc["LogisticRegression", metric] == pytest.approx(
            file_metrics.loc["LogisticRegression", metric], rel=1e-9, abs=1e-12
        ), metric
