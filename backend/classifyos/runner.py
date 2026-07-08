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
import os
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
FEATURE_IMPORTANCE_CSV_KEY = "feature_importance_summary.csv"
PERMUTATION_IMPORTANCE_CSV_KEY = "permutation_importance_summary.csv"
EXPLANATIONS_CSV_KEY = "explanations_summary.csv"
RUN_PROFILE_KEY = "run_profile.json"

#: The Section 14 / Section 5 plot filenames a run may write (plot6 only when interactions are
#: on). Kept here so the optional MLflow layer can attach them as artifacts without the engine
#: importing the API-layer artifact list (the engine has no web dependency).
_PLOT_KEYS = (
    "plot1_confusion_matrix.png",
    "plot2_roc_pr_curves.png",
    "plot3_feature_importance.png",
    "plot4_feature_impact.png",
    "plot5_calibration_curve.png",
    "plot6_interaction_summary.png",
)
#: Every artifact key a run may produce, in a stable order (CSVs + run profile, then the plots).
#: The MLflow layer resolves each to a concrete path via the StorageAdapter and logs only those
#: that actually exist on disk. Mirrors ``backend/api/artifacts.py::ARTIFACT_KEYS`` (which the
#: engine must not import) — the two lists must stay in sync.
_ARTIFACT_KEYS = (
    RESULTS_CSV_KEY,
    METRICS_CSV_KEY,
    CLASS_REPORT_CSV_KEY,
    FEATURE_IMPORTANCE_CSV_KEY,
    PERMUTATION_IMPORTANCE_CSV_KEY,
    EXPLANATIONS_CSV_KEY,
    RUN_PROFILE_KEY,
    *_PLOT_KEYS,
)


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
        #: {model_name: {feature: importance} or None} — each successful model's NATIVE
        #: (built-in) feature importance, read post-training from the fitted estimator
        #: (tree impurity/gain or |coef|). ``None`` for models that expose none (RBF-SVM,
        #: GaussianNB). Keyed by the engineered/active feature columns. Model-dependent and
        #: NOT comparable across models — distinct from the pre-training ``feature_impact_``
        #: screen, which ranks RAW features by their statistical association with the target.
        self.feature_importances_: dict[str, dict[str, float] | None] = {}
        #: {model_name: {feature: importance} or None} — each successful model's PERMUTATION
        #: importance, measured post-training on the held-out TEST split as the drop in
        #: F1-weighted when each feature is shuffled (see
        #: :mod:`classifyos.analysis.permutation_importance`). Model-AGNOSTIC, so unlike the
        #: native importances above it covers ALL six models — including the RBF-SVM and
        #: GaussianNB that expose no native importance. ``None`` only when the measure could
        #: not be computed (no feature columns / scoring error). Leakage-safe: reads test
        #: predictions only, fits nothing, never mutates the test matrix.
        self.permutation_importances_: dict[str, dict[str, float] | None] = {}
        #: {model_name: {"method", "rows": [...]} or None} — per-row SHAP explanations for a
        #: small sample of held-out TEST rows, computed during the run (models still fitted in
        #: memory) when ``config["explainability"]["enabled"]`` is set; ``{}`` when OFF. This is
        #: LOCAL explainability (why THIS prediction), complementing the two GLOBAL importance
        #: screens above. See :mod:`classifyos.analysis.explain`. Leakage-safe: the SHAP
        #: background is a TRAIN reference sample (never fitted on) and the explained rows are
        #: read-only test rows; nothing is refit. ``None`` for a model whose explainer failed
        #: or for multilabel (unsupported in v1). Report-only — never aborts the run.
        self.explanations_: dict[str, dict[str, Any] | None] = {}
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
        #: MLflow run pointer when ``config["mlflow"]["enabled"]`` is set AND logging succeeded;
        #: ``None`` otherwise (OFF by default, or a report-only logging failure). Shape:
        #: ``{"run_id", "experiment_id", "tracking_uri", "models": {name: model_uri}}`` — the
        #: API surfaces it as the additive ``result.mlflow`` block (schema 1.9). Populated by
        #: :meth:`_log_to_mlflow` after all artifacts are written. See classifyos.mlflow_logging.
        self.mlflow_run_: dict[str, Any] | None = None

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

        # Post-training native feature importance, read from each fitted model. This is a
        # MODEL property (what the trained estimator relied on), distinct from the raw
        # pre-training feature_impact_ screen above. Leakage-safe: it reads the fitted
        # estimator's internal state only — no test data, no refit. ``feature_importance()``
        # already guards its own None case (RBF-SVM / GaussianNB expose nothing).
        self.feature_importances_ = {
            name: model.feature_importance() for name, model in self.models_.items()
        }

        # Post-training PERMUTATION importance — the model-AGNOSTIC counterpart. Measured on
        # the held-out TEST split as the drop in F1-weighted when each feature is shuffled, so
        # it covers EVERY model (including the RBF-SVM / GaussianNB that have no native
        # importance above). Leakage-safe: it reads test predictions only — fits nothing,
        # refits nothing, never mutates the test matrix. Per-model try/except so a single
        # model's failure (or the whole step) never aborts the run (report-only).
        # [RISK] cost — scales with n_features × n_repeats predict passes per model.
        self.permutation_importances_ = self._compute_permutation_importances(
            problem_type,
            metric=cfg.get("permutation_metric", "f1_weighted"),
            random_state=cfg.get("random_state", 42),
        )

        # Per-row SHAP explanations (LOCAL explainability). OFF by default; computed here — while
        # every model is still fitted in memory — when the opt-in toggle is set, so no model
        # persistence is needed (same compute-during-run pattern as the importances above).
        # The SHAP background is the PRE-balance TRAIN matrix (a leakage-safe reference
        # distribution, never fitted on); the explained rows are the first ``sample_rows`` of the
        # untouched TEST split. Per-model try/except inside the helper — report-only, never aborts.
        expl_cfg = cfg.get("explainability", {}) or {}
        if expl_cfg.get("enabled", False):
            sample_rows = int(expl_cfg.get("sample_rows", 20))
            self.explanations_ = self._compute_explanations(
                problem_type,
                train_X,
                sample_rows=sample_rows,
                background_size=int(expl_cfg.get("background_size", 100)),
                random_state=cfg.get("random_state", 42),
            )
            # Attach each explained row's ORIGINAL feature values (resolved from the raw TEST
            # frame) alongside the SHAP contributions, so the waterfall can show "feature = value"
            # — the reason-code convention. Runs whenever SHAP is on (NOT gated on the LLM flag);
            # report-only, no external calls, no refit.
            self._add_feature_values(cfg, problem_type)
            # Optional LLM reason-code narratives on top of the SHAP numbers (opt-in; Azure
            # OpenAI). Report-only: absent credentials / a failed call leave SHAP untouched.
            if expl_cfg.get("llm_narratives", False):
                self._add_llm_narratives(cfg, problem_type, sample_rows=sample_rows)

        n_ok = len(self.models_)
        logger.info(
            "ModelRunner: %d/%d algorithm(s) succeeded", n_ok, len(algorithms)
        )

        # -- 9. save everything ------------------------------------------------
        self._save_all(cfg, class_weight)

        # -- 10. optional MLflow logging (opt-in, report-only) -----------------
        # OFF by default. Runs AFTER _save_all so the artifact files exist on disk to attach.
        # [RISK] leakage — logging reads nothing back into fit/transform; it serializes the
        # already-fitted models and copies the already-written artifacts. Report-only: a logging
        # failure is swallowed inside the helper and never affects the run (mlflow_run_ stays None).
        if cfg.get("mlflow", {}).get("enabled", False):
            self.mlflow_run_ = self._log_to_mlflow(cfg)
        return self

    # ------------------------------------------------------------- pipeline steps --

    def _load(self, cfg: dict[str, Any]) -> pd.DataFrame:
        """Stage 1 — load the dataset (imported lazily to keep the import graph flat).

        Interim 2b: when ``input_source.type == "postgres"``, the configured table/query is run
        ONCE and materialized to ``cfg["input_file"]`` under DATA_DIR (Option B) BEFORE the file
        is read — a no-op for the default ``file`` source, so the load path below is unchanged.
        ``data_loader`` and everything downstream still read a plain file (leakage discipline +
        StorageAdapter rule stay literally intact).
        """
        from .io.loader import data_loader
        from .io.sql_source import materialize_source

        materialize_source(cfg, self.storage)
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

            # Decision policy (calibration + binary threshold). Applied for binary/multiclass;
            # multilabel ignores it (the OvR indicator path uses per-label 0.5). Composed +
            # fitted leakage-safe (CV on TRAIN only) inside the wrapper — see models/decision.
            if problem_type != "multilabel" and hasattr(model, "set_decision_policy"):
                model.set_decision_policy(
                    calibrate=bool(cfg.get("calibrate_probs", True)),
                    threshold_mode=cfg.get("threshold_mode", "default"),
                    threshold=float(cfg.get("threshold", 0.5)),
                    threshold_metric=cfg.get("threshold_metric", "f1"),
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

            info = getattr(model, "_decision_info", None)
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
                # Decision policy outcome (binary threshold + calibration status). The effective
                # operating threshold is None for multiclass/multilabel (no single scalar cut).
                "decision_threshold": info.threshold if info is not None else None,
                "calibrated": bool(info.calibrated) if info is not None else None,
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
                "decision_threshold": None,
                "calibrated": None,
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

        # post-training native feature importance, one (model, feature, importance, rank)
        # row per model that exposes any. Always written (header-only if no model exposes
        # importances) so the artifact set stays stable across problem types / model mixes.
        importance_df = self._build_feature_importance_df()
        with self.storage.open_write(FEATURE_IMPORTANCE_CSV_KEY) as fh:
            importance_df.to_csv(fh, index=False)

        # post-training PERMUTATION importance, one (model, feature, importance, rank) row
        # per model (covers ALL models, SVM/NaiveBayes included). Always written (header-only
        # if none) so the artifact set stays stable across problem types / model mixes.
        permutation_df = self._build_permutation_importance_df()
        with self.storage.open_write(PERMUTATION_IMPORTANCE_CSV_KEY) as fh:
            permutation_df.to_csv(fh, index=False)

        # per-row SHAP explanations, one (model, sample_index, feature) row each. Written ONLY
        # when explainability was enabled (opt-in), so the default artifact set is unchanged.
        if cfg.get("explainability", {}).get("enabled", False):
            explanations_df = self._build_explanations_df()
            with self.storage.open_write(EXPLANATIONS_CSV_KEY) as fh:
                explanations_df.to_csv(fh, index=False)

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

    def _log_to_mlflow(self, cfg: dict[str, Any]) -> dict[str, Any] | None:
        """Stage 10 — log this run to MLflow (opt-in, report-only). Returns the run pointer or ``None``.

        Assembles the inputs the pure :func:`classifyos.mlflow_logging.log_run` helper needs —
        the config, each model's headline metrics row, the fitted model wrappers, and the
        concrete paths of every artifact that actually exists — then delegates the MLflow
        mechanics to it. ALL artifact paths are resolved through the StorageAdapter (no hardcoded
        paths); ``mlflow_logging`` imports ``mlflow`` lazily and swallows every failure, so this
        never aborts a run. Called only when ``cfg["mlflow"]["enabled"]`` is set.
        """
        from .mlflow_logging import log_run

        mlflow_cfg = cfg.get("mlflow", {}) or {}
        metrics_records = (
            self.metrics_df_.to_dict(orient="records")
            if self.metrics_df_ is not None and not self.metrics_df_.empty
            else []
        )
        # Resolve the concrete path of every artifact that was actually written (via the storage
        # adapter — the sanctioned way to obtain a filesystem path). plot6 / explanations_summary
        # are conditional, so only existing files are attached.
        artifact_paths: list[str] = []
        for key in _ARTIFACT_KEYS:
            try:
                path = self.storage.path_for(key, output=True)
            except Exception:  # noqa: BLE001 — a bad key must not break logging
                continue
            if os.path.exists(path):
                artifact_paths.append(path)

        return log_run(
            config=cfg,
            metrics_records=metrics_records,
            models=self.models_,
            artifact_paths=artifact_paths,
            experiment=mlflow_cfg.get("experiment", "classifyos") or "classifyos",
            # A meaningful default when the config supplied no run_name (an explicit one still
            # wins) — otherwise MLflow auto-generates a whimsical name ("capable-fox-123") that
            # reads as random in the Runs view.
            run_name=mlflow_cfg.get("run_name") or self._default_mlflow_run_name(cfg),
        )

    def _default_mlflow_run_name(self, cfg: dict[str, Any]) -> str:
        """Build a meaningful default MLflow run name — ``"<target> · <YYYY-MM-DD HH:MM>"``.

        Used only when the config supplied no ``mlflow.run_name`` (an explicit name still wins),
        so the Runs view shows the target plus when the run happened instead of MLflow's
        whimsical auto-generated name. **Reuses the timestamp the run profile already computed**
        (``run_profile.json``, written by :meth:`_save_all` at step 9 — before this step 10 log)
        rather than reading a fresh clock; falls back to the current UTC time only if the profile
        is somehow absent or its timestamp unparseable (never raises — this is display polish).

        Display-only: MLflow keys the run record and its id-based artifact folder off the run
        *id* (a UUID), so this name only sets the ``mlflow.runName`` tag the Runs view reads — it
        never touches the artifact folder names or the Postgres→file mapping.
        """
        target = str(cfg.get("target", "run"))
        stamp = (self.run_profile_ or {}).get("timestamp")
        try:
            when = datetime.fromisoformat(stamp) if stamp else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            when = datetime.now(timezone.utc)
        return f"{target} · {when:%Y-%m-%d %H:%M}"

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

    def _compute_permutation_importances(
        self, problem_type: str, *, metric: str, random_state: int
    ) -> dict[str, dict[str, float] | None]:
        """Permutation importance for every fitted model on the held-out TEST split.

        Model-agnostic (uses only ``predict``/``predict_proba``), so it covers all six models —
        including the RBF-SVM / GaussianNB that expose no native importance. ``metric`` (the
        configurable scoring metric, e.g. ``f1_weighted``) is the quantity whose drop is
        measured; each model's own ``classes_`` is forwarded so the score matches the reported
        metric exactly. For multilabel the truth is the binary indicator matrix (matching the
        OvR ``predict`` output); binary/multiclass use the 1-D label series. Each model is
        computed in its own try/except: a failure is logged and recorded as ``None`` so one bad
        model (or the whole report-only step) never aborts the run.
        """
        from .analysis.permutation_importance import permutation_importance

        if self.X_test_ is None or not self.models_:
            return {name: None for name in self.models_}

        y_true = (
            self.y_test_indicator_ if problem_type == "multilabel" else self.y_test_
        )
        out: dict[str, dict[str, float] | None] = {}
        for name, model in self.models_.items():
            try:
                out[name] = permutation_importance(
                    model,
                    self.X_test_,
                    y_true,
                    problem_type,
                    model.classes_,
                    metric=metric,
                    random_state=random_state,
                )
            except Exception:  # noqa: BLE001 — report-only; never abort the run
                logger.exception("ModelRunner: permutation importance failed for %r", name)
                out[name] = None
        return out

    def _compute_explanations(
        self,
        problem_type: str,
        X_background: pd.DataFrame,
        *,
        sample_rows: int,
        background_size: int,
        random_state: int,
    ) -> dict[str, dict[str, Any] | None]:
        """Per-row SHAP explanations for a small sample of test rows, per fitted model.

        Explains the first ``sample_rows`` rows of the held-out TEST split (the same leading
        rows the predictions preview shows) for each model, using ``X_background`` (the
        pre-balance TRAIN matrix) as the SHAP reference distribution. Each model is computed
        in its own try/except: a failure is logged and recorded as ``None`` so one bad model
        (or the whole opt-in step) never aborts the run. Returns ``{}`` if there is nothing to
        explain. See :func:`classifyos.analysis.explain.explain_rows` for the leakage note.
        """
        from .analysis.explain import explain_rows

        if self.X_test_ is None or self.X_test_.empty or not self.models_:
            return {}

        X_explain = self.X_test_.head(max(1, sample_rows))
        out: dict[str, dict[str, Any] | None] = {}
        for name, model in self.models_.items():
            try:
                out[name] = explain_rows(
                    model,
                    X_background,
                    X_explain,
                    problem_type,
                    background_size=background_size,
                    random_state=random_state,
                )
            except Exception:  # noqa: BLE001 — report-only; never abort the run
                logger.exception("ModelRunner: SHAP explanation failed for %r", name)
                out[name] = None
        return out

    def _original_row(
        self, idx: int, feature_cols: list[str]
    ) -> dict[str, Any] | None:
        """The raw (pre-preprocessing) values of ``feature_cols`` for one TEST row, or ``None``.

        Reads ``self.test_df_`` (post-split, pre-preprocessing) at the given 0-based position;
        returns ``None`` when there are no usable columns or the index is out of range. Shared by
        :meth:`_add_feature_values` and :meth:`_add_llm_narratives` so both resolve values from an
        identical raw-row dict.
        """
        raw_test = self.test_df_
        if raw_test is None or not feature_cols or not (0 <= idx < len(raw_test)):
            return None
        return raw_test.iloc[idx][feature_cols].to_dict()

    def _add_feature_values(self, cfg: dict[str, Any], problem_type: str) -> None:
        """Attach each explained row's ORIGINAL feature values to the SHAP explanations, in place.

        For every model that produced SHAP explanations, resolve each contributed feature back to
        its raw (un-preprocessed) value from ``self.test_df_`` and store the display string on the
        row under ``feature_values`` — keyed identically to ``contributions``. Reuses
        :func:`classifyos.analysis.llm_explain._resolve_feature_display`, so a one-hot ``col_cat``
        feature maps to its source column's raw category and a derived/interaction feature (no raw
        source) resolves to ``None`` rather than a fabricated value. Runs whenever SHAP is on (not
        gated on the LLM flag); report-only, no external calls, no refit, no data mutation.
        """
        from .analysis.llm_explain import _resolve_feature_display

        if problem_type == "multilabel" or not self.explanations_:
            return
        if self.test_df_ is None or self.test_df_.empty:
            return

        feature_cols = [c for c in (cfg.get("feature_cols") or []) if c in self.test_df_.columns]
        if not feature_cols:
            return

        for result in self.explanations_.values():
            if not result or not result.get("rows"):
                continue
            for row in result["rows"]:
                original_row = self._original_row(row["sample_index"], feature_cols)
                row["feature_values"] = {
                    feature: _resolve_feature_display(feature, original_row)[1]
                    for feature in row["contributions"]
                }

    def _add_llm_narratives(
        self, cfg: dict[str, Any], problem_type: str, *, sample_rows: int
    ) -> None:
        """Attach an LLM reason-code ``narrative`` to each explained row, in place.

        For every model that produced SHAP explanations, this asks an Azure OpenAI chat model to
        describe — for each explained TEST row — how the top features pushed the prediction, using
        the SHAP contributions plus the row's ORIGINAL (un-scaled) values from ``self.test_df_``
        and a per-model :class:`~classifyos.analysis.llm_explain.RunContext` (dataset/domain
        context, class base rates, this model's performance, the global feature ranking). Calls
        run concurrently (bounded). Report-only: absent credentials, a missing ``openai`` package,
        or a failed call leave a row SHAP-only (no ``narrative`` key), so this never aborts the
        run. No refit, no data mutation. See :mod:`classifyos.analysis.llm_explain`.
        """
        from .analysis.llm_explain import (
            RunContext,
            derive_dataset_understanding,
            narrate_rows,
            narrator_from_env,
        )

        if problem_type == "multilabel" or not self.explanations_:
            return
        narrator = narrator_from_env()
        if narrator is None:  # unconfigured / SDK missing — already logged; ship SHAP only
            return
        if self.test_df_ is None or self.test_df_.empty:
            return

        target = cfg.get("target", "")
        feature_cols = [c for c in (cfg.get("feature_cols") or []) if c in self.test_df_.columns]
        expl = cfg.get("explainability", {}) or {}
        context_mode = expl.get("context_mode", "both")
        dataset_context = expl.get("dataset_context", "") or ""
        column_context = expl.get("column_context", {}) or {}

        # Shared context (identical across models/rows), computed once.
        class_base_rates = self._class_base_rates(target)
        derived_schema: list[str] = []
        sample_ctx_rows: list[dict[str, Any]] = []
        dataset_understanding = ""
        if context_mode in ("derived", "both"):
            derived_schema = self._derived_schema(feature_cols)
            sample_ctx_rows = self._sample_context_rows(feature_cols)
            # One-time "primer": infer dataset/column/target meaning from the derived facts so the
            # per-row narrator has semantics even when the analyst supplied none. One call per run.
            first_model = next(iter(self.explanations_), None)
            hint_features = (
                [f for f, _ in self._global_features(first_model)] if first_model else []
            )
            primer_ctx = RunContext(
                problem_type=problem_type,
                target=target,
                class_base_rates=class_base_rates,
                context_mode=context_mode,
                derived_schema=derived_schema,
                sample_rows=sample_ctx_rows,
            )
            dataset_understanding = (
                derive_dataset_understanding(
                    narrator, primer_ctx, global_features=hint_features
                )
                or ""
            )

        contexts: dict[str, RunContext] = {}

        def context_for(model_name: str) -> RunContext:
            if model_name not in contexts:
                contexts[model_name] = RunContext(
                    problem_type=problem_type,
                    target=target,
                    class_base_rates=class_base_rates,
                    model_metrics=self._model_headline_metrics(model_name),
                    global_features=self._global_features(model_name),
                    dataset_context=dataset_context,
                    column_context=column_context,
                    context_mode=context_mode,
                    derived_schema=derived_schema,
                    sample_rows=sample_ctx_rows,
                    dataset_understanding=dataset_understanding,
                )
            return contexts[model_name]

        # Build one narration job per (model, explained row).
        jobs: list[dict[str, Any]] = []
        for name, result in self.explanations_.items():
            if not result or not result.get("rows"):
                continue
            run_context = context_for(name)
            for row in result["rows"]:
                idx = row["sample_index"]
                original_row = self._original_row(idx, feature_cols)
                jobs.append(
                    {
                        "key": (name, idx),
                        "params": {
                            "model_name": name,
                            "problem_type": problem_type,
                            "target": target,
                            "explained_class": row["explained_class"],
                            "base_value": row["base_value"],
                            "prediction": row["prediction"],
                            "contributions": row["contributions"],
                            "original_row": original_row,
                            "run_context": run_context,
                        },
                    }
                )

        results = narrate_rows(narrator, jobs)

        n_narrated = 0
        for name, result in self.explanations_.items():
            if not result or not result.get("rows"):
                continue
            for row in result["rows"]:
                narrative = results.get((name, row["sample_index"]))
                if narrative:
                    row["narrative"] = narrative
                    n_narrated += 1
        logger.info("ModelRunner: attached %d LLM narrative(s) to explanations", n_narrated)

    def _class_base_rates(self, target: str) -> dict[str, float]:
        """Population base rate per class from the raw frame (``{label: proportion}``).

        Read from ``self.raw_df_`` (not the balanced train matrix) so the rates reflect the real
        distribution the narrative should reference. Empty when unavailable.
        """
        if self.raw_df_ is None or target not in self.raw_df_.columns:
            return {}
        counts = self.raw_df_[target].astype(str).value_counts(normalize=True)
        return {str(k): float(v) for k, v in counts.items()}

    def _model_headline_metrics(self, model_name: str) -> dict[str, float]:
        """This model's headline TEST metrics (F1-weighted + accuracy) from ``metrics_df_``."""
        if self.metrics_df_ is None or self.metrics_df_.empty:
            return {}
        rows = self.metrics_df_[self.metrics_df_["model"] == model_name]
        if rows.empty:
            return {}
        row = rows.iloc[0]
        out: dict[str, float] = {}
        for key in ("f1_weighted", "accuracy"):
            value = row.get(key)
            if value is not None and pd.notna(value):
                out[key] = float(value)
        return out

    def _global_features(self, model_name: str) -> list[tuple[str, float]]:
        """Top-K globally important features for a model (permutation, else feature-impact).

        Prefers this model's model-agnostic permutation importance; falls back to the pre-training
        raw-feature composite ranking so a model with no permutation result still gets context.
        """
        from .analysis.llm_explain import _GLOBAL_FEATURE_TOP_K

        perm = (self.permutation_importances_ or {}).get(model_name)
        if perm:
            ranked = sorted(perm.items(), key=lambda kv: kv[1], reverse=True)
            return [(str(f), float(v)) for f, v in ranked[:_GLOBAL_FEATURE_TOP_K]]
        if self.feature_impact_ is not None and not self.feature_impact_.empty:
            fi = self.feature_impact_.sort_values("composite_score", ascending=False)
            return [
                (str(r["feature"]), float(r["composite_score"]))
                for _, r in fi.head(_GLOBAL_FEATURE_TOP_K).iterrows()
                if pd.notna(r.get("composite_score"))
            ]
        return []

    def _derived_schema(self, feature_cols: list[str]) -> list[str]:
        """One compact fact line per feature column, derived from the raw frame.

        Numeric → ``col (numeric): min=.. median=.. max=..``; else → ``col (categorical):
        examples a, b, c``. Lets the model infer meaning under ``context_mode`` derived/both.
        """
        if self.raw_df_ is None:
            return []
        lines: list[str] = []
        for col in feature_cols:
            if col not in self.raw_df_.columns:
                continue
            series = self.raw_df_[col]
            if pd.api.types.is_numeric_dtype(series):
                nunique = int(series.nunique(dropna=True))
                is_int = pd.api.types.is_integer_dtype(series)
                # A low-cardinality integer column is almost certainly a category CODE, not a
                # measured quantity — label it so the narrator won't read it as a magnitude.
                if is_int and nunique <= 20:
                    examples = [str(v) for v in series.dropna().unique()[:5]]
                    joined = ", ".join(examples)
                    lines.append(
                        f"- {col} (category code, integer-coded): {nunique} distinct, "
                        f"e.g. {joined}" if joined else f"- {col} (category code)"
                    )
                    continue
                try:
                    lines.append(
                        f"- {col} (numeric): min={series.min():.4g}, "
                        f"median={series.median():.4g}, max={series.max():.4g}"
                    )
                except (TypeError, ValueError):
                    lines.append(f"- {col} (numeric)")
            else:
                examples = [str(v) for v in series.dropna().unique()[:5]]
                joined = ", ".join(examples)
                lines.append(f"- {col} (categorical): examples {joined}" if joined else f"- {col}")
        return lines

    def _sample_context_rows(self, feature_cols: list[str]) -> list[dict[str, Any]]:
        """A couple of raw sample rows (feature columns only) to seed derived context."""
        from .analysis.llm_explain import _DERIVED_SAMPLE_ROWS

        if self.raw_df_ is None or not feature_cols:
            return []
        cols = [c for c in feature_cols if c in self.raw_df_.columns]
        if not cols:
            return []
        head = self.raw_df_[cols].head(_DERIVED_SAMPLE_ROWS)
        return [{k: v for k, v in rec.items()} for rec in head.to_dict(orient="records")]

    def _build_feature_importance_df(self) -> pd.DataFrame:
        """Flatten each model's native feature importance into ranked long-form rows.

        One row per (model, feature) with the model's own importance value and a 1-based
        ``rank`` (descending by importance within that model). Models that expose no native
        importance (RBF-SVM, GaussianNB → ``feature_importance()`` is ``None``) contribute
        no rows. Returns an empty frame with the locked columns when no model exposes any,
        so the CSV is always written with a stable header.
        """
        columns = ["model", "feature", "importance", "rank"]
        rows: list[dict[str, Any]] = []
        for name, importances in self.feature_importances_.items():
            if not importances:  # None (no native importance) or empty dict
                continue
            ranked = sorted(importances.items(), key=lambda kv: kv[1], reverse=True)
            for rank, (feature, value) in enumerate(ranked, start=1):
                rows.append(
                    {
                        "model": name,
                        "feature": feature,
                        "importance": float(value),
                        "rank": rank,
                    }
                )
        return pd.DataFrame(rows, columns=columns)

    def _build_permutation_importance_df(self) -> pd.DataFrame:
        """Flatten each model's PERMUTATION importance into ranked long-form rows.

        Same shape as :meth:`_build_feature_importance_df` (``model, feature, importance,
        rank``; 1-based ``rank`` descending within each model), but the values are the
        model-agnostic permutation drop in F1-weighted — so every model contributes rows,
        including the SVM / NaiveBayes that produce nothing natively. Importances may be
        slightly negative (shuffle noise); ranking by raw value is still correct. A model
        whose measure could not be computed (``None``) contributes no rows; an empty frame
        with the locked columns is returned when no model has any, so the CSV always has a
        stable header.
        """
        columns = ["model", "feature", "importance", "rank"]
        rows: list[dict[str, Any]] = []
        for name, importances in self.permutation_importances_.items():
            if not importances:  # None (not computed) or empty dict
                continue
            ranked = sorted(importances.items(), key=lambda kv: kv[1], reverse=True)
            for rank, (feature, value) in enumerate(ranked, start=1):
                rows.append(
                    {
                        "model": name,
                        "feature": feature,
                        "importance": float(value),
                        "rank": rank,
                    }
                )
        return pd.DataFrame(rows, columns=columns)

    def _build_explanations_df(self) -> pd.DataFrame:
        """Flatten the per-row SHAP explanations into long-form rows for the CSV artifact.

        One row per (model, sample_index, feature) with that feature's signed contribution,
        plus the row's ``explained_class`` / ``base_value`` / ``prediction`` repeated for
        context (``base_value + Σ contribution == prediction`` within each model+row group).
        Models with no explanation (failed / multilabel / OFF) contribute no rows. Returns an
        empty frame with the locked columns when there is nothing, so the CSV — written only
        when explainability is enabled — always has a stable header.
        """
        columns = [
            "model",
            "sample_index",
            "explained_class",
            "base_value",
            "prediction",
            "feature",
            "contribution",
            # The feature's ORIGINAL (raw, pre-preprocessing) value for this row; empty string for a
            # derived/interaction feature with no raw source (or when values weren't resolved).
            "feature_value",
            # Optional LLM reason-code narrative (repeated per feature row of a given model+row
            # group); empty string when narratives were OFF or a call failed (opt-in).
            "narrative",
        ]
        rows: list[dict[str, Any]] = []
        for name, result in self.explanations_.items():
            if not result or not result.get("rows"):
                continue
            for row in result["rows"]:
                narrative = row.get("narrative", "")
                feature_values = row.get("feature_values", {})
                for feature, contribution in row["contributions"].items():
                    value = feature_values.get(feature)
                    rows.append(
                        {
                            "model": name,
                            "sample_index": row["sample_index"],
                            "explained_class": row["explained_class"],
                            "base_value": row["base_value"],
                            "prediction": row["prediction"],
                            "feature": feature,
                            "contribution": float(contribution),
                            "feature_value": value if value is not None else "",
                            "narrative": narrative,
                        }
                    )
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
            # Decision policy as REQUESTED (the per-model effective threshold reached lives on
            # the metrics rows / API). Display + governance only.
            "decision_policy": {
                "calibrate_probs": bool(cfg.get("calibrate_probs", True)),
                "threshold_mode": cfg.get("threshold_mode", "default"),
                "threshold": cfg.get("threshold"),
                "threshold_metric": cfg.get("threshold_metric"),
            },
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
