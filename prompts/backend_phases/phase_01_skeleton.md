# Phase 1 Generation Prompt — Framework Skeleton (Sections 1–4, 9)

> Archive location: prompts/phase_01_skeleton.md (governance: prompt committed with the code it generated)

---

Read CLAUDE.md and PROJECT_STATE.md first. This session implements Phase 1 of ClassifyOS:
Sections 1, 2, 3, 4, and 9 of the ML engine, with unit tests. Do NOT implement any other
sections (no preprocessing, no feature engineering, no models) — sections are additive and
later sessions build on this one.

## Files to create

1. `backend/classifyos/config.py` — Sections 1–2
2. `backend/classifyos/io/inspect.py` — Section 3
3. `backend/classifyos/io/loader.py` — Section 4
4. `backend/classifyos/split.py` — Section 9
5. `backend/tests/test_config.py`, `backend/tests/test_loader.py`,
   `backend/tests/test_inspect.py`, `backend/tests/test_split.py`

## Section 1–2 — config.py

- `DEFAULT_CONFIG: dict` — the master config with these keys and defaults:
  `input_file` (str, required), `target` (str, required), `feature_cols` (list[str], required),
  `problem_type` ("binary" | "multiclass" | "multilabel", default "binary"),
  `test_size` (float, 0.2), `stratify` (bool, True), `time_split_col` (str | None, None),
  `algorithms` (list[str], default ["LogisticRegression","RandomForest","XGBoost"]),
  `class_balance` ("smote" | "undersample" | "class_weight" | "none", default "smote"),
  `missing_strategy` ("median" | "mean" | "mode" | "ffill" | "drop", default "median"),
  `encoding_method` ("onehot" | "label" | "ordinal" | "target", default "onehot"),
  `scaling_method` ("standard" | "minmax" | "robust" | "none", default "standard"),
  `threshold` (float, 0.5), `calibrate_probs` (bool, True),
  `interaction_features` (dict — keys: enabled=True, interaction_pairs={},
  default_interactions=["multiply"], drop_original_if_interacted=False,
  max_auto_pairs=10, fill_method="zero"), `random_state` (int, 42).
- `build_config(input_file: str, target: str, feature_cols: list[str], **overrides) -> dict`
  — deep-copies DEFAULT_CONFIG, applies arguments and overrides, validates:
  required fields non-empty, feature_cols has ≥1 column, target not in feature_cols,
  test_size in (0, 0.5], problem_type / class_balance / encoding / scaling values are
  from the allowed sets. Raises ValueError with a clear message naming the bad field.
  Returns a new dict — never mutates DEFAULT_CONFIG. Add a [RISK] comment about
  config mutation (this is the root of the _run_config isolation pattern used later).

## Section 3 — io/inspect.py

- `inspect_file(path: str, storage: StorageAdapter, target: str | None = None) -> dict`
  — loads the file via the StorageAdapter (no direct open()/pd.read_csv on raw paths),
  returns: `columns` (list), `dtypes` (dict col→str), `numeric_cols`, `categorical_cols`,
  `binary_cols` (numeric or object cols with exactly 2 unique non-null values),
  `datetime_cols` (parseable date columns by name pattern or dtype), `n_rows`,
  `n_missing` (dict col→int), `sample` (first 5 rows as list of dicts, NaN→None),
  and if `target` given: `class_distribution` (dict value→count) and
  `suggested_problem_type` ("binary" if 2 classes, "multiclass" if 3+).
  This feeds the UI dropdowns later — keys are part of the future API contract,
  so keep names exactly as above.

## Section 4 — io/loader.py

- `data_loader(config: dict, storage: StorageAdapter) -> pd.DataFrame`
  — loads CSV / Excel (.xlsx) / Parquet based on file suffix, via StorageAdapter.
  Validates: file exists (FileNotFoundError), target column present and all
  feature_cols present (ValueError listing the missing columns), target has ≥2
  classes (ValueError), target parsed as categorical/str (not float).
  If `time_split_col` is set, parse it as datetime and raise ValueError if unparseable.
  [RISK] comment: target with NaN rows — drop them and log a warning with the count.

## Section 9 — split.py

- `train_test_split_cls(df: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, pd.DataFrame]`
  — returns (train_df, test_df).
  Default: stratified random split on target preserving class proportions
  (sklearn train_test_split, stratify=y, random_state from config).
  If `config["time_split_col"]` is set: sort by that column ascending and take the
  last `test_size` fraction as test — NO shuffling. [RISK] comment: temporal leakage —
  time-based split is the correct default for time-ordered insurance data.
  Edge case: if any class has fewer than 2 members, fall back to non-stratified split
  and log a warning (do not crash).

## Tests (pytest)

Use the real sample CSVs from DATA_DIR (read DATA_DIR from backend/.env via the same
mechanism the StorageAdapter uses; sample files: policy_lapse.csv, fraud_claims.csv,
risk_tier.csv). Tests must cover:

- build_config: happy path; empty target → ValueError; target inside feature_cols →
  ValueError; bad problem_type → ValueError; DEFAULT_CONFIG not mutated after a build.
- inspect_file: on policy_lapse.csv — occupation in categorical_cols, has_agent in
  binary_cols, policy_start_date detected as datetime, class_distribution for
  will_lapse has 2 keys; on risk_tier.csv — suggested_problem_type == "multiclass".
- data_loader: missing file → FileNotFoundError; nonexistent feature column →
  ValueError naming it; loads all 3 CSVs successfully.
- train_test_split_cls: on risk_tier.csv — class proportions in train vs full dataset
  within ±2 percentage points per class; on policy_lapse.csv with
  time_split_col="policy_start_date" — max(train date) <= min(test date);
  on fraud_claims.csv — stratified split keeps ≥1 fraud row in test.

## Process requirements

- Every public function: type hints + docstring. Embed [RISK] comments where noted.
- All file I/O through StorageAdapter — never a raw path open in pipeline code.
- Run the full pytest suite; fix failures before finishing. Target: all tests pass.
- Verify every sklearn/pandas call against the installed versions (hallucination check)
  — if unsure of an API, check it in the venv rather than guessing.
- Save this prompt file to prompts/phase_01_skeleton.md.
- Update PROJECT_STATE.md: phase tracker (Ph.0 ✅, Ph.1 ✅ or 🔄 with notes),
  completed-this-session list, any new decisions or issues, next steps (Phase 2).
- Commit everything as: "Phase 1: framework skeleton — sections 1-4, 9 + tests"

---

## Outcome (filled in after generation — 2026-06-12)

Implemented all five modules with type hints, docstrings, and the required [RISK]
comments (config mutation in `build_config`; target-NaN drop in `data_loader`;
temporal leakage in `train_test_split_cls`). All I/O routes through `StorageAdapter`.
Added `openpyxl` + `pyarrow` to requirements (loader supports .xlsx/.parquet).
Sample CSVs generated into `DATA_DIR` (`backend/data/samples`) via
`scripts/generate_sample_data.py`. Test suite: **22 passed** against the real samples.
Hallucination check: verified against pandas 2.3.3 / scikit-learn 1.9.0 in the venv.
