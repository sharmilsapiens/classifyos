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
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from classifyos.config import build_config
from classifyos.io.loader import data_loader
from classifyos.io.sql_source import (
    InputSourceError,
    list_tables,
    materialize_delta_source,
    materialize_source,
)
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
        # Delta (Databricks §6.6 Step 4) fields — default None, ignored for file/postgres.
        "catalog": None,
        "schema": None,
        "limit": None,
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


# --------------------------------------------------------------------------- #
# Delta input source (Databricks §6.6 Step 4) — PySpark is mocked entirely.    #
# NEVER contacts a real cluster/SparkSession; a live smoke test is the         #
# notebooks/classifyos_smoke_test.py notebook (documentation/tooling).         #
# --------------------------------------------------------------------------- #


class _FakeSparkDF:
    """Stand-in for a Spark DataFrame: only the two methods the materializer uses."""

    def __init__(self, pdf: pd.DataFrame) -> None:
        self._pdf = pdf

    def limit(self, num: int) -> "_FakeSparkDF":
        return _FakeSparkDF(self._pdf.head(int(num)))

    def toPandas(self) -> pd.DataFrame:  # noqa: N802 — mirrors the PySpark API name
        return self._pdf.copy()


class _FakeSpark:
    """Stand-in SparkSession: records calls and returns seeded frames for table()/sql()."""

    def __init__(
        self,
        tables: dict[str, pd.DataFrame] | None = None,
        query_result: pd.DataFrame | None = None,
    ) -> None:
        self._tables = tables or {}
        self._query_result = query_result
        self.calls: list[tuple[str, str]] = []

    def table(self, name: str) -> _FakeSparkDF:
        self.calls.append(("table", name))
        return _FakeSparkDF(self._tables[name])

    def sql(self, query: str) -> _FakeSparkDF:
        self.calls.append(("sql", query))
        return _FakeSparkDF(self._query_result)


def _install_fake_pyspark(monkeypatch: pytest.MonkeyPatch, active_session: object) -> None:
    """Inject a minimal fake ``pyspark.sql`` whose ``SparkSession.getActiveSession()`` returns
    ``active_session`` (pass ``None`` to simulate "no active session"). No real Spark involved.
    """

    class FakeSparkSession:
        @staticmethod
        def getActiveSession() -> object:  # noqa: N802 — mirrors the PySpark API name
            return active_session

    sql_mod = types.ModuleType("pyspark.sql")
    sql_mod.SparkSession = FakeSparkSession  # type: ignore[attr-defined]
    root_mod = types.ModuleType("pyspark")
    root_mod.sql = sql_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyspark", root_mod)
    monkeypatch.setitem(sys.modules, "pyspark.sql", sql_mod)


# --- config validation (build_config is the authoritative validator → 422) --------------


@pytest.mark.parametrize(
    "src",
    [
        {"type": "delta", "table": "policy_lapse"},
        {"type": "delta", "catalog": "main", "schema": "insurance", "table": "policy_lapse"},
        {"type": "delta", "query": "SELECT * FROM main.insurance.policy_lapse"},
        {"type": "delta", "table": "policy_lapse", "limit": 5000},
    ],
)
def test_build_config_accepts_delta(src) -> None:
    cfg = build_config("snap.parquet", "t", ["a"], input_source=src)
    assert cfg["input_source"]["type"] == "delta"


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "delta"},                                        # neither table nor query
        {"type": "delta", "table": "a; DROP TABLE b"},            # unsafe table identifier
        {"type": "delta", "catalog": "main; DROP", "table": "t"},  # unsafe catalog identifier
        {"type": "delta", "schema": "bad-schema", "table": "t"},   # unsafe schema identifier
        {"type": "delta", "table": "t", "limit": 0},               # non-positive limit
        {"type": "delta", "table": "t", "limit": -5},              # negative limit
        {"type": "delta", "table": "t", "limit": "5000"},          # limit not an int
    ],
)
def test_build_config_bad_delta_raises(bad) -> None:
    with pytest.raises(ValueError):
        build_config("snap.parquet", "t", ["a"], input_source=bad)


def test_build_config_delta_requires_parquet_or_csv_destination() -> None:
    with pytest.raises(ValueError, match="parquet"):
        build_config(
            "snap.xlsx", "t", ["a"], input_source={"type": "delta", "table": "t"}
        )


# --- materialize_delta_source — mocked PySpark, never a real cluster --------------------


def test_materialize_delta_file_source_is_noop(temp_storage: LocalFolderStorage) -> None:
    """The default file source is a complete no-op — nothing runs, nothing is written."""
    cfg = build_config("x.csv", "t", ["a"])
    assert materialize_delta_source(cfg, temp_storage) is None
    assert list(temp_storage.list()) == []


def test_materialize_delta_no_pyspark_raises(
    temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A local run (no PySpark installed) raises a clear InputSourceError, never a crash."""
    monkeypatch.setitem(sys.modules, "pyspark", None)  # force the lazy import to fail
    monkeypatch.setitem(sys.modules, "pyspark.sql", None)
    cfg = build_config(
        "snap.parquet",
        "t",
        ["a"],
        input_source={"type": "delta", "catalog": "main", "schema": "ins", "table": "policy"},
    )
    with pytest.raises(InputSourceError, match="PySpark"):
        materialize_delta_source(cfg, temp_storage)


def test_materialize_delta_no_active_session_raises(
    temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PySpark present but no active SparkSession (i.e. off a cluster) → InputSourceError."""
    _install_fake_pyspark(monkeypatch, active_session=None)
    cfg = build_config(
        "snap.parquet", "t", ["a"], input_source={"type": "delta", "table": "policy"}
    )
    with pytest.raises(InputSourceError, match="SparkSession"):
        materialize_delta_source(cfg, temp_storage)


def test_materialize_delta_no_table_or_query_at_runtime_raises(
    temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hand-built config that bypassed build_config still fails cleanly (defensive branch)."""
    _install_fake_pyspark(monkeypatch, active_session=_FakeSpark())
    cfg = {"input_file": "snap.parquet", "input_source": {"type": "delta"}}
    with pytest.raises(InputSourceError, match="either"):
        materialize_delta_source(cfg, temp_storage)


def test_materialize_delta_table_parquet_roundtrip(
    temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A table read materializes a Parquet snapshot that data_loader reads back unchanged."""
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"], "will_lapse": [0, 1, 0]})
    spark = _FakeSpark(tables={"main.insurance.policy_lapse": df})
    _install_fake_pyspark(monkeypatch, active_session=spark)

    cfg = build_config(
        "snap.parquet",
        "will_lapse",
        ["a", "b"],
        input_source={
            "type": "delta",
            "catalog": "main",
            "schema": "insurance",
            "table": "policy_lapse",
        },
    )
    materialize_delta_source(cfg, temp_storage)

    assert ("table", "main.insurance.policy_lapse") in spark.calls
    assert temp_storage.exists("snap.parquet")
    loaded = data_loader(cfg, temp_storage)
    assert list(loaded.columns) == ["a", "b", "will_lapse"]
    assert len(loaded) == 3


def test_materialize_delta_applies_limit(
    temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The optional row cap is pushed down to Spark (sdf.limit) before materializing."""
    df = pd.DataFrame({"a": list(range(10)), "y": [0, 1] * 5})
    spark = _FakeSpark(tables={"t": df})
    _install_fake_pyspark(monkeypatch, active_session=spark)

    cfg = build_config(
        "snap.parquet", "y", ["a"], input_source={"type": "delta", "table": "t", "limit": 4}
    )
    materialize_delta_source(cfg, temp_storage)
    loaded = data_loader(cfg, temp_storage)
    assert len(loaded) == 4


def test_materialize_delta_query_csv(
    temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raw query is run via spark.sql and materialized to the CSV snapshot destination."""
    df = pd.DataFrame({"a": [1, 2], "y": [0, 1]})
    spark = _FakeSpark(query_result=df)
    _install_fake_pyspark(monkeypatch, active_session=spark)

    cfg = build_config(
        "snap.csv",
        "y",
        ["a"],
        input_source={"type": "delta", "query": "SELECT a, y FROM main.ins.t"},
    )
    materialize_delta_source(cfg, temp_storage)
    assert ("sql", "SELECT a, y FROM main.ins.t") in spark.calls
    loaded = data_loader(cfg, temp_storage)
    assert len(loaded) == 2


def test_materialize_delta_empty_result_raises(
    temp_storage: LocalFolderStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty table/query result raises InputSourceError rather than writing an empty snapshot."""
    spark = _FakeSpark(tables={"t": pd.DataFrame({"a": [], "y": []})})
    _install_fake_pyspark(monkeypatch, active_session=spark)
    cfg = build_config(
        "snap.parquet", "y", ["a"], input_source={"type": "delta", "table": "t"}
    )
    with pytest.raises(InputSourceError, match="no rows"):
        materialize_delta_source(cfg, temp_storage)
