/* ════════════════════════════════════════════════════════════════════════
   searchSpaces — the per-model Optuna search spaces, mirrored for the UI.

   This is a faithful, READ-ONLY mirror of the engine's `SEARCH_SPACES`
   (backend/classifyos/tuning.py `_space_*` functions). It exists only so the
   Configuration page can render the default bounds/choices a user may override
   via `tuning.search_space_overrides`. It introduces NO new tunable knob — the
   engine's `_space_*` functions remain the single source of which parameters
   exist; if a parameter is not listed here it cannot be overridden from the UI.

   Override wire-shape (what `search_space_overrides[model][param]` becomes):
     • numeric  → { low?, high? }  — merged over the engine default (engine `_b`)
     • categorical → an array of choices                    (engine `_ch`)
   A blank numeric field / an unchanged categorical set means "use the engine
   default" and is omitted from the payload entirely.
   ════════════════════════════════════════════════════════════════════════ */

/** One tunable parameter in a model's search space. */
export type SpaceParam =
  | {
      name: string
      kind: "float" | "int"
      low: number
      high: number
      /** searched on a log scale (engine passes log=True) — low must be > 0. */
      log?: boolean
      note?: string
    }
  | {
      name: string
      kind: "categorical"
      choices: (string | number)[]
      note?: string
    }

/**
 * Canonical model name → ordered parameter list. Keyed to the MODEL_REGISTRY /
 * engine `SEARCH_SPACES` names. Bounds/choices are copied verbatim from
 * tuning.py; keep them in sync if the engine spaces change.
 */
export const SEARCH_SPACES: Record<string, SpaceParam[]> = {
  XGBoost: [
    { name: "learning_rate", kind: "float", low: 0.01, high: 0.3, log: true },
    { name: "max_depth", kind: "int", low: 3, high: 10 },
    { name: "n_estimators", kind: "int", low: 100, high: 800 },
    { name: "subsample", kind: "float", low: 0.6, high: 1.0 },
    { name: "colsample_bytree", kind: "float", low: 0.6, high: 1.0 },
    { name: "min_child_weight", kind: "int", low: 1, high: 10 },
    { name: "reg_alpha", kind: "float", low: 1e-3, high: 10.0, log: true },
    { name: "reg_lambda", kind: "float", low: 1e-3, high: 10.0, log: true },
    { name: "gamma", kind: "float", low: 0.0, high: 5.0 },
  ],
  LightGBM: [
    { name: "num_leaves", kind: "int", low: 15, high: 255 },
    { name: "max_depth", kind: "int", low: 3, high: 12 },
    { name: "learning_rate", kind: "float", low: 0.01, high: 0.3, log: true },
    { name: "n_estimators", kind: "int", low: 100, high: 800 },
    { name: "feature_fraction", kind: "float", low: 0.6, high: 1.0 },
    { name: "bagging_fraction", kind: "float", low: 0.6, high: 1.0 },
    { name: "bagging_freq", kind: "int", low: 1, high: 7 },
    { name: "min_child_samples", kind: "int", low: 5, high: 100 },
    { name: "reg_alpha", kind: "float", low: 1e-3, high: 10.0, log: true },
    { name: "reg_lambda", kind: "float", low: 1e-3, high: 10.0, log: true },
  ],
  RandomForest: [
    { name: "n_estimators", kind: "int", low: 100, high: 600 },
    { name: "max_depth", kind: "int", low: 3, high: 30 },
    { name: "max_features", kind: "categorical", choices: ["sqrt", "log2", 0.5, 0.75, 1.0] },
    { name: "min_samples_leaf", kind: "int", low: 1, high: 10 },
    { name: "min_samples_split", kind: "int", low: 2, high: 20 },
  ],
  LogisticRegression: [
    { name: "C", kind: "float", low: 1e-3, high: 1e2, log: true },
  ],
  SVM: [
    { name: "C", kind: "float", low: 1e-2, high: 1e2, log: true },
    { name: "kernel", kind: "categorical", choices: ["rbf", "linear"] },
    { name: "gamma", kind: "float", low: 1e-4, high: 1e0, log: true, note: "RBF kernel only" },
  ],
  NaiveBayes: [
    { name: "var_smoothing", kind: "float", low: 1e-12, high: 1e-6, log: true },
  ],
}

/** Numeric per-param override (sparse — only the bound(s) the user changed). */
export type NumericOverride = { low?: number; high?: number }
/** One param override: numeric bounds OR a categorical choice subset. */
export type ParamOverride = NumericOverride | (string | number)[]
/** model → param → override. Rides along as `tuning.search_space_overrides`. */
export type SearchSpaceOverrides = Record<string, Record<string, ParamOverride>>
