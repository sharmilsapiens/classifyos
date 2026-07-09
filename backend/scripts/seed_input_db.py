"""Seed the ClassifyOS *input* database with example tables (dev convenience — NOT pipeline code).

This is a tiny developer helper that loads two example datasets into the local input database
(the one whose SQLAlchemy DSN is held by ``CLASSIFYOS_PG_DSN`` in ``backend/.env``) so the
dashboard's **"Import from database"** picker has something to show. It is the DB twin of the
committed sample CSVs that seed ``DATA_DIR`` — a one-off setup step, not part of the pipeline.

It writes ONE table per dataset:

* ``iris``   — the classic multiclass set (sklearn ``load_iris``): four numeric measurements +
  a ``species`` target (setosa / versicolor / virginica). No file dependency — built in memory.
* ``arizona`` — the existing ``arizona_buyingpropensity`` sample (read from ``DATA_DIR`` via the
  StorageAdapter), a binary problem on the ``converted`` target.

Reads go through the ``StorageAdapter`` (the arizona CSV lives under ``DATA_DIR``); the DB write
uses ``pandas.to_sql`` over a plain SQLAlchemy engine (``psycopg2`` for Postgres — the pinned
driver). Nothing here touches the ML pipeline; it only populates the input DB.

Usage (run from the ``backend/`` directory, venv active):

    python scripts/seed_input_db.py
    python scripts/seed_input_db.py --connection-env CLASSIFYOS_PG_DSN
    python scripts/seed_input_db.py --arizona-key real/arizona_buyingpropensity.csv
    python scripts/seed_input_db.py --dsn "postgresql://user:pass@localhost:5432/classifyos_data"

Re-running is safe: each table is written with ``if_exists="replace"`` (drop + recreate), so the
seed is idempotent. The DSN is read from the environment (never hardcoded); ``--dsn`` is an escape
hatch for a one-off target and is not persisted anywhere.
"""

from __future__ import annotations

# --- bootstrap: make the engine importable and load the real env BEFORE anything reads it. ---
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

# Load backend/.env explicitly (same file the CLI + test suite load). Without this the
# StorageAdapter falls back to its relative ./data default and CLASSIFYOS_PG_DSN reads empty.
load_dotenv(BACKEND_DIR / ".env")

import argparse  # noqa: E402
import os  # noqa: E402

import pandas as pd  # noqa: E402

from classifyos.io.storage import LocalFolderStorage  # noqa: E402

#: Default table names written by this seeder (one per dataset).
IRIS_TABLE = "iris"
ARIZONA_TABLE = "arizona"
#: Default storage key (relative to DATA_DIR) for the arizona sample CSV.
DEFAULT_ARIZONA_KEY = "real/arizona_buyingpropensity.csv"


def _load_iris() -> pd.DataFrame:
    """Build the iris frame in memory (multiclass): 4 numeric features + a ``species`` target.

    Uses sklearn's bundled ``load_iris`` so there is no file dependency; column names are
    snake-cased and the integer target is mapped to its species name for a readable multiclass
    target column.
    """
    from sklearn.datasets import load_iris  # noqa: PLC0415 — local, only for this dev seeder

    bunch = load_iris(as_frame=True)
    df = bunch.frame.rename(
        columns={
            "sepal length (cm)": "sepal_length",
            "sepal width (cm)": "sepal_width",
            "petal length (cm)": "petal_length",
            "petal width (cm)": "petal_width",
        }
    )
    # Map the 0/1/2 target to species names (a friendlier multiclass target than integers).
    names = list(bunch.target_names)
    df["species"] = df["target"].map(lambda i: str(names[int(i)]))
    return df.drop(columns=["target"])


def _load_arizona(key: str, storage: LocalFolderStorage) -> pd.DataFrame:
    """Read the arizona buying-propensity sample (binary, target ``converted``) via the StorageAdapter.

    ``key`` is a logical key relative to ``DATA_DIR`` (default ``real/arizona_buyingpropensity.csv``).
    All reads go through the storage abstraction — no hardcoded path.
    """
    with storage.open_read(key) as fh:
        return pd.read_csv(fh)


def _resolve_dsn(args: argparse.Namespace) -> str:
    """Return the SQLAlchemy DSN: an explicit ``--dsn`` wins, else the ``--connection-env`` var."""
    if args.dsn:
        return args.dsn.strip()
    url = os.environ.get(args.connection_env, "").strip()
    if not url:
        raise SystemExit(
            f"connection env var {args.connection_env!r} is not set (or is empty).\n"
            f"Set it in backend/.env to a SQLAlchemy DSN, e.g.\n"
            f"  {args.connection_env}=postgresql://user:pass@localhost:5432/classifyos_data\n"
            f"or pass --dsn explicitly."
        )
    return url


def _write_table(df: pd.DataFrame, table: str, engine) -> None:
    """Write ``df`` to ``table`` (drop + recreate), then report the row/column count."""
    df.to_sql(table, engine, if_exists="replace", index=False)
    print(f"    seeded table {table!r}: {len(df)} rows x {df.shape[1]} cols")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Seed the ClassifyOS input DB with example tables (iris, arizona) so the "
        "dashboard's 'Import from database' picker has data to show. Dev convenience only.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--connection-env",
        default="CLASSIFYOS_PG_DSN",
        help="Name of the env var holding the SQLAlchemy DSN of the input DB.",
    )
    p.add_argument(
        "--dsn",
        default=None,
        help="Explicit SQLAlchemy DSN (overrides --connection-env). Not persisted anywhere.",
    )
    p.add_argument(
        "--arizona-key",
        default=DEFAULT_ARIZONA_KEY,
        help="Storage key (relative to DATA_DIR) of the arizona sample CSV.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    storage = LocalFolderStorage()
    dsn = _resolve_dsn(args)
    # Print the DSN with any password masked — never echo a credential to the console.
    safe_dsn = dsn
    if "@" in dsn and "://" in dsn:
        scheme, rest = dsn.split("://", 1)
        creds, _, host = rest.partition("@")
        if ":" in creds:
            user = creds.split(":", 1)[0]
            safe_dsn = f"{scheme}://{user}:***@{host}"

    print(f"DATA_DIR   : {storage.data_dir}")
    print(f"target DB  : {safe_dsn}")

    from sqlalchemy import create_engine  # noqa: PLC0415 — local, only for this dev seeder

    iris_df = _load_iris()
    try:
        arizona_df = _load_arizona(args.arizona_key, storage)
    except FileNotFoundError:
        raise SystemExit(
            f"could not read the arizona sample at DATA_DIR/{args.arizona_key!r}.\n"
            f"Pass --arizona-key <key> pointing at a readable arizona_buyingpropensity CSV "
            f"under DATA_DIR ({storage.data_dir})."
        ) from None

    engine = create_engine(dsn)
    try:
        print("seeding tables:")
        _write_table(iris_df, IRIS_TABLE, engine)
        _write_table(arizona_df, ARIZONA_TABLE, engine)
    finally:
        engine.dispose()

    print("done. The 'Import from database' picker will now list these tables.")


if __name__ == "__main__":
    main()
