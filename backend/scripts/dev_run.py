"""Standalone pipeline smoke-test runner (dev tool — NOT a pipeline section).

Runs the ClassifyOS pipeline built through Phase 4 (Sections 1–7B) end-to-end on a
real CSV and writes real artifacts to ``OUTPUT_DIR``, so the pipeline can be exercised
before the ``ModelRunner`` (Phase 7) exists.

This is a human convenience tool: it prints freely, reads ``backend/.env`` for the
real ``DATA_DIR``/``OUTPUT_DIR`` (the engine itself does NOT auto-load ``.env``), and
fails readably stage-by-stage instead of dumping a raw traceback (real data is messier
than synthetic). It does NOT modify any pipeline code, and it imports the same engine
modules the API and CLI will.

Usage (run from the ``backend/`` directory):

    python scripts/dev_run.py --file policy_lapse.csv --target will_lapse
    python scripts/dev_run.py --file real/claim_behaviour.csv --target had_claim \
        --problem-type binary --encoding onehot --scaling standard --balance smote

``--file`` is a path relative to ``DATA_DIR``. When ``--features`` is omitted, all
columns are used except the target and any detected ID-like / datetime columns. When
``--problem-type`` is omitted it is inferred from ``inspect_file``.
"""

from __future__ import annotations

# --- bootstrap: make the engine importable and load the real env BEFORE anything
#     that reads DATA_DIR / OUTPUT_DIR (LocalFolderStorage reads them at construction).
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

# Load backend/.env explicitly (same file the test suite loads). Without this the
# engine falls back to LocalFolderStorage's relative data/classification_output
# defaults instead of the real DATA_DIR / OUTPUT_DIR.
load_dotenv(BACKEND_DIR / ".env")

import argparse  # noqa: E402

import pandas as pd  # noqa: E402

from classifyos.analysis.feature_impact import (  # noqa: E402
    PLOT_PNG_KEY as IMPACT_PLOT_KEY,
    SUMMARY_CSV_KEY,
    analyze_feature_impact,
)
from classifyos.config import build_config  # noqa: E402
from classifyos.io.inspect import inspect_file  # noqa: E402
from classifyos.io.loader import data_loader  # noqa: E402
from classifyos.io.storage import LocalFolderStorage  # noqa: E402
from classifyos.preprocessing.features import FeatureBuilder  # noqa: E402
from classifyos.preprocessing.interactions import (  # noqa: E402
    PLOT_PNG_KEY as INTERACTION_PLOT_KEY,
    InteractionFeatureBuilder,
    plot_interaction_summary,
)
from classifyos.preprocessing.preprocess import Preprocessor  # noqa: E402
from classifyos.split import train_test_split_cls  # noqa: E402

# Distinct-value fraction at/above which a column is treated as an ID (matches the
# analyze_feature_impact id_like threshold). Such columns are excluded from the default
# feature set — they are leakage-bait and carry no generalisable signal.
_ID_LIKE_FRACTION = 0.99


# --------------------------------------------------------------------------- #
# Printing helpers (this tool is allowed to print freely).                    #
# --------------------------------------------------------------------------- #


def banner(title: str) -> None:
    """Print a clear section banner before a stage."""
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def info(msg: str) -> None:
    """Print an indented one-line result/detail."""
    print(f"    {msg}")


def stage_failed(stage: str, exc: Exception) -> None:
    """Report a readable stage failure and abort (downstream stages depend on it)."""
    print()
    print("!" * 72)
    print(f"  STAGE FAILED: {stage}")
    print(f"  {type(exc).__name__}: {exc}")
    print("!" * 72)
    sys.exit(1)


# --------------------------------------------------------------------------- #
# Small local helpers                                                          #
# --------------------------------------------------------------------------- #


def _read_for_detection(path: str, storage: LocalFolderStorage) -> pd.DataFrame:
    """Read the dataset (via the StorageAdapter) for default-feature detection only.

    Mirrors the loader's suffix dispatch. Used solely to compute per-column
    uniqueness when ``--features`` is not supplied; the real load happens in the
    ``data_loader`` stage.
    """
    suffix = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    if suffix in ("xlsx", "xls"):
        with storage.open_read(path, binary=True) as fh:
            return pd.read_excel(fh)
    if suffix in ("parquet", "pq"):
        with storage.open_read(path, binary=True) as fh:
            return pd.read_parquet(fh)
    with storage.open_read(path) as fh:
        return pd.read_csv(fh)


def _default_features(
    path: str,
    target: str,
    datetime_cols: list[str],
    storage: LocalFolderStorage,
) -> tuple[list[str], list[str]]:
    """Pick default feature columns: everything except target / datetime / ID-like.

    Returns ``(feature_cols, excluded_id_like)``.
    """
    df = _read_for_detection(path, storage)
    n_rows = len(df)
    id_like: list[str] = []
    features: list[str] = []
    for col in df.columns:
        if col == target or col in datetime_cols:
            continue
        frac = (df[col].nunique(dropna=True) / n_rows) if n_rows else 0.0
        # Treat a near-unique column as an ID only if it is NOT a continuous float:
        # object/string codes (policy_id) and integer row-IDs are leakage-bait, but a
        # continuous float (e.g. sum_assured) is naturally high-cardinality and a
        # legitimate feature — excluding it would gut the smoke test.
        is_float = pd.api.types.is_float_dtype(df[col])
        if frac >= _ID_LIKE_FRACTION and not is_float:
            id_like.append(col)
            continue
        features.append(col)
    return features, id_like


def _class_balance_str(y: pd.Series) -> str:
    """Format a target column's class counts and proportions on one line."""
    counts = y.astype(str).value_counts()
    total = int(counts.sum())
    parts = [f"{cls}={n} ({n / total:.1%})" for cls, n in counts.items()]
    return ", ".join(parts)


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the ClassifyOS pipeline (Phases 1–4) end-to-end on a real CSV "
        "and write real artifacts to OUTPUT_DIR. Development smoke-test tool.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--file",
        required=True,
        help="Path to the input dataset, relative to DATA_DIR (e.g. real/claim_behaviour.csv).",
    )
    p.add_argument("--target", required=True, help="Name of the target column.")
    p.add_argument(
        "--features",
        default=None,
        help="Comma-separated feature columns. Default: all columns except the target "
        "and any detected ID-like / datetime columns.",
    )
    p.add_argument(
        "--problem-type",
        default=None,
        choices=["binary", "multiclass", "multilabel"],
        help="Override the problem type. Default: inferred from inspect_file.",
    )
    p.add_argument("--encoding", default=None, help="Override encoding_method.")
    p.add_argument("--scaling", default=None, help="Override scaling_method.")
    p.add_argument("--balance", default=None, help="Override class_balance.")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    storage = LocalFolderStorage()
    print(f"DATA_DIR   : {storage.data_dir}")
    print(f"OUTPUT_DIR : {storage.output_dir}")
    print(f"input file : {args.file}")
    print(f"target     : {args.target}")

    written_keys: list[str] = []

    # --- stage 1: inspect ---------------------------------------------------
    banner("1. inspect_file")
    try:
        inspection = inspect_file(args.file, storage, target=args.target)
    except Exception as exc:  # noqa: BLE001 — readable failure, not a raw trace
        stage_failed("inspect_file", exc)

    info(f"rows: {inspection['n_rows']}  columns: {len(inspection['columns'])}")
    info(f"numeric:     {inspection['numeric_cols']}")
    info(f"categorical: {inspection['categorical_cols']}")
    info(f"binary:      {inspection['binary_cols']}")
    info(f"datetime:    {inspection['datetime_cols']}")
    class_dist = inspection.get("class_distribution", {})
    info(f"class_distribution[{args.target}]: {class_dist}")
    info(f"suggested_problem_type: {inspection.get('suggested_problem_type')}")

    # Logical stop conditions (not exceptions): target absent / too few classes.
    if args.target not in inspection["columns"]:
        print(f"\nSTOP: target {args.target!r} not found in the file.")
        sys.exit(1)
    if len(class_dist) < 2:
        print(
            f"\nSTOP: target {args.target!r} has {len(class_dist)} class(es); "
            "at least 2 are required to classify."
        )
        sys.exit(1)

    # --- stage 2: build_config ----------------------------------------------
    banner("2. build_config")
    try:
        if args.features:
            feature_cols = [c.strip() for c in args.features.split(",") if c.strip()]
            excluded_ids: list[str] = []
        else:
            feature_cols, excluded_ids = _default_features(
                args.file, args.target, inspection["datetime_cols"], storage
            )

        problem_type = args.problem_type or inspection.get(
            "suggested_problem_type", "binary"
        )
        overrides: dict[str, str] = {"problem_type": problem_type}
        if args.encoding:
            overrides["encoding_method"] = args.encoding
        if args.scaling:
            overrides["scaling_method"] = args.scaling
        if args.balance:
            overrides["class_balance"] = args.balance

        config = build_config(
            input_file=args.file,
            target=args.target,
            feature_cols=feature_cols,
            **overrides,
        )
    except Exception as exc:  # noqa: BLE001
        stage_failed("build_config", exc)

    if not args.features and excluded_ids:
        info(f"excluded ID-like columns from defaults: {excluded_ids}")
        info(f"(also excluded datetime columns: {inspection['datetime_cols']})")
    info(f"problem_type: {config['problem_type']}")
    info(f"encoding={config['encoding_method']}  scaling={config['scaling_method']}  "
         f"balance={config['class_balance']}")
    info(f"feature_cols ({len(feature_cols)}): {feature_cols}")

    raw_feature_count = len(feature_cols)

    # --- stage 3: data_loader -----------------------------------------------
    banner("3. data_loader")
    try:
        df = data_loader(config, storage)
    except Exception as exc:  # noqa: BLE001
        stage_failed("data_loader", exc)

    input_rows = len(df)
    info(f"loaded rows: {input_rows}  columns: {len(df.columns)}")
    info(f"class balance: {_class_balance_str(df[args.target])}")

    # --- stage 4: analyze_feature_impact ------------------------------------
    banner("4. analyze_feature_impact  ->  feature_impact_summary.csv + plot4")
    try:
        impact = analyze_feature_impact(df, config, storage)
    except Exception as exc:  # noqa: BLE001
        stage_failed("analyze_feature_impact", exc)

    written_keys.extend([SUMMARY_CSV_KEY, IMPACT_PLOT_KEY])
    info("top 5 features by composite_score:")
    for _, row in impact.head(5).iterrows():
        score = row["composite_score"]
        score_str = f"{score:.4f}" if pd.notna(score) else "nan"
        info(f"  {int(row['rank']):>2}. {row['feature']:<24} composite={score_str}")
    flagged = impact.loc[impact["id_like"], "feature"].tolist()
    if flagged:
        info(f"[!] id_like=True (leakage-bait) columns present in features: {flagged}")
    else:
        info("no id_like columns among the selected features")

    # --- stage 5: train_test_split_cls --------------------------------------
    banner("5. train_test_split_cls")
    try:
        train_df, test_df = train_test_split_cls(df, config)
    except Exception as exc:  # noqa: BLE001
        stage_failed("train_test_split_cls", exc)

    info(f"train rows: {len(train_df)}  | balance: {_class_balance_str(train_df[args.target])}")
    info(f"test  rows: {len(test_df)}  | balance: {_class_balance_str(test_df[args.target])}")

    # --- stage 6: preprocess (fit on train, transform both) -----------------
    banner("6. Preprocessor.fit_transform(train) + transform(test)")
    try:
        pre = Preprocessor(config)
        train_pre = pre.fit_transform(train_df)
        test_pre = pre.transform(test_df)
    except Exception as exc:  # noqa: BLE001
        stage_failed("preprocess", exc)

    info(f"feature count in:  {raw_feature_count}")
    info(f"feature count out: {len(pre.feature_names_out_)}")
    info(f"train_pre shape: {train_pre.shape}  test_pre shape: {test_pre.shape}")

    # --- stage 7: feature engineering + interactions ------------------------
    banner("7. FeatureBuilder + InteractionFeatureBuilder  ->  plot6")
    try:
        fb = FeatureBuilder(config)
        train_fb = fb.fit_transform(train_pre, args.target)
        test_fb = fb.transform(test_pre)

        ib = InteractionFeatureBuilder(config)
        train_final = ib.fit_transform(train_fb, args.target)
        test_final = ib.transform(test_fb)

        plot_interaction_summary(
            train_final, args.target, ib.interaction_cols_, storage
        )
    except Exception as exc:  # noqa: BLE001
        stage_failed("feature_engineering", exc)

    written_keys.append(INTERACTION_PLOT_KEY)
    info(f"FeatureBuilder created ({len(fb.created_features_)}): {fb.created_features_}")
    info(f"interaction columns ({len(ib.interaction_cols_)}): {ib.interaction_cols_}")
    info(f"train_final shape: {train_final.shape}  test_final shape: {test_final.shape}")

    final_feature_count = len([c for c in train_final.columns if c != args.target])

    # --- summary ------------------------------------------------------------
    banner("SUMMARY")
    info(f"input rows ................ {input_rows}")
    info(f"raw feature count ......... {raw_feature_count}")
    info(f"final feature count ....... {final_feature_count}")
    info(f"interaction cols created .. {len(ib.interaction_cols_)}")
    print()
    info("files written to OUTPUT_DIR:")
    for key in written_keys:
        info(f"  - {key}  ->  {storage.path_for(key, output=True)}")
    print()


if __name__ == "__main__":
    main()
