"""Section 15 — :class:`ModelRunner`, the pipeline orchestrator.

``ModelRunner`` is the single entry point that runs the whole ClassifyOS engine end to
end: it takes a validated run config plus a :class:`StorageAdapter`, executes every
section in the *corrected canonical order*, trains and evaluates each requested
algorithm, and writes all artifacts (CSVs, the run profile, and the Section 14 plots) to
``OUTPUT_DIR`` through the storage adapter. The API layer (Phase 8) and the CLI
(Section 16) both drive the engine exclusively through this class — it supersedes the
``dev_run.py`` smoke-test script.

Canonical order executed by :meth:`run` (NOT the scope's outdated step diagram — see the
Phase 3 pipeline-order decision in PROJECT_STATE.md / plan_tweak.md row 4):

#. ``data_loader`` → :attr:`raw_df_`
#. ``analyze_feature_impact`` on the RAW frame (before preprocessing) →
   :attr:`feature_impact_` (also writes ``feature_impact_summary.csv`` + ``plot4``)
#. ``train_test_split_cls`` → :attr:`train_df_`, :attr:`test_df_`
#. ``Preprocessor.fit(train)`` → transform train AND test
#. ``FeatureBuilder.fit(train)`` → transform both
#. ``UserFeatureBuilder.fit(train)`` → transform both (user-defined structured features,
   computed from the RAW split frame; OFF when ``config["user_features"]`` is empty)
#. ``InteractionFeatureBuilder.fit(train)`` → transform both (+ writes ``plot6``)
#. ``handle_class_imbalance`` on the TRAIN matrices ONLY → balanced train + class weight
#. (optional, OFF by default) ``tune_model`` per algorithm on the PRE-balance TRAIN
   matrices → best hyperparameters (Section 8B / Phase 7B; ``config["tuning"]``)
#. for each algorithm: ``build_model`` (with tuned params, if any) → ``fit`` →
   ``classify`` → ``evaluate_model``
#. save everything (Section 14 plots + CSVs + ``run_profile.json``)

[RISK] _run_config isolation: :meth:`run` deep-copies the config once at the start and
uses the copy for every downstream stage. ``self.config`` is NEVER mutated during a run,
so the same ``ModelRunner`` (or the same config dict) can be re-run, and the interaction
columns added to the working frames never leak back into the stored config. This is the
scope's central correctness rule for the runner.

Robustness: a single failing algorithm (a library edge case, a degenerate split for one
model) is logged, recorded as a failed row in :attr:`metrics_df_`, and skipped — it never
aborts the whole run. The other algorithms still train and the artifacts are still written.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .analysis.feature_impact import analyze_feature_impact
from .config import build_config
from .evaluation.metrics import evaluate_model
from .io.storage import StorageAdapter
from .models.registry import build_model
from .multilabel import parse_label_sets
from .predict import classify
from .preprocessing.balance import handle_class_imbalance
from .preprocessing.features import FeatureBuilder
from .preprocessing.interactions import (
    InteractionFeatureBuilder,
    plot_interaction_summary,
)
from .preprocessing.preprocess import Preprocessor
from .preprocessing.user_features import UserFeatureBuilder
from .split import train_test_split_cls

logger = logging.getLogger(__name__)

# Logical output keys (part of the future output contract — see docs/api_contract.md).
RESULTS_CSV_KEY = "classification_results.csv"
METRICS_CSV_KEY = "metrics_comparison.csv"
CLASS_REPORT_CSV_KEY = "class_report.csv"
RUN_PROFILE_KEY = "run_profile.json"


class ModelRunner:
    """Run the full ClassifyOS pipeline for one config and collect all results.

    Args:
        config: A validated run config (see :func:`classifyos.config.build_config`).
            Stored as-is and NEVER mutated; :meth:`run` works on a deep copy.
        storage: Storage adapter for every read (input data) and write (artifacts).

    Attributes (populated by :meth:`run`):
        raw_df_: The loaded, validated dataframe (``data_loader`` output).
        feature_impact_: The ``analyze_feature_impact`` ranking frame.
        train_df_, test_df_: The raw (post-split, pre-preprocessing) partitions.
        active_features_: Final engineered feature column names (incl. interaction cols).
        predictions_df_: Per-sample predictions for every successful model, tagged with
            a ``model`` column.
        metrics_df_: One summary row per requested algorithm (failed models flagged).
        feature_impact_: see above.
        models_: ``{name: fitted ModelWrapper}`` for every algorithm that succeeded.
        metrics_: ``{name: full metrics dict}`` (the rich ``evaluate_model`` output,
            used by the Section 14 plots).
        X_test_, y_test_, classes_, problem_type_: handles the plots / serializers reuse.
    """

    def __init__(self, config: dict[str, Any], storage: StorageAdapter) -> None:
        self.config = config
        self.storage = storage

        # Result state — set during run().
        self.raw_df_: pd.DataFrame | None = None
        self.feature_impact_: pd.DataFrame | None = None
        self.train_df_: pd.DataFrame | None = None
        self.test_df_: pd.DataFrame | None = None
        self.active_features_: list[str] = []
        self.predictions_df_: pd.DataFrame | None = None
        self.metrics_df_: pd.DataFrame | None = None
        self.models_: dict[str, Any] = {}
        self.metrics_: dict[str, dict[str, Any]] = {}
        #: {model_name: best hyperparameters} for every model that was tuned this run.
        self.tuned_params_: dict[str, dict[str, Any]] = {}
        self.X_test_: pd.DataFrame | None = None
        self.y_test_: pd.Series | None = None
        #: For multilabel runs only: the test target as a binary indicator matrix
        #: ``(n_test, n_labels)`` (built by the fitted MultiLabelBinarizer). ``None`` for
        #: binary/multiclass. The curve helper consumes this; binary/multiclass use y_test_.
        self.y_test_indicator_: np.ndarray | None = None
        #: For multilabel runs only: the fitted MultiLabelBinarizer (TRAIN label vocabulary).
        self._mlb: Any = None
        self.classes_: list[Any] = []
        self.problem_type_: str = "binary"
        self.run_profile_: dict[str, Any] | None = None

    # --------------------------------------------------------------------- run --

    def run(self) -> "ModelRunner":
        """Execute the whole pipeline and write all artifacts. Returns ``self``."""
        # [RISK] _run_config isolation — deep-copy the caller's config ONCE and use the
        # copy for every stage below. self.config is never mutated, so re-running is safe
        # and the interaction columns added to the working frames never leak into config.
        cfg = copy.deepcopy(self.config)

        target = cfg["target"]
        problem_type = cfg.get("problem_type", "binary")
        self.problem_type_ = problem_type
        algorithms = list(cfg.get("algorithms", []))

        # -- 1. load -----------------------------------------------------------
        logger.info("ModelRunner: loading %s", cfg["input_file"])
        self.raw_df_ = data = self._load(cfg)

        # -- 2. feature impact on RAW data (writes feature_impact_summary.csv + plot4) --
        logger.info("ModelRunner: analyzing feature impact (raw)")
        self.feature_impact_ = analyze_feature_impact(data, cfg, self.storage)

        # -- 3. split ----------------------------------------------------------
        logger.info("ModelRunner: train/test split")
        self.train_df_, self.test_df_ = train_test_split_cls(data, cfg)

        # -- 4-6. preprocess → features → interactions (fit on TRAIN, apply to both) --
        train_X, train_y, test_X, test_y = self._engineer(cfg, target)
        self.X_test_, self.y_test_ = test_X, test_y
        self.active_features_ = list(train_X.columns)

        # -- 6b. multilabel: build the indicator matrix (TRAIN-fitted vocabulary) --
        # The single delimited target column (e.g. "Auto|Home") must become a binary
        # indicator matrix (n, n_labels) for the OneVsRest wrappers + the multilabel metrics.
        # [RISK] leakage — the MultiLabelBinarizer learns its label vocabulary from the TRAIN
        # split only; a label appearing only in test is ignored (mirrors the encoder rule).
        if problem_type == "multilabel":
            from sklearn.preprocessing import MultiLabelBinarizer

            self._mlb = MultiLabelBinarizer().fit(parse_label_sets(train_y))
            self.y_test_indicator_ = self._mlb.transform(parse_label_sets(test_y))

        # -- 7. class imbalance (TRAIN ONLY) -----------------------------------
        logger.info("ModelRunner: handling class imbalance (%s)", cfg.get("class_balance"))
        X_bal, y_bal, class_weight = handle_class_imbalance(train_X, train_y, cfg)

        # -- 7B. optional hyperparameter tuning (per model, PRE-balance TRAIN) --
        # [RISK] leakage — tuning is scored on folds carved from the PRE-balance train
        # matrices (train_X/train_y), never the test set; balancing is applied only to the
        # final fit below (X_bal/y_bal). See classifyos.tuning for the full leakage note.
        self.tuned_params_ = self._tune(cfg, algorithms, train_X, train_y, class_weight)

        # -- 8. per-algorithm train → classify → evaluate ----------------------
        # For multilabel the "classes" are the label names (the indicator columns); for
        # binary/multiclass they are the distinct label values in the balanced train set.
        if problem_type == "multilabel":
            self.classes_ = list(self._mlb.classes_)
        else:
            self.classes_ = sorted(pd.Series(y_bal).astype(str).unique())
        metrics_rows: list[dict[str, Any]] = []
        prediction_frames: list[pd.DataFrame] = []
        for name in algorithms:
            row, preds = self._run_one_algorithm(
                name, X_bal, y_bal, test_X, test_y, problem_type, class_weight, cfg,
                best_params=self.tuned_params_.get(name, {}),
                train_eval_X=train_X, train_eval_y=train_y,
            )
            metrics_rows.append(row)
            if preds is not None:
                prediction_frames.append(preds)

        self.metrics_df_ = pd.DataFrame(metrics_rows)
        self.predictions_df_ = (
            pd.concat(prediction_frames, ignore_index=True)
            if prediction_frames
            else pd.DataFrame()
        )

        n_ok = len(self.models_)
        logger.info(
            "ModelRunner: %d/%d algorithm(s) succeeded", n_ok, len(algorithms)
        )

        # -- 9. save everything ------------------------------------------------
        self._save_all(cfg, class_weight)
        return self

    # ------------------------------------------------------------- pipeline steps --

    def _load(self, cfg: dict[str, Any]) -> pd.DataFrame:
        """Stage 1 — load the dataset (imported lazily to keep the import graph flat)."""
        from .io.loader import data_loader

        return data_loader(cfg, self.storage)

    def _engineer(
        self, cfg: dict[str, Any], target: str
    ) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
        """Stages 4-6 — preprocess, build features, build interactions (TRAIN-fitted).

        Every stage is fitted on the TRAIN partition only and merely applied to the
        TEST partition, preserving the no-leakage guarantee. Writes ``plot6``.

        Returns ``(X_train, y_train, X_test, y_test)`` — all-numeric feature matrices
        with the target split off into the label series.
        """
        # 4. preprocess
        pre = Preprocessor(cfg)
        train_pp = pre.fit_transform(self.train_df_)
        test_pp = pre.transform(self.test_df_)

        # 5. derived features (polynomial / ratio / binning)
        # [TEMP — feature engineering unwired] Section 7 derived features are temporarily
        # force-disabled here regardless of the incoming request config (mirroring the
        # interaction unwiring below). FeatureBuilder short-circuits when disabled — fit
        # builds nothing (created_features_ stays empty) and transform returns a copy — so
        # no ratio/bin/poly columns enter active_features. The LOCKED schema is unchanged.
        # To re-enable: delete the next line.
        cfg["feature_engineering"] = {**cfg.get("feature_engineering", {}), "enabled": False}
        fb = FeatureBuilder(cfg)
        train_fb = fb.fit_transform(train_pp, target)
        test_fb = fb.transform(test_pp)

        # 5b. user-defined structured features. These are computed from the RAW post-split
        # frames (self.train_df_/self.test_df_) — NOT the preprocessed frame — so that
        # datetime_diff can see real datetime columns and numeric ops use unscaled values;
        # the Preprocessor scales numerics and encodes/drops datetime columns. Their output
        # columns are then injected here, AFTER FeatureBuilder and BEFORE interactions, so
        # they can become interaction candidates and exist before balancing/training.
        # [RISK] leakage — fitted on the TRAIN frame only; no test rows reach fit(). Output
        # columns join by index, so the preprocessing "drop" strategy stays aligned.
        ufb = UserFeatureBuilder(cfg)
        ufb.fit(self.train_df_, target)
        if ufb.created_features_:
            train_uf = ufb.transform(self.train_df_)
            test_uf = ufb.transform(self.test_df_)
            train_fb = train_fb.join(train_uf[ufb.created_features_])
            test_fb = test_fb.join(test_uf[ufb.created_features_])

        # 6. pairwise interactions (+ plot6 on the engineered TRAIN frame)
        # [TEMP — interaction features unwired] Interaction features are temporarily
        # force-disabled here regardless of the incoming request config. The builder
        # short-circuits when disabled (no pairs discovered, transform returns a copy),
        # so result.run.interaction_cols comes back empty and no plot6 is written —
        # the LOCKED schema 1.0 is unchanged (interaction_cols is just []).
        # To re-enable: delete the next line and restore the plot6 call below.
        cfg["interaction_features"] = {**cfg.get("interaction_features", {}), "enabled": False}
        ib = InteractionFeatureBuilder(cfg)
        train_fin = ib.fit_transform(train_fb, target)
        test_fin = ib.transform(test_fb)
        if ib.enabled_ and ib.interaction_cols_:
            try:
                plot_interaction_summary(
                    train_fin, target, ib.interaction_cols_, self.storage
                )
            except Exception:  # noqa: BLE001 — a plot must never abort a run
                logger.exception("ModelRunner: plot6 (interaction summary) failed")

        X_train = train_fin.drop(columns=[target])
        y_train = train_fin[target]
        X_test = test_fin.drop(columns=[target])
        y_test = test_fin[target]
        return X_train, y_train, X_test, y_test

    def _tune(
        self,
        cfg: dict[str, Any],
        algorithms: list[str],
        train_X: pd.DataFrame,
        train_y: pd.Series,
        class_weight: dict[Any, float] | None,
    ) -> dict[str, dict[str, Any]]:
        """Stage 7B — tune each requested algorithm (when enabled), returning best params.

        Tuning is OFF unless ``cfg["tuning"]["enabled"]``. For each algorithm in the tune
        list, :func:`classifyos.tuning.tune_model` runs its own Optuna study on the
        PRE-balance TRAIN matrices and returns the best hyperparameters (or ``{}`` to fall
        back to defaults). Imported lazily so the (optional) Optuna dependency is only
        touched when tuning is actually requested.
        """
        from .tuning import should_tune_model, tune_model

        tuning_enabled = bool(cfg.get("tuning", {}).get("enabled", False))
        if not tuning_enabled:
            return {}

        problem_type = cfg.get("problem_type", "binary")
        random_state = cfg.get("random_state", 42)
        tuned: dict[str, dict[str, Any]] = {}
        for name in algorithms:
            if not should_tune_model(name, cfg):
                continue
            logger.info("ModelRunner: tuning %s …", name)
            best = tune_model(
                name,
                train_X,
                train_y,
                problem_type,
                cfg,
                class_weight=class_weight,
                random_state=random_state,
            )
            if best:
                tuned[name] = best
                logger.info("ModelRunner: %s tuned → %s", name, best)
            else:
                logger.info("ModelRunner: %s tuning returned no params; using defaults", name)
        return tuned

    def _run_one_algorithm(
        self,
        name: str,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        problem_type: str,
        class_weight: dict[Any, float] | None,
        cfg: dict[str, Any],
        best_params: dict[str, Any] | None = None,
        train_eval_X: pd.DataFrame | None = None,
        train_eval_y: pd.Series | None = None,
    ) -> tuple[dict[str, Any], pd.DataFrame | None]:
        """Build → fit → classify → evaluate ONE algorithm; never raises.

        ``best_params`` (from the optional tuning stage) are splatted into ``build_model``;
        when empty the wrapper defaults are used — identical to the pre-tuning behaviour.

        The headline metrics (``accuracy``/``f1_weighted``/…) are computed on the HELD-OUT
        TEST split — they are the reported generalization performance. In addition, a parallel
        set of ``train_*`` headline metrics is computed on ``train_eval_X``/``train_eval_y`` —
        the PRE-balance TRAIN split (real rows at the natural class distribution, NOT the
        SMOTE/undersampled matrix the model was fit on). Reporting train on the pre-balance
        split keeps it the same distribution as test, so the train↔test gap is a clean
        overfitting signal rather than one muddied by the balancing-induced distribution shift.
        No leakage surface: the model already trained on these rows; this only reports on them.

        On any failure the model is logged, recorded as a ``status="failed"`` row with
        the error message, and ``None`` predictions are returned so the run continues
        with the remaining algorithms.
        """
        random_state = cfg.get("random_state", 42)
        params = dict(best_params or {})
        try:
            model = build_model(
                name,
                problem_type=problem_type,
                class_weight=class_weight,
                random_state=random_state,
                **params,
            )

            if problem_type == "multilabel":
                # Fit on the binary indicator matrix (OneVsRest, one estimator per label);
                # evaluate against the indicator truth. y_train/y_test stay the delimited
                # strings (classify() re-joins them for the predictions table).
                Y_train = self._mlb.transform(parse_label_sets(y_train))
                model.fit(X_train, Y_train)
                # OvR on an indicator matrix learns integer column classes; restore the real
                # label names so metrics/curves/classify read the products, not 0..n-1.
                model.classes_ = np.asarray(self._mlb.classes_)
                classes = np.asarray(self._mlb.classes_)
                Y_test = self._mlb.transform(parse_label_sets(y_test))
                y_proba = model.predict_proba(X_test)
                y_pred = model.predict(X_test)
                metrics = evaluate_model(Y_test, y_pred, y_proba, problem_type, classes)
            else:
                model.fit(X_train, y_train)
                classes = np.asarray(model.classes_)
                y_proba = model.predict_proba(X_test)
                y_pred = model.predict(X_test)
                metrics = evaluate_model(y_test, y_pred, y_proba, problem_type, classes)

            # Train-side (pre-balance) headline metrics — see docstring. Re-runs the SAME
            # evaluate_model on the pre-balance TRAIN split so train/test are apples-to-apples.
            train_metrics = self._evaluate_train(
                model, train_eval_X, train_eval_y, problem_type, classes
            )

            preds = classify(model, X_test, y_test, classes)
            preds.insert(0, "model", model.name)
            preds = preds.reset_index().rename(columns={"index": "sample_index"})

            self.models_[model.name] = model
            self.metrics_[model.name] = metrics

            row = {
                "model": model.name,
                "status": "ok",
                "n_test": int(len(X_test)),
                "accuracy": metrics.get("accuracy"),
                "f1_weighted": metrics.get("f1_weighted"),
                "f1_macro": metrics.get("f1_macro"),
                "precision_weighted": metrics.get("precision_weighted"),
                "recall_weighted": metrics.get("recall_weighted"),
                "roc_auc": metrics.get("roc_auc"),
                "pr_auc": metrics.get("pr_auc"),
                "mcc": metrics.get("mcc"),
                "log_loss": metrics.get("log_loss"),
                **_train_row(train_metrics),
                "error": None,
            }
            logger.info(
                "ModelRunner: %s ok (f1_weighted=%s, accuracy=%s)",
                model.name,
                _fmt(row["f1_weighted"]),
                _fmt(row["accuracy"]),
            )
            return row, preds
        except Exception as exc:  # noqa: BLE001 — one bad model must not kill the run
            logger.exception("ModelRunner: algorithm %r failed", name)
            row = {
                "model": name,
                "status": "failed",
                "n_test": int(len(X_test)),
                "accuracy": None,
                "f1_weighted": None,
                "f1_macro": None,
                "precision_weighted": None,
                "recall_weighted": None,
                "roc_auc": None,
                "pr_auc": None,
                "mcc": None,
                "log_loss": None,
                **_train_row(None),
                "error": f"{type(exc).__name__}: {exc}",
            }
            return row, None

    def _evaluate_train(
        self,
        model: Any,
        train_eval_X: pd.DataFrame | None,
        train_eval_y: pd.Series | None,
        problem_type: str,
        classes: np.ndarray,
    ) -> dict[str, Any] | None:
        """Headline metrics on the PRE-balance TRAIN split (the overfit-gap reference).

        Returns ``None`` (so every ``train_*`` field becomes ``None``) when the pre-balance
        matrices were not supplied or the evaluation fails for any reason — a train-side
        diagnostic must never abort or alter the run. ``classes`` is the fitted model's class
        order so ``evaluate_model``/``predict_proba`` columns stay aligned with the test call.
        """
        if train_eval_X is None or train_eval_y is None:
            return None
        try:
            proba = model.predict_proba(train_eval_X)
            pred = model.predict(train_eval_X)
            if problem_type == "multilabel":
                y_true = self._mlb.transform(parse_label_sets(train_eval_y))
            else:
                y_true = train_eval_y
            return evaluate_model(y_true, pred, proba, problem_type, classes)
        except Exception:  # noqa: BLE001 — a diagnostic must never kill the run
            logger.exception("ModelRunner: train-side evaluation failed for %r", model.name)
            return None

    # ----------------------------------------------------------------- artifacts --

    def _save_all(
        self, cfg: dict[str, Any], class_weight: dict[Any, float] | None
    ) -> None:
        """Stage 9 — write CSVs, the run profile, and the Section 14 plots."""
        # predictions
        if self.predictions_df_ is not None and not self.predictions_df_.empty:
            with self.storage.open_write(RESULTS_CSV_KEY) as fh:
                self.predictions_df_.to_csv(fh, index=False)

        # metrics comparison
        if self.metrics_df_ is not None:
            with self.storage.open_write(METRICS_CSV_KEY) as fh:
                self.metrics_df_.to_csv(fh, index=False)

        # per-class per-model report
        report_df = self._build_class_report()
        with self.storage.open_write(CLASS_REPORT_CSV_KEY) as fh:
            report_df.to_csv(fh, index=False)

        # run profile
        self.run_profile_ = self._build_run_profile(cfg, class_weight)
        with self.storage.open_write(RUN_PROFILE_KEY) as fh:
            json.dump(self.run_profile_, fh, indent=2)

        # Section 14 plots (plot1/2/3/5). Imported lazily to avoid a hard matplotlib
        # import when a caller only wants the engine outputs. A plot failure is logged
        # but never aborts the run.
        try:
            from .evaluation.plots import plot_results

            plot_results(self, self.storage)
        except Exception:  # noqa: BLE001
            logger.exception("ModelRunner: plot_results (plot1/2/3/5) failed")

        logger.info("ModelRunner: artifacts written to OUTPUT_DIR")

    def _build_class_report(self) -> pd.DataFrame:
        """Flatten every successful model's per-class classification report to rows.

        One row per (model, class) plus the macro/weighted average rows that sklearn's
        ``classification_report`` produces, so the dashboard can render a per-class
        table per model.
        """
        rows: list[dict[str, Any]] = []
        for name, metrics in self.metrics_.items():
            report = metrics.get("classification_report") or {}
            for label, vals in report.items():
                if not isinstance(vals, dict):  # the scalar "accuracy" entry
                    continue
                rows.append(
                    {
                        "model": name,
                        "class": label,
                        "precision": vals.get("precision"),
                        "recall": vals.get("recall"),
                        "f1_score": vals.get("f1-score"),
                        "support": vals.get("support"),
                    }
                )
        columns = ["model", "class", "precision", "recall", "f1_score", "support"]
        return pd.DataFrame(rows, columns=columns)

    def _build_run_profile(
        self, cfg: dict[str, Any], class_weight: dict[Any, float] | None
    ) -> dict[str, Any]:
        """Assemble the JSON-serializable ``run_profile.json`` payload."""
        target = cfg["target"]
        problem_type = cfg.get("problem_type", "binary")
        class_distribution: dict[str, int] = {}
        if self.raw_df_ is not None:
            if problem_type == "multilabel":
                # Per-label prevalence (how many rows carry each label), not per-combo —
                # the honest distribution for a multilabel target. Counts use the same
                # delimited-set parsing the binarizer does.
                from collections import Counter

                counter: Counter = Counter()
                for labels in parse_label_sets(self.raw_df_[target].tolist()):
                    counter.update(set(labels))
                class_distribution = {str(k): int(v) for k, v in counter.most_common()}
            else:
                counts = self.raw_df_[target].astype(str).value_counts()
                class_distribution = {str(k): int(v) for k, v in counts.items()}

        tuning_cfg = cfg.get("tuning", {}) or {}
        tuning_profile = {
            "enabled": bool(tuning_cfg.get("enabled", False)),
            "metric": tuning_cfg.get("metric"),
            "cv": tuning_cfg.get("cv"),
            "cv_folds": tuning_cfg.get("cv_folds"),
            "n_trials": tuning_cfg.get("n_trials"),
            "timeout_seconds": tuning_cfg.get("timeout_seconds"),
            "tuned_models": sorted(self.tuned_params_),
            "best_params": {
                name: params for name, params in self.tuned_params_.items()
            },
        }

        return {
            "input_file": cfg["input_file"],
            "target": target,
            "problem_type": cfg.get("problem_type", "binary"),
            "features": list(cfg.get("feature_cols", [])),
            "active_features": list(self.active_features_),
            "algorithms": list(cfg.get("algorithms", [])),
            "class_balance": cfg.get("class_balance"),
            "tuning": tuning_profile,
            "class_weight": (
                {str(k): float(v) for k, v in class_weight.items()}
                if class_weight
                else None
            ),
            "class_distribution": class_distribution,
            "n_rows": int(len(self.raw_df_)) if self.raw_df_ is not None else 0,
            "n_train": int(len(self.train_df_)) if self.train_df_ is not None else 0,
            "n_test": int(len(self.test_df_)) if self.test_df_ is not None else 0,
            "models_succeeded": sorted(self.models_),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


#: Headline metric keys mirrored onto the train side as ``train_<key>`` columns. These are
#: the same scalars the scoreboard shows for test; the train copy makes the overfit gap
#: visible. Confusion matrices / per-class reports / curves stay test-only by design.
_TRAIN_METRIC_KEYS = (
    "accuracy",
    "f1_weighted",
    "f1_macro",
    "precision_weighted",
    "recall_weighted",
    "roc_auc",
    "pr_auc",
    "mcc",
    "log_loss",
)


def _train_row(train_metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Build the ``train_*`` columns from a train-side metrics dict (``None`` → all ``None``)."""
    metrics = train_metrics or {}
    return {f"train_{key}": metrics.get(key) for key in _TRAIN_METRIC_KEYS}


def _fmt(value: Any) -> str:
    """Format a possibly-``None`` metric for a log line."""
    return f"{value:.4f}" if isinstance(value, (int, float)) else "n/a"


def run_from_args(
    input_file: str,
    target: str,
    feature_cols: list[str],
    storage: StorageAdapter,
    **overrides: Any,
) -> ModelRunner:
    """Convenience: build a config and run it in one call.

    Used by the CLI (Section 16) and handy for tests/notebooks. ``overrides`` are passed
    straight to :func:`classifyos.config.build_config` (e.g. ``problem_type``,
    ``algorithms``, ``class_balance``).
    """
    config = build_config(input_file, target, feature_cols, **overrides)
    return ModelRunner(config, storage).run()


# data_loader is imported lazily inside _load to keep the module-level import graph small;
# re-export nothing else here.
