"""Section 16 — the ClassifyOS command-line interface.

A thin, readable wrapper around :class:`~classifyos.runner.ModelRunner` so the whole
engine can be driven from a terminal without the API:

    python -m classifyos.cli --file policy_lapse.csv --target will_lapse
    python -m classifyos.cli --file risk_tier.csv --target risk_tier \\
        --problem-type multiclass --algos LR,RF,LGBM --balance class_weight
    python -m classifyos.cli --file fraud_claims.csv --target is_fraud --inspect

Two modes:

* ``--inspect`` — run :func:`classifyos.io.inspect.inspect_file` and print the column
  profile + class distribution. No model run, nothing written.
* default (run) — build a config, run :class:`ModelRunner`, then print a per-model metrics
  summary table and the list of files written to ``OUTPUT_DIR``.

[MANDATORY] :func:`load_dotenv` is called at startup. The engine does NOT auto-load
``backend/.env``; without this call :class:`LocalFolderStorage` would fall back to its
relative ``data`` / ``classification_output`` defaults instead of the configured
``DATA_DIR`` / ``OUTPUT_DIR`` (see PROJECT_STATE.md / CLAUDE.md). ``--output-dir`` may
override ``OUTPUT_DIR`` for a single invocation.
"""

from __future__ import annotations

import argparse
import copy
import sys
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from .config import DEFAULT_CONFIG, build_config
from .io.inspect import inspect_file
from .io.storage import LocalFolderStorage, StorageAdapter
from .runner import ModelRunner

#: Distinct-value fraction at/above which a non-float column is treated as an ID and
#: excluded from the default feature set (matches the feature-impact id_like threshold).
_ID_LIKE_FRACTION = 0.99


# --------------------------------------------------------------------------- #
# argument parsing                                                            #
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    p = argparse.ArgumentParser(
        prog="classifyos",
        description="Run the ClassifyOS classification pipeline end to end on a dataset.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--file",
        required=True,
        help="Input dataset key, relative to DATA_DIR (e.g. policy_lapse.csv).",
    )
    p.add_argument("--target", required=True, help="Target column name.")
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
        help="Problem type. Default: inferred from inspect_file (binary vs multiclass).",
    )
    p.add_argument(
        "--test-size", type=float, default=None, help="Test fraction in (0, 0.5]."
    )
    p.add_argument(
        "--algos",
        default=None,
        help="Comma-separated algorithm names or aliases (e.g. LR,RF,XGB). "
        "Default: the config default (LogisticRegression,RandomForest,XGBoost).",
    )
    p.add_argument("--balance", default=None, help="class_balance override "
                   "(smote|undersample|class_weight|none).")
    p.add_argument("--encoding", default=None, help="encoding_method override.")
    p.add_argument("--scaling", default=None, help="scaling_method override.")
    # -- hyperparameter tuning (Section 8B; Optuna). OFF unless --tune is given. --
    p.add_argument(
        "--tune",
        action="store_true",
        help="Enable Optuna hyperparameter tuning before each model is fit (OFF by "
        "default). Multiplies fit cost; tree models benefit most.",
    )
    p.add_argument(
        "--tune-models",
        default=None,
        help="Comma-separated models to tune (names/aliases). Default when --tune is "
        "set: all algorithms in the run.",
    )
    p.add_argument(
        "--tune-metric",
        default=None,
        help="Metric to optimise (e.g. f1_weighted, roc_auc, mcc). Default: f1_weighted.",
    )
    p.add_argument(
        "--trials", type=int, default=None, help="Optuna trials per model (default 30)."
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Per-model tuning timeout in seconds (default: no timeout).",
    )
    p.add_argument(
        "--tune-cv-folds",
        type=int,
        default=None,
        help="CV folds used to score each trial within the train split (default 3).",
    )
    p.add_argument(
        "--inspect",
        action="store_true",
        help="Inspect-only: print the column/class profile and exit (no run).",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Override OUTPUT_DIR for this run (where artifacts are written).",
    )
    return p


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _read_for_detection(path: str, storage: StorageAdapter) -> pd.DataFrame:
    """Read the dataset via the StorageAdapter for default-feature detection only."""
    suffix = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    if suffix in ("xlsx", "xls"):
        with storage.open_read(path, binary=True) as fh:
            return pd.read_excel(fh)
    if suffix in ("parquet", "pq"):
        with storage.open_read(path, binary=True) as fh:
            return pd.read_parquet(fh)
    with storage.open_read(path) as fh:
        return pd.read_csv(fh)


def default_features(
    path: str,
    target: str,
    datetime_cols: list[str],
    storage: StorageAdapter,
) -> tuple[list[str], list[str]]:
    """Pick default features: every column except target / datetime / ID-like.

    A near-unique column is treated as an ID (and excluded) only when it is NOT a
    continuous float: object/string codes and integer row-IDs are leakage-bait, but a
    high-cardinality float (e.g. ``sum_assured``) is a legitimate feature.

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
        is_float = pd.api.types.is_float_dtype(df[col])
        if frac >= _ID_LIKE_FRACTION and not is_float:
            id_like.append(col)
            continue
        features.append(col)
    return features, id_like


def _build_tuning_override(args: argparse.Namespace) -> dict[str, Any]:
    """Assemble a complete ``tuning`` sub-dict from the CLI flags (``--tune`` was given).

    Starts from the config defaults so the stored config (and the run_profile audit) always
    carries every tuning key, then overlays the flags the user set. An empty ``models`` list
    means "tune every algorithm in the run" (handled by the tuner).
    """
    tuning = copy.deepcopy(DEFAULT_CONFIG["tuning"])
    tuning["enabled"] = True
    if args.tune_models:
        tuning["models"] = [m.strip() for m in args.tune_models.split(",") if m.strip()]
    if args.tune_metric:
        tuning["metric"] = args.tune_metric
    if args.trials is not None:
        tuning["n_trials"] = args.trials
    if args.timeout is not None:
        tuning["timeout_seconds"] = args.timeout
    if args.tune_cv_folds is not None:
        tuning["cv_folds"] = args.tune_cv_folds
    return tuning


def _print_inspection(inspection: dict[str, Any], target: str) -> None:
    """Pretty-print the ``inspect_file`` profile."""
    print(f"rows: {inspection['n_rows']}   columns: {len(inspection['columns'])}")
    print(f"numeric     : {inspection['numeric_cols']}")
    print(f"categorical : {inspection['categorical_cols']}")
    print(f"binary      : {inspection['binary_cols']}")
    print(f"datetime    : {inspection['datetime_cols']}")
    n_missing = {k: v for k, v in inspection["n_missing"].items() if v}
    print(f"missing     : {n_missing if n_missing else 'none'}")
    if "class_distribution" in inspection:
        print(f"class distribution[{target}]: {inspection['class_distribution']}")
        print(f"suggested problem type      : {inspection['suggested_problem_type']}")


def _print_metrics_table(runner: ModelRunner) -> None:
    """Print a compact per-model metrics summary (accuracy, F1-weighted, ROC-AUC, MCC)."""
    df = runner.metrics_df_
    if df is None or df.empty:
        print("  (no models were run)")
        return

    header = f"  {'model':<20} {'status':<8} {'accuracy':>9} {'f1_wtd':>9} {'roc_auc':>9} {'mcc':>9}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for _, r in df.iterrows():
        print(
            f"  {str(r['model']):<20} {str(r['status']):<8} "
            f"{_fmt(r['accuracy']):>9} {_fmt(r['f1_weighted']):>9} "
            f"{_fmt(r['roc_auc']):>9} {_fmt(r['mcc']):>9}"
        )
    failed = df[df["status"] == "failed"]
    for _, r in failed.iterrows():
        print(f"  ! {r['model']} failed: {r['error']}")


def _fmt(value: Any) -> str:
    """Format a possibly-None/NaN metric to 4dp for the summary table."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    if isinstance(value, (int, float)):
        return f"{value:.4f}"
    return str(value)


# --------------------------------------------------------------------------- #
# main                                                                        #
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code (0 = success)."""
    # [MANDATORY] load backend/.env so DATA_DIR/OUTPUT_DIR resolve (engine doesn't).
    load_dotenv()

    args = build_parser().parse_args(argv)

    storage = (
        LocalFolderStorage(output_dir=args.output_dir)
        if args.output_dir
        else LocalFolderStorage()
    )
    print(f"DATA_DIR   : {storage.data_dir}")
    print(f"OUTPUT_DIR : {storage.output_dir}")
    print(f"input file : {args.file}")
    print(f"target     : {args.target}")
    print()

    # -- inspect -------------------------------------------------------------
    try:
        inspection = inspect_file(args.file, storage, target=args.target)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — readable failure, not a raw trace
        print(f"ERROR inspecting file: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.inspect:
        _print_inspection(inspection, args.target)
        return 0

    # -- build config --------------------------------------------------------
    try:
        if args.features:
            feature_cols = [c.strip() for c in args.features.split(",") if c.strip()]
            excluded_ids: list[str] = []
        else:
            feature_cols, excluded_ids = default_features(
                args.file, args.target, inspection["datetime_cols"], storage
            )

        overrides: dict[str, Any] = {
            "problem_type": args.problem_type
            or inspection.get("suggested_problem_type", "binary"),
        }
        if args.test_size is not None:
            overrides["test_size"] = args.test_size
        if args.algos:
            overrides["algorithms"] = [
                a.strip() for a in args.algos.split(",") if a.strip()
            ]
        if args.balance:
            overrides["class_balance"] = args.balance
        if args.encoding:
            overrides["encoding_method"] = args.encoding
        if args.scaling:
            overrides["scaling_method"] = args.scaling
        if args.tune:
            overrides["tuning"] = _build_tuning_override(args)

        config = build_config(args.file, args.target, feature_cols, **overrides)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR building config: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if excluded_ids:
        print(f"excluded ID-like columns from defaults: {excluded_ids}")
    if inspection["datetime_cols"]:
        print(f"excluded datetime columns from defaults: {inspection['datetime_cols']}")
    print(f"problem_type : {config['problem_type']}")
    print(f"algorithms   : {config['algorithms']}")
    print(f"balance={config['class_balance']}  encoding={config['encoding_method']}  "
          f"scaling={config['scaling_method']}")
    tuning = config.get("tuning", {})
    if tuning.get("enabled"):
        models = tuning.get("models") or ["all"]
        print(
            f"tuning      : ON  models={models}  metric={tuning.get('metric')}  "
            f"trials={tuning.get('n_trials')}  cv_folds={tuning.get('cv_folds')}  "
            f"timeout={tuning.get('timeout_seconds')}"
        )
    print(f"features ({len(feature_cols)}): {feature_cols}")
    print()

    # -- run -----------------------------------------------------------------
    try:
        runner = ModelRunner(config, storage).run()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR during run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("=== metrics summary ===")
    _print_metrics_table(runner)
    print()

    if runner.tuned_params_:
        print("=== tuned hyperparameters ===")
        for name, params in runner.tuned_params_.items():
            print(f"  {name}: {params}")
        print()

    print("=== files written to OUTPUT_DIR ===")
    for key in _written_keys(runner, storage):
        print(f"  - {key}")
    return 0


def _written_keys(runner: ModelRunner, storage: StorageAdapter) -> list[str]:
    """List the expected output keys that actually exist in OUTPUT_DIR after a run."""
    from .analysis.feature_impact import PLOT_PNG_KEY as PLOT4_KEY, SUMMARY_CSV_KEY
    from .evaluation.plots import PLOT1_KEY, PLOT2_KEY, PLOT3_KEY, PLOT5_KEY
    from .preprocessing.interactions import PLOT_PNG_KEY as PLOT6_KEY
    from .runner import (
        CLASS_REPORT_CSV_KEY,
        METRICS_CSV_KEY,
        RESULTS_CSV_KEY,
        RUN_PROFILE_KEY,
    )

    candidates = [
        SUMMARY_CSV_KEY,
        RESULTS_CSV_KEY,
        METRICS_CSV_KEY,
        CLASS_REPORT_CSV_KEY,
        RUN_PROFILE_KEY,
        PLOT1_KEY,
        PLOT2_KEY,
        PLOT3_KEY,
        PLOT4_KEY,
        PLOT5_KEY,
        PLOT6_KEY,
    ]
    return [key for key in candidates if storage.exists(key)]


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(main())
