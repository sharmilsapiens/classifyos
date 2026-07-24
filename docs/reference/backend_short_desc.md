# ClassifyOS — Plain-Language Build Summary

What got built, phase by phase, in everyday language. For someone non-technical, or for
anyone returning after a break who wants the gist without reading code.

---

## Phase 0 — Project scaffold & environment setup (✅ Done, 2026-06-12)
**In one line:** Laid the empty skeleton of the whole project — folders, plumbing, and tooling — so later work has a place to live.
- Repo structure: created the backend (Python), frontend (React), and supporting folders matching the planned module map, with empty packages ready to fill in.
- StorageAdapter: a single "file gateway" so the app reads/writes through one place (local folders now, cloud storage later) instead of touching files directly.
- Environment & templates: requirements list, an `.env.example` template, `.gitignore`, and a stubbed API contract doc — everything needed to set up a fresh machine.
- Sample data: scaffolded the place for sample datasets and a React (Vite + TypeScript) frontend shell with a dev proxy to the backend.

## Phase 1 — Framework skeleton (✅ Done, 2026-06-12)
**In one line:** Built the first working pieces of the data pipeline — reading a file, understanding it, loading it, and splitting it for training.
- config.py: defines the settings for a run and validates them (catches bad inputs before anything runs).
- io/inspect.py: peeks at a data file and reports its columns, types, missing values, and a guess at the problem type — without fully loading it.
- io/loader.py: actually loads the data (CSV/Excel/Parquet), checks the target and features are valid, and standardises the target column.
- split.py: divides data into training and test sets — keeping class balance, or splitting by time when asked.
- Tests: 22 automated checks passing on real sample data; synthetic sample datasets (policy lapse, fraud, risk tier) generated.

## Phase 2 — Feature impact analysis (✅ Done, 2026-06-12)
**In one line:** Added a tool that ranks which input columns most strongly relate to the thing we're predicting, with a chart to show it.
- analysis/feature_impact.py: scores every feature against the target using several statistical measures and combines them into one ranked list.
- CSV output: writes `feature_impact_summary.csv` — the ranked table of features and their scores.
- PNG output: writes `plot4_feature_impact.png` — a two-panel chart (top features by combined score, plus a metric comparison).
- ID-column guard: flags columns that look like identifiers (almost all unique values) as leakage-bait — marked, not silently used.

## Phase 2 follow-up — Environment hardening (✅ Done, 2026-06-12)
**In one line:** Tidied up how the project finds its data folders and made sure tests never make a mess in real output folders.
- Data folders moved outside the repo so datasets and results never get committed by accident.
- dotenv notes: documented that only the test suite auto-loads `.env`; the engine, CLI, and API must load it themselves (otherwise they fall back to default local folders).
- Test isolation: tests now write their outputs to a temporary folder instead of the real output directory.

## Phase 3 — Preprocessing (✅ Done, 2026-06-12)
**In one line:** Built the data-cleaning stage — and made its central rule "learn only from training data" enforceable and tested.
- preprocessing/preprocess.py: a `Preprocessor` that fills missing values, caps outliers, encodes categories, and scales numbers.
- Leakage guard: every statistic it uses is learned from the training data only and merely applied to the test data — the core "no data leakage" rule, baked into the design.
- Smart encoding: switches encoding strategy automatically for high-cardinality columns, and handles multiclass problems where target-based encoding doesn't apply.
- Tests: 14 new automated checks (41 total), including dedicated tests that would fail if any leakage crept in.

## Phase 4 — Feature engineering & interactions (✅ Done, 2026-06-12)
**In one line:** Added a stage that builds new helper columns from the existing ones — squared terms, ratios, bins for skewed numbers, and combinations of two columns — deciding what to build from the training data only (60 tests passing).
- `FeatureBuilder` (preprocessing/features.py): adds squared terms (off by default), ratio columns, and quantile "bucket" columns for very skewed numbers — each decided on the training data and applied unchanged to the test data.
- `InteractionFeatureBuilder` (preprocessing/interactions.py): combines pairs of columns — multiply (`a_x_b`), divide (`a_div_b`), subtract (`a_minus_b`) — either pairs you name or pairs it auto-discovers on training data, with a guard so dividing by (near-)zero never produces infinities.
- PNG output `plot6_interaction_summary.png`: a bar chart of how strongly each new interaction column relates to the target.
- Dev tool `backend/scripts/dev_run.py`: runs the whole pipeline so far (Phases 1–4) end-to-end on a real CSV and writes the real artifacts (feature_impact_summary.csv, plot4, plot6) to OUTPUT_DIR, failing readably stage-by-stage.

## Phase 5 — Class imbalance handling (✅ Done, 2026-06-15)
**In one line:** Added the stage that evens out lopsided training data (e.g. fraud, where only ~1% of rows are positive) — strictly on the training data, never the test data (70 tests passing).
- `preprocessing/balance.py` (`handle_class_imbalance`): given the training features and labels, it rebalances them one of four ways chosen in the config:
  - **SMOTE** — invents realistic synthetic minority-class rows until the classes are even (with safety guards so it never crashes when the minority is tiny, falling back to simple duplication for a one-of-a-kind class).
  - **Undersample** — randomly drops majority-class rows until the classes are even (and logs how many it threw away).
  - **Class weight** — changes nothing in the data; instead hands the model a "pay more attention to the rare class" instruction. The only option that returns weights.
  - **None** — leaves the data exactly as-is.
- Train-only by design: the function is never even given the test data, so it physically cannot resample or reweight it — the core "no leakage" rule, made structural.
- Multilabel safety: when each row can carry several labels at once (where resampling doesn't make sense), it automatically switches to the class-weight approach and says so.

## Phase 6 — Models & evaluation (✅ Done, 2026-06-15)
**In one line:** Added the part that actually trains models, scores how good they are, and produces a per-customer predictions table — six algorithms, all behind one common interface (117 tests passing).
- Six model wrappers (`models/base.py` + `models/wrappers.py`): Logistic Regression, Random Forest, XGBoost, LightGBM, SVM, and Naive Bayes, all wearing the same "shape" so the rest of the app can use any of them interchangeably — same way of training, predicting, giving class probabilities, and reporting which features mattered.
- Model registry (`models/registry.py`): a lookup table that turns an algorithm name (or a short nickname like "RF" or "XGB") into the right model; new models are added here and nowhere else.
- `evaluate_model` (`evaluation/metrics.py`): given the true answers and the model's predictions, it computes the full scorecard — accuracy, precision/recall/F1, ROC-AUC, PR-AUC, log-loss, MCC, a confusion matrix, a per-class breakdown, and calibration data — all packaged so the web dashboard can read it directly. It deliberately leads with F1 (not accuracy), because accuracy lies on lopsided data like fraud.
- `classify` (`predict.py`): builds the per-row results table — for each test record: the actual label, the predicted label, the probability of each class, the model's confidence, and whether it got it right.
- Rare-class handling carried through: the "pay more attention to the rare class" weights from Phase 5 are fed into every model; SVM uses a calibrated variant so its probabilities are trustworthy; XGBoost's quirk of only accepting numeric labels is handled invisibly.
- Two new libraries (XGBoost, LightGBM) were installed and the exact versions of everything were frozen into a lock file so the setup is reproducible on another machine.

## Phase 7 — Plots, the runner & the command line (✅ Done, 2026-06-15)
**In one line:** Tied every previous stage together so a single command runs the whole thing end-to-end — train every model, score them, draw the charts, and save everything — and added the command-line tool to do it (130 tests passing). **The engine is now feature-complete.**
- `ModelRunner` (runner.py): the conductor. Given a configuration it runs the full pipeline in the correct, leakage-safe order — load the data, rank features, split, clean, engineer features, balance the training data, then train and score every requested algorithm — and writes all the results. It makes a private copy of the configuration so a run never changes the original (you can re-run safely), and if one algorithm trips over a bad edge case it's logged and skipped rather than crashing the whole run.
- `plot_results` (evaluation/plots.py): draws the result charts — confusion matrices (where each model gets right vs wrong), ROC/precision-recall curves (how well each model separates the classes), feature-importance bars (what each model leaned on), and calibration curves (are the probabilities trustworthy). When a chart doesn't apply (e.g. a model with no importances, or calibration for a 3-way problem) it writes a clearly-labelled placeholder so nothing downstream ever finds a missing file.
- The command-line tool (cli.py): `python -m classifyos.cli --file <data> --target <column>`. An `--inspect` mode just profiles the file (columns, missing values, class balance); the normal mode runs everything and prints a tidy per-model scoreboard plus the list of files written. It loads the project's environment settings itself so it always finds the right data and output folders.
- Outputs written for every run: a per-customer predictions table, a model-comparison scoreboard, a per-class breakdown, a JSON "run profile" (an audit record of exactly what was run), and the six charts.
- First real-data run: pointed the tool at a real dataset and trained four algorithms end-to-end — 93–97% accuracy — confirming the whole engine works outside the synthetic samples.

## Phase 7B — Hyperparameter tuning (✅ Done, 2026-06-16)
**In one line:** Added an optional, OFF-by-default Optuna layer that automatically searches for better settings for each model before training it — strictly on the training data, so it never peeks at the test set (147 tests passing).
- `tuning.py` (`tune_model`): for a chosen model, runs a small Optuna "study" that tries different hyperparameter combinations and keeps the best one. One uniform mechanism for all six models; rich search spaces for the tree models that benefit most (XGBoost, LightGBM, RandomForest) and thinner ones for the rest (LogisticRegression tunes its regularisation strength `C`; SVM is slow; NaiveBayes barely changes).
- Runtime dials (all in config / on the CLI): which models to tune, the metric to optimise (default F1-weighted), how many trials, a per-model time cap, and k-fold-vs-single-split scoring. Tuning is OFF unless you ask for it.
- No leakage: every candidate is scored using cross-validation *inside the training split only*; the test set is never touched. Balancing (SMOTE) is applied only to the final fit, never inside the tuning folds.
- Safety: each model is tuned independently — if one model's search errors, it quietly falls back to defaults and the run continues. A **hard default time cap (600s per model)** means a tuning run can never run unbounded.
- The conductor (ModelRunner) calls the tuner before fitting each requested model, feeds the best settings into the final fit, and records what was tuned (and the winning settings) in `run_profile.json`. CLI flags: `--tune`, `--tune-models`, `--tune-metric`, `--trials`, `--timeout`, `--tune-cv-folds`.
- **7B.2 follow-up (2026-06-23):** widened three search spaces after a read-only audit — LightGBM now also tunes `max_depth` (so its leaf-wise trees can't grow unbounded against a large leaf count), XGBoost gains `gamma` (an extra "don't bother splitting unless it helps enough" dial), and SVM's kernel is now a genuine rbf-vs-linear choice (with the rbf-only `gamma` skipped when linear is picked). Tuning is still OFF by default and a non-tuning run is unchanged.

## Tooling — Doc-update enforcement hook (✅ Done 2026-06-15, ❌ Removed 2026-06-16)
**In one line:** Briefly added a safety net that wouldn't let a coding session finish if it changed the ML engine but forgot to update the project's living docs — then removed it as ineffective.
- `scripts/check_docs_updated.py`: checked (via git) whether any pipeline code under `backend/classifyos/` changed; if so, it required both PROJECT_STATE.md and backend_short_desc.md to have been updated too.
- Was registered as a Claude Code "Stop" hook in `.claude/settings.json`.
- **Removed 2026-06-16:** the hook could detect that files changed but not that the docs were *meaningfully* updated, and it missed cases anyway. Doc-update discipline now lives in the phase prompts instead (and in CLAUDE.md's working-style rules). The script and the hook entry are gone.

## RUNBOOK.md — operator's manual (✅ Done, 2026-06-15)
**In one line:** RUNBOOK.md added — a plain, command-first guide to running the ML engine from the terminal and reading the results, written against the real CLI and verified with live runs.
- Covers setup (venv + `.env`, the relative-default fallback caveat), `--inspect`, every CLI flag with its default, worked binary/multiclass examples, what each of the 11 output files means, the re-run overwrite limitation (fixed filenames → use `--output-dir` to keep runs), and a troubleshooting table.

## Phase 11 — Multilabel end-to-end + performance baseline (✅ Done, 2026-06-20)
**In one line:** Made the multilabel use case (Product Recommendation) actually run end-to-end
for the first time, and measured the engine's speed on a 10k+ row dataset.
- **Multilabel was wired up.** A multilabel target is a single column holding a `|`-separated SET
  of labels per row (e.g. `Auto|Home`). A new small bridge (`classifyos/multilabel.py`) turns
  that into the yes/no-per-label table the models need (using a tool fitted on the **training rows
  only**, so it never peeks at the test set). The conductor (ModelRunner) now builds that table,
  trains a true multilabel model (one classifier per product), and reports **per-label** scores, a
  **per-label** ROC/PR curve, a **per-label** precision/recall report, and a predictions table that
  shows the predicted product SET.
- **Honest about limits.** A single confusion matrix and MCC aren't defined for a multilabel
  target, so those are reported as "not applicable" rather than faked. Rebalancing (SMOTE) isn't
  defined for a multi-label row, so it falls back to class-weight with a warning (documented).
  These are additive changes keyed to the multilabel path — binary and multiclass behaviour is
  untouched and all prior tests stay green.
- **All seven use cases** (3 binary, 3 multiclass, 1 multilabel) now run through the engine and
  API in one sweep (`tests/test_use_case_sweep.py`), each producing the full 11-artifact set.
- **Performance baseline:** timed `ModelRunner.run()` on a 12,000-row synthetic dataset (4
  algorithms, tuning off) and a realistic tuning sanity run (one model, 25 trials) to confirm the
  hard per-model time cap bounds it. See PROJECT_STATE.md for the measured numbers.

## Phase 14 — User-defined structured features (✅ Done, 2026-06-23)
**In one line:** Let a user add their own derived columns — picked from dropdowns, never
typed as a formula — so analysts can build domain features (like `duration = end_date −
start_date` or `premium ÷ sum_assured`) without writing or running any code.
- **`UserFeatureBuilder` (preprocessing/user_features.py):** a new leakage-safe
  fit/transform builder (same discipline as the existing FeatureBuilder). It reads a list of
  STRUCTURED specs and builds exactly the columns asked for.
- **What it can build (fixed allowlists only):** two-number ops (add / subtract / multiply /
  divide / ratio, with the same divide-by-near-zero guard the ratio features use); a
  date-difference (`end − start`) turned into a numeric duration in a chosen unit
  (seconds/minutes/hours/days); and single-column transforms — `log`, `abs`, quantile `bin`,
  and pulling a date part (`year`/`month`/`day`/`day-of-week`/`hour`) out of a date column.
- **Safety — no formulas, ever.** The user never sends a formula string the backend
  evaluates; they choose a column + an operation from a fixed list + (optionally) a second
  column + a name. The backend applies only KNOWN operations to KNOWN columns — `eval`/`exec`
  are never used on user input (a [RISK] comment marks this). Unknown operations/types are
  rejected the moment the config is built.
- **No leakage, no surprises.** Anything the builder needs to learn (bin edges, the
  divide-fill value) is learned from the TRAINING rows only and applied unchanged to the test
  rows. A spec that points at a missing column, the wrong column type, or the target is simply
  skipped with a clear logged reason — it never crashes the run — and a name that clashes with
  an existing column is refused so nothing is ever overwritten.
- **OFF by default.** With no user features configured (the default) a run is byte-for-byte
  identical to before. The new columns slot into the pipeline right after the automatic
  feature engineering and before the interaction step, so they can themselves become
  interaction candidates and are present for balancing and training. Engine layer only — the
  API and UI that let users define these are separate follow-up sessions. (24 new tests.)

## ⚠ Temporary change — interaction features unwired (2026-06-25)
**In one line:** By request, the "interaction features" stage (Phase 4's column-combining step)
was **temporarily switched off** in training and **hidden from the dashboard** — not deleted, and
reversible at any time.
- **Engine:** the conductor (ModelRunner) now forces interaction features OFF for every run, no
  matter what the request asks for, so no `a_x_b`/`a_minus_b` combined columns are built and the
  interaction summary chart (`plot6`) is no longer produced. The API still reports an
  `interaction_cols` list — it's just empty — so nothing downstream breaks.
- **Dashboard:** the Interaction-features controls on the Configuration page, the sidebar link,
  and the Interaction Features result page are hidden (the page's code is kept in place, just
  unwired); visiting `/interactions` redirects to the home page.
- **Note:** the ordinary ratio features from Phase 4 (`a_div_b`) are a *separate* feature; they were
  also unwired on 2026-06-26 (see the next section), so the `_div_`-marker caveat that once let a
  ratio column surface in `interaction_cols` no longer applies in practice.
- **To restore:** see PROJECT_STATE.md / plan_tweak.md row 42 — revert the one engine line, the
  plot6 call, the three UI comment blocks, and the matching test edits.

## ⚠ Temporary change — feature engineering unwired (2026-06-26)
**In one line:** By request (pre-demo), the Phase 4 "feature engineering" stage (Section 7's
ratio / binning / polynomial derived columns) was **temporarily switched off** in training and the
**"Feature engineering" config card hidden** — not deleted, and reversible at any time.
- **Engine:** the conductor (ModelRunner) now forces feature engineering OFF for every run, no matter
  what the request asks for, so no `_sq` / `_div_` / `_bin` derived columns are built. Section 7 has
  no chart or CSV of its own, so no artifact disappears; the result's feature list just has fewer
  columns and nothing downstream breaks.
- **Dashboard:** only the "Feature engineering" controls on the Configuration page are hidden. The
  separate **user-defined Feature Builder panel stays visible and fully works** — it is a different
  feature. No result page changes.
- **To restore:** see PROJECT_STATE.md / `unwire.md` entry #2 — revert the one engine line, uncomment
  the config card, and revert the `test_runner` assertion.

## Bugfix — XGBoost/LightGBM on real "dotted/bracketed" column names (✅ Done, 2026-06-26)
**In one line:** XGBoost and LightGBM used to crash on real datasets whose columns came from
flattened JSON (e.g. `covers[0].insuranceAmount`); they now train fine.
- **Why it broke:** both libraries refuse feature names that contain special characters like
  `[`, `]`, `<`. The scikit-learn models (Logistic Regression, Random Forest) don't care, so only
  XGBoost/LightGBM failed — which is exactly what was seen on `arizona_buyingpropensity.csv`.
- **The fix:** the two model wrappers now quietly rename columns to safe placeholder names
  (`f0, f1, …`) just for the library's benefit, then translate the importances back to the real
  column names afterwards. Nothing the rest of the system sees changes, and it's leakage-safe.
- **Heads-up (unrelated):** on that particular dataset every model scored a perfect 1.0, which
  usually means a column is giving away the answer (target leakage). That's logged as a separate
  open item for a data review — it is *not* a model bug.

## Data Profile — exploratory views on upload (✅ Done, 2026-06-26)
**In one line:** When you upload a dataset, the app now profiles every column so the dashboard
can show its distribution and key numbers — averages and spread for number columns, the most
common values for category columns, a missing-data scan, and how the number columns relate.
- **`analysis/profile.py` (`profile_dataframe`):** a new read-only helper that summarises each
  column — for **numbers**: count, mean, median, mode, standard deviation, min/max, the 25th/75th
  percentiles, skew, and a histogram (the shape of the distribution); for **categories** (and
  yes/no columns): the most common values with their counts and a leftover "other" bucket; for
  **dates**: the earliest and latest value. It also computes a **correlation grid** showing how
  strongly the number columns move together.
- **No peeking, no leakage.** It runs on the raw uploaded file, ignores the target entirely, and
  learns nothing that feeds a model — it only decides what to *display*. For very large files it
  profiles a random sample for the heavy charts (the missing-value counts still use every row).
- **Bolted on cleanly.** The existing file-inspector (`inspect_file`) gained an optional
  "also profile this" switch that is **off by default**, so nothing that already used it changes;
  when on, it profiles the file it had already loaded (no second read). Engine + API + dashboard
  page; 10 new engine tests.
- **Update (2026-06-29) — flags two kinds of "watch out" columns.** Each column now carries a
  small list of advisories the dashboard shows as a badge: **"single value"** when a column holds
  only one value (it's the same for every row, so it teaches a model nothing — its spread/skew and
  correlations are blank), and **"identifier-like"** when nearly every row is a different value
  (it looks like an ID or reference number — high churn that won't generalise and can leak the
  answer). Uses the same "near-unique" threshold as the Feature Impact screen so the two agree.
  +2 engine tests.
- **Update (2026-07-03) — identifier-like columns are kept out of the correlation grid.** A
  correlation over near-unique ID values is just noise, so any column flagged "identifier-like" is
  now dropped before the number-column correlation is computed (constant columns are still shown —
  their blank cells honestly say "no variance"). This matches what the dashboard already does for
  those columns' distribution charts. +2 engine tests.

## Train-vs-test metrics — the overfit gap (✅ Done, 2026-06-26)
**In one line:** Every model now reports its scores on the **training data** alongside the
held-out **test** scores, so you can see at a glance whether a model is memorising (great on
train, worse on test) rather than genuinely generalising.
- **What was already true:** all the headline numbers shown in the dashboard were *already* the
  held-out **test** scores (the model never sees the test rows while training) — there was simply
  no train-side number to compare against.
- **What's new:** the conductor (ModelRunner) re-scores each trained model on the **pre-balance
  training split** — the real training rows at their natural class mix, *not* the SMOTE-balanced
  set the model was fitted on — and reports the same headline metrics (accuracy, F1, precision,
  recall, ROC-AUC, PR-AUC, MCC, log-loss) as a parallel `train_*` set. Measuring train on the
  pre-balance rows keeps it the *same distribution* as test, so the train→test gap is a clean
  overfitting signal rather than one muddied by the rebalancing.
- **No leakage, no risk.** The model already trained on these rows; this only *reports* on them.
  A failed model carries nulls; a train-side scoring error is logged and never aborts the run.
- **Surfaced everywhere additively.** The API gained an optional `train` block on each model row
  (locked contract bumped `1.1 → 1.2`, additive only — old clients ignore it) and the dashboard's
  model scoreboard now shows **F1 · train** next to **F1 · test** plus a colour-coded **Gap**
  column (amber/red as the gap widens). Confusion matrices, per-class reports and curves stay
  test-only by design.

## Post-training feature importance — what each model leaned on (✅ Done, 2026-06-26)
**In one line:** Every trained model now reports its own **native** feature importance —
how much each input column actually drove that model's decisions — surfaced as data
(JSON + CSV), not just the existing chart.
- **What it is:** a *post-training, per-model* view, distinct from the existing pre-training
  `feature_impact` screen. The pre-training screen asks "which raw columns correlate with the
  target?" (a property of the data, before any model exists). This asks "which columns did the
  **trained model** rely on?" (a property of the model). They answer different questions and can
  disagree.
- **It's model-dependent.** Random Forest / XGBoost / LightGBM report tree impurity/gain
  importances; Logistic Regression reports coefficient magnitudes. SVM (RBF) and Naive Bayes
  genuinely have no such number, so they're simply omitted — not faked. Because each model
  measures importance its own way, the values are **not comparable across models**.
- **What was already there:** the engine already computed these (each model wrapper's
  `feature_importance()`) and drew them as `plot3_feature_importance.png`. The numbers just lived
  only in the picture.
- **What's new:** the conductor (ModelRunner) now collects them into `feature_importances_` and
  writes a ranked `feature_importance_summary.csv` (one `model, feature, importance, rank` row per
  model that exposes any). No leakage surface — it reads the fitted model's internals only, no test
  data and no re-fitting.
- **Surfaced everywhere additively.** The API gained an optional `result.feature_importance` block
  keyed by model (locked contract bumped `1.2 → 1.3`, additive only — `null`/omitted when no model
  exposes importances, so old runs are unchanged), and the dashboard's Feature Impact page now shows
  a per-model ranked bar + the `plot3` chart beneath the pre-training screen, with a note that
  SVM/Naive Bayes are omitted and values aren't cross-comparable.

## Permutation feature importance — the model-agnostic counterpart (✅ Done, 2026-06-27)
**In one line:** Added a second post-training importance measure that works for **every**
model — including SVM and Naive Bayes, which have no native importance — by measuring how much
each model's accuracy drops when a feature is scrambled.
- **Why:** the native importance above is blank for two of the six models (the RBF-kernel SVM and
  Naive Bayes genuinely expose no per-feature number). This fills that gap so the post-training
  story is complete for all six.
- **What it is:** for each trained model, the engine scores it on the held-out **test** data, then
  shuffles one feature's values at a time and re-scores. The drop in score (F1-weighted, the
  engine's primary metric, averaged over a few shuffles) is that feature's importance — a big drop
  means the model leaned on it heavily. Because it only needs the model's *predictions*, it works
  for any model, and it's measured in one consistent unit, so unlike the native importances these
  values **are** comparable across models.
- **New engine module (`analysis/permutation_importance.py`):** a pure, model-agnostic function.
  It's leakage-safe — it reads the held-out test predictions only, fits nothing, re-trains nothing,
  and never alters the test data (it shuffles a private copy). A fixed random seed makes it
  reproducible. [RISK] noted: two correlated features can both look unimportant because the model
  leans on whichever twin wasn't shuffled; and it costs extra compute (many prediction passes).
- **What's new in the conductor:** ModelRunner collects these into `permutation_importances_`
  (one entry per model — now including SVM/Naive Bayes) and writes a ranked
  `permutation_importance_summary.csv`. Each model is computed in its own safety net, so a failure
  there never aborts the run.
- **Surfaced everywhere additively.** The API gained an optional `result.permutation_importance`
  block keyed by model (locked contract bumped `1.3 → 1.4`, additive only — `null`/omitted when it
  couldn't be computed, so old runs are unchanged), and the dashboard's Feature Impact page now
  shows a "Permutation importance · per model" card — covering all models, with a model picker, a
  ranked bar, and a note about the correlated-feature caveat — beneath the native-importance card.
- **The scoring metric is selectable from the UI** (follow-up, same day). Rather than hardcoding
  F1-weighted, a "Permutation importance metric" selector on the Configuration page lets you choose
  what the shuffle-drop is measured in — any of the engine's reported metrics: accuracy, F1
  (weighted/macro), precision/recall, MCC, and the probability-based ROC-AUC, PR-AUC and log-loss.
  The scorer reuses the engine's one `evaluate_model` so the permutation score is computed
  *identically* to the metric shown elsewhere (no second definition to drift); log-loss is negated
  so "more drop = more important" still holds, and a metric undefined for the problem type (e.g.
  PR-AUC on multiclass) simply yields no importances rather than a fabricated number. It's a
  request-side config field (`permutation_metric`, default F1-weighted) — **no contract/version
  change** — and the chart labels itself with the chosen metric.

## Missing-value treatment split by feature type (✅ Done, 2026-06-27)
**In one line:** The "what to do about blanks" setting is now chosen **separately for number
columns and category columns**, and there are more (and smarter) options to choose from — so an
average can never be wrongly applied to a text column.
- **Why:** there used to be a single global "missing values" setting. Picking "mean" filled every
  blank with the average — which is meaningless for a text/category column, so those quietly fell
  back to the most common value. Splitting the control makes the right behaviour explicit and lets
  you, say, use the median for numbers and forward-fill for categories at the same time.
- **Two controls now:** *Missing values · numeric* and *Missing values · categorical*.
  - **Numbers** can use: median, mean, most-common (mode), forward-fill, **backward-fill (new)**,
    **k-nearest-neighbours (new)**, **iterative/model-based (new)**, or drop-the-row.
  - **Categories** can use: most-common (mode), forward-fill, **backward-fill (new)**, or
    drop-the-row. The number-only options (mean/median/KNN/iterative) aren't offered here because
    they're undefined for text.
- **The two new "smart" imputers (numbers only):** *KNN* fills a blank by looking at the most
  similar rows; *iterative* models each column from the others. Both are **learned from the
  training rows only** and applied unchanged to the test rows (the core no-leakage rule —
  scikit-learn's `KNNImputer` / `IterativeImputer`). **Backward-fill** is the mirror of the
  existing forward-fill (carry the next row's value back instead of the previous row's forward).
- **Backward-compatible.** The old single setting still exists as a legacy default; a run that only
  sets it behaves exactly as before (numbers use it; categories fall back to most-common when it's a
  number-only statistic). "Drop" stays row-level and, as always, only drops training rows — at
  prediction time every row is kept and filled instead. Engine + API + dashboard; new tests across
  all three (293 backend pytest · 97 frontend vitest).

## Decision policy — calibration & decision threshold made real (✅ Done, 2026-06-30)
**In one line:** The "Decision threshold" and "Calibrate probabilities" settings — which were
shown in the UI but secretly did **nothing** — now actually work: the engine can tune the
positive/negative cut-off for the best score, or use a value you set, and it can calibrate
probabilities so a "0.8" really means about 80%.
- **The problem we found:** both settings were passed all the way through (screen → API →
  config) but the engine never read either. Predictions always used the built-in 0.5 cut-off,
  and the only calibration anywhere was the SVM's own internal one. So the threshold control was
  a dead switch, and the risk-register's claim that "threshold is configurable" was misleading.
- **Two different things, both now wired up.** *Calibration* reshapes the probabilities so they
  are trustworthy; the *decision threshold* decides where to cut a (now trustworthy) probability
  into a yes/no. They are independent — calibration makes a threshold meaningful but doesn't pick
  one. For lopsided problems (fraud, lapse) the 0.5 default is rarely the best cut, so calibration
  alone was not enough.
- **Threshold (binary only) — three modes:** *default* (the old 0.5 cut), *fixed* (use the value
  you set), or *tuned* — the engine searches for the cut-off that maximises a chosen score (F1,
  balanced accuracy, precision, recall, …) using cross-validation **inside the training data
  only**, so the held-out test set never influences the operating point (no leakage). The
  effective cut-off each model ended up using is reported back. Multiclass/multilabel keep their
  argmax and ignore the threshold.
- **Calibration (binary + multiclass), ON by default now.** Each model's probabilities are
  calibrated on the training data only (scikit-learn's `CalibratedClassifierCV`). The SVM is
  skipped (already calibrated) and multilabel is left as-is. This is a deliberate behaviour change
  — every run now calibrates by default, which is slightly slower but gives better probabilities,
  which the insurance use cases want.
- **No new ML written, no model code rewritten.** It composes scikit-learn's own building blocks
  (`CalibratedClassifierCV`, `FixedThresholdClassifier`, `TunedThresholdClassifierCV`) in one new
  helper (`models/decision.py`); the six model classes are untouched. A careful detail: the
  calibration/threshold wrappers hide a model's "what mattered" numbers, so the importance read-out
  now unwraps to the real model first — otherwise native importance would have silently vanished
  the moment calibration (now default) switched on.
- **Surfaced additively.** The API gained request fields (`threshold_mode`, `threshold_metric`)
  and two new per-model result fields — the effective `decision_threshold` and whether the model is
  `calibrated` (locked contract bumped `1.4 → 1.5`, additive only; old clients ignore them). The
  dashboard controls + result badges are a separate follow-up session. Engine + API + tests this
  session (**315 backend pytest green**, +16 net new).

## Missing values — per-column choice (✅ Done, 2026-07-01)
**In one line:** On top of the by-type setting, you can now pick the fill method **for an
individual column** — so one number column can use KNN while the rest use the median, or one
category column can forward-fill while the rest use most-common.
- **Why:** the previous step let you choose one method for *all* number columns and one for *all*
  category columns. That's still the sensible default, but sometimes a single column wants
  different treatment (e.g. a time-ordered column that should forward-fill, or a column with a
  strong relationship to others that suits KNN). This adds a per-column override on top of the
  type defaults.
- **How it works:** a new optional setting `missing_strategy_by_column` maps a column name to its
  own strategy. Any column you don't list keeps its per-type default, so leaving it empty is
  **byte-for-byte identical** to before. On the Configuration page a "Missing values · per column"
  card lists your selected feature columns; each has a dropdown defaulting to "Type default" and
  offering the strategies valid for that column's kind (numbers get the full set incl. KNN /
  iterative; categories get most-common / forward-fill / backward-fill / drop).
- **Mixing is allowed now.** Because the strategy is resolved per column, a single run can use KNN
  on one number column and iterative on another (both learned from the training rows only, applied
  unchanged to test — the same no-leakage rule). "Drop" stays row-level and only ever drops
  training rows.
- **Foolproofing:** if you somehow name a number-only method (mean/KNN/…) for a category column,
  the engine quietly coerces it back to that column's type default rather than erroring — the same
  fallback used when a number-only global meets a text column. Unknown strategy names are rejected
  when the config is built (a 422, not a crash).
- **Backward-compatible & additive.** Engine + API (request-side only, **no contract/version
  change** — the response is unchanged) + dashboard. New tests across all three
  (**323 backend pytest · 119 frontend vitest**).

## Explainability — per-row SHAP, rewired for real (✅ Done, 2026-07-01)
**In one line:** The Explainability page is back — and it now shows a real, per-prediction
"why": for a single policy/claim, which features pushed the model's answer up or down, and by
how much (a SHAP waterfall), for **all six** models.
- **The backstory:** this page had been hidden because the honest answer used to be "we can't do
  it yet." A live web request holds no trained model in memory, so explaining a row *after* a run
  seemed to need model persistence (a v2.0 / MLflow item). That blocker is now gone — we simply
  compute the explanations **during** the run, while the models are still in memory, and send them
  back with the results, exactly like the two importance screens already do. No model persistence
  needed.
- **What it shows:** pick a model and a test row → a **waterfall** that starts at the model's
  average prediction (the "base value") and adds each feature's signed contribution to land on
  this row's prediction. Red bars pushed the prediction up, green pulled it down; the numbers add
  up exactly (base + all contributions = the prediction). This is the reason-code / adverse-action
  view insurance needs ("this policy was flagged high-lapse-risk *because* of X, Y, Z").
- **How (SHAP):** a new engine helper (`analysis/explain.py`) uses the industry-standard **SHAP**
  library — the fast, exact *TreeExplainer* for the tree models (Random Forest / XGBoost /
  LightGBM) and the model-agnostic *KernelExplainer* for Logistic Regression / SVM / Naive Bayes.
  So it covers **all six** models — better than the native importance screen, which can't do
  SVM/Naive Bayes. (Before writing it, the exact SHAP calls were checked against the installed
  version and confirmed to add up for every model — the project's hallucination-check rule.)
- **Opt-in, because it costs.** It's **OFF by default** (a new "Per-row explainability (SHAP)"
  toggle on the Configuration page); the SVM/Naive Bayes path in particular is slow, so it's
  bounded to a small sample of rows and only runs when you ask. No leakage: SHAP's reference data
  is a sample of the **training** rows (never fitted on), the explained rows are read-only test
  rows, and nothing is re-trained.
- **Surfaced additively.** The API gained an optional `result.explanations` block (locked contract
  bumped `1.5 → 1.6`, additive — absent when the toggle is off, so old runs are unchanged) plus an
  `explanations_summary.csv` artifact. The page was rewritten to draw the real waterfall (the old
  "coming in v2.0" placeholder is gone) and put back in the sidebar. The `/api/v1/explain` endpoint
  stays as a documented stub that now points callers to the `/run` explanations. Engine + API +
  dashboard, new tests across all three (**337 backend pytest · 122 frontend vitest**); `shap`
  added to requirements. This **restores** unwire.md entry #3.

## Explainability — LLM reason-code narratives on top of SHAP (✅ Done, 2026-07-03)
**In one line:** Each explained row can now carry a short plain-language paragraph — written by
an Azure OpenAI model from the row's own SHAP numbers — that says, in words an underwriter can
read, how the top features drove that prediction.
- **What it adds:** the SHAP work above gives the *numbers* behind one prediction (base value,
  each feature's signed push, the additive landing point). This turns those same numbers into a
  2–4 sentence reason-code narrative — "flagged high lapse risk chiefly because of a high number
  of late payments, only partly offset by a longer tenure" — so a claims/underwriting user doesn't
  have to read a waterfall.
- **How:** a new pure engine module (`analysis/llm_explain.py`) builds an Azure OpenAI chat client
  from five `AZURE_OPEN_AI_*` environment variables and, for each explained row, sends the top
  features (by |contribution|), their signed SHAP pushes, the row's feature values, the base value
  and the prediction, asking for a short grounded paragraph. The `openai` package is imported
  **lazily** and only when narratives are requested — the exact same opt-in / lazy-import
  discipline as `shap` and `optuna`.
- **Opt-in twice, and safe to fail.** It is **OFF by default**, gated by a new
  `explainability.llm_narratives` flag that also requires SHAP (`explainability.enabled`) to be on.
  If the credentials are absent, the `openai` package is missing, or a call errors/times out, the
  run simply ships SHAP without narratives — a report-only layer that never aborts a run and adds
  no new ML or leakage surface (it only reads values SHAP already computed; nothing is refit).
- **Scope:** one narrative per explained (model, row) for **all** models that produced SHAP, over
  the same `sample_rows` cap (default 20 rows). Binary + multiclass (multilabel isn't explained).
- **Surfaced additively.** The API gained `result.explanations[model].rows[].narrative` (locked
  contract bumped `1.6 → 1.7`, additive — `null` unless narratives were on AND credentials
  configured, so a SHAP-only run is unchanged), and `explanations_summary.csv` gained a `narrative`
  column. Engine + API + dashboard (a toggle on Configuration + the narrative rendered above the
  waterfall); new tests across all three; `openai` added to requirements. Hallucination check ✅ —
  `AzureOpenAI(...)` + `chat.completions.create(...)` verified against the installed openai 1.109.1.

## Explainability — context-aware, original-value narratives (✅ Done, 2026-07-03)
**In one line:** The LLM narratives now read like a human wrote them — they cite the **original
(un-scaled) values** ("status.description = 4", "coverage = 500,000"), compare the prediction to the
**class base rate**, and use **domain meaning** you supply, instead of restating a scaled number.
- **The problem:** the first cut fed the model the *scaled* feature values ("Decision_Days =
  -1.473"), no idea what the columns/target mean, and only that one row — producing mechanical text.
- **Original values.** The narrator now maps each SHAP feature back to its raw value from the
  retained pre-preprocessing test rows (`test_df_`): a numeric column shows its real number, a
  one-hot column shows the source column's category, and a derived/interaction feature with no raw
  source keeps its contribution without inventing a value.
- **Dataset context — you choose the source.** A new `context_mode` (**given / derived / both**)
  controls what the model sees: `given` uses the free-text `dataset_context` (what the data/target
  mean) plus per-column `column_context` notes you write; `derived` lets the model infer meaning
  from data the engine already has (column headers, a couple of sample rows, light stats, class base
  rates); `both` combines them. [RISK] privacy — `derived`/`both` send sample data values to Azure
  (opt-in, documented).
- **Whole-run context in every call.** Each narrative is now framed against the model's headline
  performance, the class base rates, and the global feature ranking — assembled once per model into
  a `RunContext` and placed in the (stable) system message, with only the row's own values in the
  user message.
- **Faster + more robust.** Calls now run over a small **thread pool** (default 6) instead of one
  at a time, cutting a `rows × models` sweep from minutes to seconds. The token budget was raised
  and a **length-truncation retry** added because the richer prompt makes reasoning models (gpt-5)
  spend far more hidden reasoning tokens — without it some rows came back empty.
- **Request-side only — no contract/version change** (the response `narrative` is still a string).
  Engine + API + dashboard (a "Context mode" selector, a dataset-context textarea, and a per-column
  notes panel, shown only when the narrative toggle is on); new tests across all three. Verified live
  against the Azure `gpt-5` deployment on `arizona_buyingpropensity.csv`. Hallucination check ✅ — no
  new library calls (same `openai` chat API, `concurrent.futures` stdlib).

## Explainability — narratives that read as prose, not a SHAP readout (✅ Done, 2026-07-03)
**In one line:** With no context supplied, narratives still restated the SHAP numbers ("Decision_Days
= 2 reduced the score by 0.1040…"); they now read as a short underwriter's note that names the two or
three real drivers in business terms — and the model figures out what the columns mean on its own.
- **Prompt redesign.** The narrator's instructions now forbid printing SHAP numbers / base value /
  `feature = value (±x)` lists; it uses the contributions only to pick the top 2–3 drivers and their
  direction, compares the case to the class base rate in words, treats integer-coded categoricals as
  category *codes* (not magnitudes), and writes flowing prose. The per-row feature list was trimmed
  from 8 to 5 to keep the focus on the few drivers that matter.
- **Dataset-understanding "primer".** Because auto-derived context was just numbers (min/median/max,
  sample rows) with no *meaning*, a single extra LLM call per run now infers — from the headers,
  per-column facts, sample rows, target and class balance — what the dataset is, what the target
  means, and each key column's likely business meaning. That inferred paragraph is reused in every
  row's prompt (labelled a *hypothesis*, so any analyst-supplied context still wins). This gives the
  narrator real semantics even when the analyst types nothing. It runs only in `derived`/`both` mode,
  once per run (not per row), and degrades to no-primer behaviour on any failure.
- **Coded columns flagged.** Low-cardinality integer columns are labelled "category code" in the
  derived facts so the model describes them qualitatively instead of as amounts.
- **Result (verified live on `arizona_buyingpropensity.csv`, no human context):** *"This case looks
  well below the typical conversion rate for our book. The primary negative driver is the application
  status being in category 4… and a very fast decision turnaround of two days further lowered the
  chance…"* — no raw numbers, drivers named in business terms.
- **Engine-internal only** — prompt/primer quality; no `config`/API/contract/frontend/`schema_version`
  change (reuses the existing `context_mode`). +1 LLM call per run. Tests extended; hallucination
  check ✅ (same `openai` chat API, no new libraries).

## Explainability — feature values shown next to their SHAP push (✅ Done, 2026-07-03)
**In one line:** The waterfall now shows each feature's **actual value** beside its contribution
(`num_late_payments = 3` pushed the prediction up), so a reason code says not just *which* feature
mattered but *what its value was* — the missing half of an adverse-action explanation.
- **Why:** SHAP is complete without it (base value + all pushes = the prediction), but a bare
  "num_late_payments pushed +0.10" doesn't tell you the value that drove it. The canonical SHAP
  waterfall labels each row `feature = value`, and the insurance reason-code use case needs the value
  to be actionable. Tellingly, the LLM-narrative path already resolved these raw values internally —
  they were just locked inside prose and never surfaced for the chart.
- **How:** the conductor (ModelRunner) now attaches, to every explained row, each contributed
  feature's **original (raw, pre-preprocessing) value** — reusing the exact resolver the narrative
  path already uses, so a one-hot `col_cat` feature maps back to its source column's category and a
  derived/interaction feature with no raw source stays value-less rather than faked. It reads the
  retained held-out test frame the engine already keeps; no re-fitting, no new library calls, no
  leakage surface.
- **Always on with SHAP (not gated on the LLM flag).** Feature values appear whenever per-row
  explainability is on, independent of whether the Azure narrative is enabled.
- **Surfaced additively.** The API gained `result.explanations[model].rows[].feature_values` (locked
  contract bumped `1.7 → 1.8`, additive — present whenever explanations are), the
  `explanations_summary.csv` gained a `feature_value` column, and the dashboard waterfall renders
  `feature = value` next to each bar (falling back to the plain name when a value can't be resolved).
  Engine + API + dashboard; new tests across all three (**360 backend pytest · 128 frontend vitest**,
  `tsc -b` + `vite build` clean). Verified live on `policy_lapse.csv` (values like `age = 61`,
  `annual_premium = 6904` resolved). Hallucination check ✅ — no new library calls.

## MLflow run logging & model persistence — Databricks integration Phase A (✅ Done, 2026-07-08)
**In one line:** A run can now be **recorded in MLflow** — its settings, each model's scores, all
the output files, and a **saved copy of every trained model** — so results survive, runs stack up
as history, and the trained models can be shared and re-loaded (locally now; Databricks later).
- **The gap it closes:** until now the engine kept **nothing** between runs — trained models lived
  only in memory and were thrown away, and the output files used fixed names so each run overwrote
  the last. This is the first piece of the "run it on Databricks" plan (`docs/databricks_integration.md`
  §6, Phase A), and it also fixes those persistence/overwrite gaps immediately.
- **What it does when switched on:** after training finishes, the runner logs to MLflow — the run
  **config** (as searchable parameters), each model's **headline test metrics**, the **existing
  artifact files** (the CSVs, the charts, the run profile), and **one saved model per algorithm**
  using the right serializer for each (`mlflow.xgboost` / `mlflow.lightgbm` / `mlflow.sklearn`). Each
  saved model is the trained algorithm itself (the calibration/threshold wrapper is peeled off first —
  the same unwrap the feature-importance read-out already does, and the only form the XGBoost/LightGBM
  savers accept). Every saved model was verified to **load back and predict**.
- **OFF by default, and safe to fail.** It's opt-in (a new `mlflow` config block, `enabled` false by
  default) and follows the exact same discipline as the SHAP/Optuna/OpenAI features — the `mlflow`
  library is imported **only when asked for**, and **every failure is swallowed** (a missing package,
  an unreachable store, a model that won't serialize) so logging can never abort a training run. A run
  with it off is byte-for-byte identical to before.
- **No leakage, all I/O through the gateway.** Logging happens strictly **after** training and reads
  nothing back into the model-fitting; it only serializes already-trained models and copies
  already-written files. Every artifact path is resolved through the StorageAdapter (no hardcoded
  paths); MLflow's own store is its internal mechanism (like Optuna's).
- **Where it logs.** Locally by default — MLflow's out-of-the-box local store (a small `mlflow.db`
  database + an `./mlruns` folder), no server needed. The engine sets **no** tracking location itself,
  so pointing one environment variable (`MLFLOW_TRACKING_URI`) at a database or a Databricks-managed
  server later "lights it up" with **no code change** — exactly what the interim Postgres phase and the
  Databricks phases need.
- **Surfaced additively.** The API gained a request toggle (`mlflow.enabled`) and an optional
  `result.mlflow` block (the run id + a load URI per saved model), locked contract bumped `1.8 → 1.9`
  (additive — `null` when logging was off, so an old run is unchanged). Engine + API + tests; the new
  `mlflow` dependency is pinned in requirements. Verified live on `policy_lapse.csv` (a run logged with
  params, metrics, 11 artifacts, and 3 loadable models across all three flavors; an off-run wrote
  nothing extra). Databricks packaging (Phase B) and Model Serving (Phase C) are **not** built yet.

## Postgres input source — read a run's data from a database (✅ Done, 2026-07-08)
**In one line:** A run can now optionally draw its data from a SQL database (e.g. a Postgres
table) instead of an uploaded file — by exporting the table/query to a snapshot file first, so
the whole pipeline runs exactly as before.
- **Why:** the next step of the Databricks-integration plan (`docs/databricks_integration.md` §6.5,
  Interim 2b) — a database-backed input, delivered locally now, that carries forward to Databricks
  unchanged. It follows Phase A (MLflow logging) and Interim 2a (MLflow's history in Postgres).
- **What it does:** a new `input_source` setting picks where the data comes from. The default
  `file` reads the uploaded file as always. `postgres` runs a chosen **table** (→ `SELECT * FROM
  <table>`) or a **raw SQL query** once, and writes the result to the run's input file (a Parquet
  or CSV) in the data folder — after which the ordinary file pipeline loads it and everything
  downstream is **completely unchanged**.
- **"Materialize to a file" on purpose (Option B).** Rather than teaching the engine to read a
  database (which would bend the "all reads go through one file gateway" rule and complicate the
  no-leakage discipline), the query result is *snapshotted to a file* first. That keeps the storage
  rule and the load→split→learn-from-train-only rule **literally intact**, and the snapshot is a
  durable, auditable record of exactly the rows the run saw.
- **Credentials are never in the request/config.** The database connection is referenced by the
  **name** of an environment variable (in `backend/.env`, machine-local, gitignored) that holds the
  connection string — never a password written into a run's configuration. A bad setting (unknown
  source type, both/neither of table/query, a missing connection name, an unsafe table name, or a
  non-Parquet/CSV destination) is rejected the moment the config is built.
- **OFF by default & safe to fail.** With no `input_source` (or `type: file`) a run is byte-for-byte
  identical to before. The database libraries (SQLAlchemy + the Postgres driver) are imported
  **only** when a database source is actually used. A source that can't be read (unset connection
  name, unreachable DB, failed query, empty result) fails with a clear message, not a crash.
- **Verified:** loading `policy_lapse.csv` into a local Postgres table and running with
  `source = postgres` reproduces the direct-CSV run **bit-for-bit** when the query preserves row
  order (`ORDER BY`); the snapshot holds the identical set of rows either way. (A SQL table has no
  inherent row order, so a plain `SELECT *` can shuffle the rows and slightly change the seeded
  train/test split — documented; add an `ORDER BY` for an exact reproduction.) Engine + API; new
  `classifyos/io/sql_source.py`; new tests; `SQLAlchemy` pinned. Dashboard UI to pick a
  table/query is a follow-up. Databricks packaging (Phase B) and Model Serving (Phase C) are **not**
  built yet.

## MLflow — meaningful default run name (✅ Done, 2026-07-08)
**In one line:** When a run is logged to MLflow without a name set, it's now recorded as
"<target> · <date time>" (e.g. `will_lapse · 2026-07-08 14:30`) instead of MLflow's random
whimsical name ("capable-fox-123"), so the dashboard's Runs list reads meaningfully.
- **Why:** the engine forwarded the config's `mlflow.run_name`, which is empty by default, so
  MLflow auto-generated a cute-but-random name for every run — unhelpful when scanning the run
  history. Now, only when no name was supplied, the engine builds a sensible default from the
  target column plus when the run happened.
- **Reuses the run's own timestamp.** It formats the timestamp the run profile already computed
  (`run_profile.json`, written just before logging) rather than reading the clock again — one
  source of truth for "when this run happened."
- **An explicit name still wins.** If a caller sets `mlflow.run_name`, that is used unchanged; the
  default only fills the gap. Display-only: the name sets MLflow's `mlflow.runName` tag (which the
  Runs list reads) and never touches the id-based artifact folder names or the Postgres→file
  mapping. Pure standard-library date formatting — no new dependency, no schema/version change.
  +4 engine tests (**406 backend pytest green**).

## Databricks I/O — volume storage adapter + wheel packaging (Phase B, Steps 1 & 2) (✅ Done, 2026-07-14)
**In one line:** Added a storage adapter that points the engine at Databricks Unity Catalog
"volumes" (cloud folders) instead of local disk, and the build recipe to package the engine as an
installable `.whl` — the two groundwork pieces for running ClassifyOS on a Databricks cluster, both
built and tested entirely locally with no cluster needed.
- **Why:** the next step of the Databricks plan (`docs/databricks_integration.md` §6.6, Steps 1 & 2).
  To run the engine on a cluster you need (a) it to read/write the cluster's storage, and (b) it
  wrapped as a library the cluster can install. Both were designed to be verifiable on this machine
  first, so nothing here is speculative.
- **The storage adapter (`DatabricksVolumeStorage`).** A Unity Catalog volume is just a cloud folder
  exposed at an ordinary-looking path (`/Volumes/main/classifyos/data/input`) that plain Python can
  read and write like any local folder. So the new adapter is a **thin wrapper** over the existing
  local-folder one, with its input/output roots pointed at those volume paths (taken from env vars).
  Crucially, **no engine code changed** — every part of the pipeline already reads and writes through
  the one "file gateway" (the StorageAdapter rule), so it neither knows nor cares whether a path is
  `C:/Projects/...` or `/Volumes/main/...`.
- **Opt-in, zero change for local runs.** The engine picks the Databricks adapter only when you set
  `CLASSIFYOS_STORAGE_BACKEND=databricks` (or just point `DBRICKS_INPUT_VOLUME` at a volume);
  otherwise it uses the local-folder adapter exactly as before. A local run with none of these set is
  **byte-for-byte identical** to today. The three new env vars are documented in `.env.example`.
- **The wheel recipe (`pyproject.toml`).** A new build-metadata file so the engine can be packaged as
  a standard installable wheel (`classifyos-1.0.0-py3-none-any.whl`) and `pip install`ed on a cluster.
  It packages **only the ML engine**, deliberately leaving out the web/API layer so the engine stays
  web-free, and its dependency list is kept **identical** to the engine section of the requirements
  file. Build outputs are git-ignored (not committed).
- **Caught two mistakes in the reference guide.** The project's hallucination-check rule paid off:
  the guide named a build backend that doesn't actually exist (fixed to the real one), and its
  dependency list was missing two libraries the engine genuinely uses (added back) — both verified
  against the installed tools before finalising.
- **Verified.** +7 new tests for the adapter-selection logic (which adapter you get for each
  combination of env vars, and that the resolved folders are correct) — **424 backend pytest green**;
  the wheel builds cleanly; and a real end-to-end run (with the "volumes" pointed at local folders)
  trained two models and wrote all 12 output files to the output volume, identical to a normal local
  run. **Still deferred (need a real cluster):** the Delta-table input source, the MLflow
  managed-server wiring, the cluster smoke-test notebook, and the FastAPI→Databricks-Jobs
  orchestration. The API layer and every engine stage are untouched.

## Databricks I/O — Delta table input + managed-MLflow wiring + smoke-test notebook (Phase B, Steps 3–5) (✅ Done, 2026-07-14)
**In one line:** A run can now read its data straight from a Databricks "Delta table" (the cluster's
native table format) instead of a file, results can be recorded in Databricks' built-in MLflow with
no code change, and there's a ready-made cluster notebook that runs the whole thing end-to-end — the
last engine-side pieces before wiring ClassifyOS into Databricks jobs.
- **Why:** the next steps of the Databricks plan (`docs/databricks_integration.md` §6.6, Steps 3–5),
  following the storage adapter + wheel (Steps 1 & 2). These finish the "engine runs cleanly on a
  cluster" story; only the job-orchestration layer (Step 6) then remains.
- **Delta table as an input source (Step 4).** A new `input_source` type, `delta`, sitting right
  beside the existing `file` and `postgres` options and working the **exact same way** as the
  Postgres one: it reads the chosen Unity Catalog table (`catalog.schema.table`) — or a raw SQL
  query — **once**, snapshots the result to a Parquet file in the data folder, and then the ordinary
  file pipeline runs on that snapshot completely unchanged. So the "all reads go through one file
  gateway" rule and the "learn only from the training split" rule stay literally intact, and the
  snapshot is a durable, auditable record of exactly the rows the run saw. An optional row cap
  (`limit`) keeps quick/dev runs small.
- **Cluster-only, and safe to fail off-cluster.** Reading a Delta table needs Spark, which only
  exists on a Databricks cluster. The Spark library is imported **only** when a Delta source is
  actually used, and if it's missing (or there's no live Spark session — i.e. you're not on a
  cluster) the run stops with a **clear message** telling you to use `file` locally — it never
  crashes an ordinary local run. With no `delta` source configured, a run is byte-for-byte identical
  to before.
- **Safety at the config boundary.** The catalog / schema / table names are checked against a
  safe-identifier allowlist the moment the config is built (they're slotted into the table name and
  can't be passed as safe parameters, so this guards against SQL injection — the same guard the
  Postgres table name already uses). A raw query is the analyst's own opt-in SQL on their own
  cluster. The snapshot file must be a `.parquet`/`.csv`, and `limit` must be a positive whole
  number — bad values are rejected up front (a 422), never a crash mid-run.
- **Managed MLflow with zero code (Step 3).** Databricks ships its own MLflow tracking server and
  model registry. Because the logging code only ever **reads** the "where to log" setting from the
  environment (and never sets it itself), simply setting two environment variables on the cluster
  (`MLFLOW_TRACKING_URI=databricks`, `MLFLOW_REGISTRY_URI=databricks-uc`) makes every logged run
  appear in the Databricks Experiments UI — **no code change at all**. This was verified by
  re-reading the logging module, and the two variables are documented in the environment template.
- **A ready-to-run cluster notebook (Step 5).** A new `notebooks/classifyos_smoke_test.py` (a plain
  Databricks notebook) installs the packaged engine, sets the environment variables, reads a small
  Delta table, trains a couple of models, and prints the scoreboard plus the MLflow run link — the
  one-click way to confirm the whole chain works on a real cluster (Delta read → snapshot → train →
  artifacts to the cloud folder → run visible in MLflow). It's written against the engine's real
  config builder (the reference guide's shorthand didn't match it).
- **Verified.** +20 new tests with **Spark mocked entirely** (a fake Spark session is injected — no
  real cluster is ever contacted): the Delta source reads a table/query, applies the row cap,
  snapshots to Parquet/CSV and round-trips through the loader; and every failure mode (no Spark, no
  live session, no table/query, empty result, unsafe names) is covered. Full backend suite green.
  **Hallucination check ✅** — every Spark call (`getActiveSession`, `table`, `sql`, `limit`,
  `toPandas`) confirmed against the official Azure Databricks PySpark reference (Spark 4.1.0 / DBR
  18.2). **Not yet run on a real cluster** (that's the smoke-test notebook's job once cluster access
  is available); the FastAPI layer and every engine stage are untouched. **Still deferred:** wiring
  Delta runs through the web API and the FastAPI→Databricks-Jobs orchestration (Step 6), and Model
  Serving (Phase C).

## Databricks envelope moved into the engine wheel — notebook needs no repo checkout (✅ Done, 2026-07-23)
**In one line:** Moved the code that shapes a run's results into the final dashboard response INTO
the engine's installable package, so the Databricks job notebook can build that response from the
installed library alone — no copy of the web-app source needed on the cluster.
- **The problem it fixes:** the cluster notebook used to import the response-builder from the web
  (`api`) layer, which isn't part of the engine wheel — so it only worked if the whole repo was
  checked out next to the notebook on the cluster. On a real run that failed (`No module named
  'api'`) because the Databricks Git folder was a partial checkout without the `backend/` folder.
- **What moved:** a new `classifyos.envelope` sub-package inside the engine now holds the result
  reshaper, the JSON-safety helper, the artifact lister, and the response models (the "locked
  `/run` schema"), plus a one-call `build_run_envelope(runner, storage)` that returns the whole
  `{status, schema_version, result, error}` response. The web layer re-exports every one of these
  from its old locations, so **nothing in the API or its tests changed** — there is still exactly
  one definition of each (the web layer's `RunResponse` literally *is* the engine's now).
- **The notebook is simpler + self-contained:** Cell 5 calls `classifyos.envelope.build_run_envelope`
  from the wheel; the old "find the repo's `backend/` and add it to the path" bootstrap (and its
  `/Workspace`-prefix hunting) is gone, so the notebook can run from a plain notebook import.
- **The one tradeoff:** the engine wheel now lists **pydantic** as a dependency (it backs the
  response models). It's a data-validation library, not a web framework — the web *server* deps
  (FastAPI/uvicorn) stay out — and it was already installed alongside the engine via MLflow. A plain
  engine/CLI run never imports the envelope, so pydantic is only used when actually building a
  response. Owner-approved deviation (plan_tweak #50).
- **Byte-identical, and needs a wheel rebuild.** The Databricks response is guaranteed identical to
  a local run (both go through the same `RunResponse`). The wheel must be rebuilt + re-uploaded so
  the cluster gets `classifyos.envelope`. Also fixed this session: the notebook's MLflow experiment
  name (now an absolute workspace path Databricks accepts) and a doc correction to the result-path
  matching. 75 API tests + full backend suite green; local runs unchanged.

## Runs history recorded per-user (engine bit) (✅ Done, 2026-07-23)
**In one line:** A small engine addition so the dashboard's Runs tab can show each user only *their*
Databricks runs: every logged run is stamped with who ran it, plus a reloadable copy of its result.
- New `snapshot_envelope(run_id, envelope, user_email)` in the engine's MLflow module is now the ONE
  place that attaches a run's rendered result (for byte-identical reload) and tags it with two labels:
  a "reloadable" marker and the **owner's email**. The web layer's old snapshot helper just calls it.
- The Databricks job stamps each run with the runner's email; the API then filters the Runs list to
  the caller and refuses to open someone else's run (the filtering/auth lives in the API — see
  `api_short_desc.md`; the engine change is just the helper + the shared tag names).
- Report-only and additive: if MLflow logging is off/fails nothing happens, and a local run is
  unchanged. No new dependency, no schema change.

## LLM narration can be handed to the API — engine flag + a side artifact (✅ Done, 2026-07-24)
**In one line:** So narratives can be generated OFF the cluster (on Databricks the cluster can't reach
Azure OpenAI — a 403), the engine can now skip its in-process narrate call and instead leave behind the
context the API needs to narrate later.
- **New flag `CLASSIFYOS_NARRATE_IN_ENGINE` (default `true`).** Unset/true → the engine narrates
  in-process exactly as before, so the **local** backend is byte-identical. The Databricks Job notebook
  sets it `false`: the run still computes SHAP but skips the (unreachable) Azure call.
- **New side artifact `api/narration_context.json`.** Whenever a run requests LLM narratives, the engine
  serializes the whole-run narration context it can't otherwise be reconstructed from the result — the
  analyst dataset/column context + `context_mode`, plus the data-derived per-column schema + a couple of
  sample rows (and the feature-column list for value resolution). It is JSON-sanitized and logged to
  MLflow under `api/` (next to the result snapshot) by `mlflow_logging.log_run`. Everything else the
  narrator needs (class base rates, per-model metrics, global importances, the SHAP rows) is already in
  the result envelope, so it is deliberately not duplicated.
- **`snapshot_envelope` gained an optional `tracking_uri`** so the API's off-cluster re-persist of the
  narrated result can target Databricks-managed MLflow per call (thread-safe; local unchanged).
- Additive + report-only: it is a SIDE artifact (not the locked `/run` envelope), so **no schema change**;
  the in-engine narrator, its prompt, and a non-narrative run are all unchanged. The FastAPI narrate step
  that consumes this lives in `api_short_desc.md`. Needs a wheel rebuild + cluster restart + notebook
  re-import to take effect on Databricks.

---

## How to read this project

- **CLAUDE.md** — the conventions and hard rules (what must never be violated).
- **PROJECT_STATE.md** — the live status: what's done, decisions made, known issues, next steps.
- **plan_tweak.md** — the honest register of where we deviated from the original signed plan and why.
- **backend_short_desc.md** (this file) — the plain-language phase-by-phase summary of the
  ML engine.
- **api_short_desc.md** — the plain-language summary of the API surface (Phase 8 FastAPI layer).
- **frontend_short_desc.md** — the plain-language summary of the React dashboard (Phase 9).
- **docs/api_contract.md** — the **locked** `/api/v1/run` request/response schema.
