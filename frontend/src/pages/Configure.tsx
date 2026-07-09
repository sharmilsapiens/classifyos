/* Configuration — step 2 of Upload → Configure → Run.

   A form that binds every field the locked RunConfig accepts. The values live in
   the global store's `form`; each control reads from it and writes back via
   updateForm(). The "Run pipeline" button validates the 3 required fields
   client-side (a friendlier first pass than waiting for the server's 422), then
   triggers runPipeline() and navigates to Overview to watch it run (9c merged the
   old Pipeline page into Overview — it shows the in-progress state then results).

   The option lists below MUST match the engine's allowed values
   (backend/classifyos/config.py) so a run never 422s on a bad enum. */

import type { ReactNode } from "react"
import { useNavigate } from "react-router-dom"
import { Link } from "react-router-dom"
import { Play } from "lucide-react"

import type { ColumnProfile, Histogram } from "@/api/types"
import { useApp } from "@/store/AppStore"
import { fmtInt, fmtNum } from "@/lib/format"
import { ColumnFlags } from "@/lib/columnFlags"
import { cn } from "@/lib/utils"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Button, buttonVariants } from "@/components/ui/button"
import { EmptyState, PageHeader } from "@/components/common/States"
import FeatureBuilderPanel from "@/components/config/FeatureBuilderPanel"
import TuningOverridesPanel from "@/components/config/TuningOverridesPanel"
import MissingByColumnPanel from "@/components/config/MissingByColumnPanel"
import ExplainContextPanel from "@/components/config/ExplainContextPanel"

// Allowed values — mirror config.py's tuples exactly.
const PROBLEM_TYPES = ["binary", "multiclass", "multilabel"] as const
const CLASS_BALANCE = ["smote", "undersample", "class_weight", "none"] as const
// Missing-value strategy is split by feature type — numeric columns can use the model-based
// imputers (knn/iterative) and the numeric statistics; non-numeric columns cannot.
const MISSING_NUMERIC = [
  "median", "mean", "mode", "ffill", "bfill", "knn", "iterative", "drop",
] as const
const MISSING_CATEGORICAL = ["mode", "ffill", "bfill", "drop"] as const
const ENCODING = ["onehot", "label", "ordinal", "target"] as const
const SCALING = ["standard", "minmax", "robust", "none"] as const
const OUTLIER = ["iqr", "zscore", "none"] as const
// Decision-threshold policy (binary only). "tuned" lets the engine pick the cut on train-only
// CV folds; "fixed" uses the analyst value; "default" is sklearn's 0.5 argmax.
const THRESHOLD_MODES = [
  { value: "tuned", label: "Auto-tune (best cut)" },
  { value: "fixed", label: "Fixed value" },
  { value: "default", label: "Default (0.5)" },
] as const
// Metrics a tuned threshold may maximise — mirror config.py THRESHOLD_METRICS exactly.
const THRESHOLD_METRICS = [
  "f1", "f1_weighted", "f1_macro", "balanced_accuracy", "accuracy", "precision", "recall",
] as const
// const FILL = ["zero", "median", "nan"] as const  // unused while interactions card is hidden
const TUNING_METRICS = [
  "f1_weighted", "f1_macro", "accuracy", "precision_weighted", "recall_weighted",
  "roc_auc", "pr_auc", "mcc", "log_loss",
] as const
// Canonical algorithm names (the MODEL_REGISTRY keys).
const ALGORITHMS = [
  "LogisticRegression", "RandomForest", "XGBoost", "LightGBM", "SVM", "NaiveBayes",
] as const

export default function Configure() {
  const { inspect, serverPath, form, updateForm, runPipeline, formErrors } = useApp()
  const navigate = useNavigate()

  // Can't configure without an uploaded dataset.
  if (!inspect || !serverPath) {
    return (
      <div>
        <PageHeader title="Configuration" subtitle="Set up a run." />
        <EmptyState
          title="Upload a dataset first"
          description="Configuration needs a dataset's columns to pick a target and features."
          action={<Link to="/upload" className={buttonVariants({ size: "sm" })}>Upload data</Link>}
        />
      </div>
    )
  }

  const errors = formErrors()
  // Feature candidates = every column except the target (datetimes are offered but
  // the engine drops id/datetime columns itself).
  const featureCandidates = inspect.columns.filter((c) => c !== form.target)
  // The upload's Data-Profile blocks (may be absent on an older upload) let each
  // candidate show its distribution + degenerate-column flags right in the picker.
  const profileByName = new Map<string, ColumnProfile>(
    (inspect.column_profiles ?? []).map((p) => [p.name, p]),
  )
  // How much of the selected feature columns is actually missing, split the same way
  // the two selectors are (numeric vs everything else) — so the imputation choice is
  // made knowing whether (and how much) there is anything to impute. When a category
  // has selected columns but none with gaps, its selector is locked (nothing to impute).
  const numericMissing = missingState(form.feature_cols, profileByName, true)
  const categoricalMissing = missingState(form.feature_cols, profileByName, false)

  function toggleFeature(col: string) {
    const next = form.feature_cols.includes(col)
      ? form.feature_cols.filter((c) => c !== col)
      : [...form.feature_cols, col]
    updateForm({ feature_cols: next })
  }

  function toggleAlgo(name: string) {
    const next = form.algorithms.includes(name)
      ? form.algorithms.filter((a) => a !== name)
      : [...form.algorithms, name]
    updateForm({ algorithms: next })
  }

  function onRun() {
    // Navigate to Overview first so it shows the in-progress state immediately,
    // then kick off the (synchronous, possibly slow) run.
    navigate("/")
    void runPipeline()
  }

  return (
    <div>
      <PageHeader
        title="Configuration"
        subtitle={`Dataset: ${serverPath}`}
        actions={
          <Button onClick={onRun} disabled={errors.length > 0 || form.algorithms.length === 0}>
            <Play className="h-4 w-4" />
            Run pipeline
          </Button>
        }
      />

      {/* Required-field mirror (so the user sees problems before the server 422s). */}
      {errors.length > 0 && (
        <div className="mb-5 rounded-md border border-amber/40 bg-amber/10 p-3 text-sm text-foreground">
          <p className="mb-1 font-semibold text-amber">Finish these before running:</p>
          <ul className="list-disc space-y-0.5 pl-5 text-xs">
            {errors.map((e) => <li key={e}>{e}</li>)}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Target + features */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Target &amp; features</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-5 md:grid-cols-[260px_1fr]">
            <div className="space-y-1.5">
              <Label htmlFor="target">Target column</Label>
              <Select
                id="target"
                value={form.target}
                onChange={(e) =>
                  updateForm({
                    target: e.target.value,
                    feature_cols: form.feature_cols.filter((c) => c !== e.target.value),
                  })
                }
              >
                <option value="">— choose —</option>
                {inspect.columns.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
              {inspect.suggested_problem_type && (
                <p className="text-xs text-muted-foreground">
                  Suggested problem type: {inspect.suggested_problem_type}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label>Feature columns ({form.feature_cols.length})</Label>
                <div className="flex gap-2 text-xs">
                  <button
                    type="button"
                    className="text-primary hover:underline"
                    onClick={() => updateForm({ feature_cols: featureCandidates })}
                  >
                    Select all
                  </button>
                  <button
                    type="button"
                    className="text-muted-foreground hover:underline"
                    onClick={() => updateForm({ feature_cols: [] })}
                  >
                    Clear
                  </button>
                </div>
              </div>
              <div className="grid max-h-72 grid-cols-1 gap-1 overflow-y-auto rounded-md border p-2 sm:grid-cols-2">
                {featureCandidates.map((col) => (
                  <FeatureRow
                    key={col}
                    col={col}
                    checked={form.feature_cols.includes(col)}
                    onToggle={() => toggleFeature(col)}
                    profile={profileByName.get(col)}
                    nRows={inspect.n_rows}
                  />
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                Numeric columns show a mini distribution and avg · IQR · variance;
                categorical columns list their values; identifier/single-value columns
                are flagged (usually excluded).
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Problem framing */}
        <Card>
          <CardHeader><CardTitle>Problem framing</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 gap-4">
            <Field label="Problem type">
              <Select value={form.problem_type}
                onChange={(e) => updateForm({ problem_type: e.target.value as typeof form.problem_type })}>
                {PROBLEM_TYPES.map((p) => <option key={p} value={p}>{p}</option>)}
              </Select>
            </Field>
            <Field label="Test size">
              <Input type="number" min={0.05} max={0.5} step={0.05} value={form.test_size}
                onChange={(e) => updateForm({ test_size: Number(e.target.value) })} />
            </Field>
            <Field label="Decision threshold" hint={thresholdModeHint(form.threshold_mode, form.problem_type)}>
              <Select value={form.threshold_mode}
                onChange={(e) => updateForm({ threshold_mode: e.target.value })}>
                {THRESHOLD_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </Select>
            </Field>
            {form.threshold_mode === "tuned" ? (
              <Field label="Threshold metric" hint="Maximised on train-only CV folds to choose the cut.">
                <Select value={form.threshold_metric}
                  onChange={(e) => updateForm({ threshold_metric: e.target.value })}>
                  {THRESHOLD_METRICS.map((m) => <option key={m} value={m}>{m}</option>)}
                </Select>
              </Field>
            ) : form.threshold_mode === "fixed" ? (
              <Field label="Threshold value" hint="Positive-class cutoff (0–1).">
                <Input type="number" min={0.01} max={0.99} step={0.05} value={form.threshold}
                  onChange={(e) => updateForm({ threshold: Number(e.target.value) })} />
              </Field>
            ) : (
              <Field label="Threshold value" hint="Fixed 0.5 cutoff (change the mode to tune or set it).">
                <Input type="number" value={0.5} disabled />
              </Field>
            )}
            <Field label="Random state">
              <Input type="number" value={form.random_state}
                onChange={(e) => updateForm({ random_state: Number(e.target.value) })} />
            </Field>
            <div className="col-span-2 flex gap-6 pt-1">
              <Switch id="stratify" label="Stratified split" checked={form.stratify}
                onChange={(e) => updateForm({ stratify: e.target.checked })} />
              <Switch id="calibrate" label="Calibrate probabilities" checked={form.calibrate_probs}
                onChange={(e) => updateForm({ calibrate_probs: e.target.checked })} />
            </div>
          </CardContent>
        </Card>

        {/* Algorithms */}
        <Card>
          <CardHeader><CardTitle>Algorithms ({form.algorithms.length})</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 gap-x-4 gap-y-2">
            {ALGORITHMS.map((name) => (
              <label key={name} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[color:var(--primary)]"
                  checked={form.algorithms.includes(name)}
                  onChange={() => toggleAlgo(name)}
                />
                <span className="truncate">{name}</span>
              </label>
            ))}
          </CardContent>
        </Card>

        {/* Preprocessing */}
        <Card>
          <CardHeader><CardTitle>Preprocessing</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 gap-4">
            <Field label="Class balance">
              <Select value={form.class_balance}
                onChange={(e) => updateForm({ class_balance: e.target.value as typeof form.class_balance })}>
                {CLASS_BALANCE.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            </Field>
            <Field label="Missing values · numeric"
              hint={<>{numericMissing.summary}{!numericMissing.disableSelector && missingNumericHint(form.missing_strategy_numeric)}</>}>
              <Select aria-label="Missing values · numeric"
                value={form.missing_strategy_numeric}
                disabled={numericMissing.disableSelector}
                onChange={(e) => updateForm({ missing_strategy_numeric: e.target.value })}>
                {MISSING_NUMERIC.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            </Field>
            <Field label="Missing values · categorical"
              hint={<>{categoricalMissing.summary}{!categoricalMissing.disableSelector && missingCategoricalHint(form.missing_strategy_categorical)}</>}>
              <Select aria-label="Missing values · categorical"
                value={form.missing_strategy_categorical}
                disabled={categoricalMissing.disableSelector}
                onChange={(e) => updateForm({ missing_strategy_categorical: e.target.value })}>
                {MISSING_CATEGORICAL.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            </Field>
            <Field label="Encoding">
              <Select value={form.encoding_method}
                onChange={(e) => updateForm({ encoding_method: e.target.value })}>
                {ENCODING.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            </Field>
            <Field label="Scaling">
              <Select value={form.scaling_method}
                onChange={(e) => updateForm({ scaling_method: e.target.value })}>
                {SCALING.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            </Field>
            <Field label="Outliers">
              <Select value={form.outlier_method}
                onChange={(e) => updateForm({ outlier_method: e.target.value })}>
                {OUTLIER.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            </Field>
            <Field label="High-cardinality threshold"
              hint={highCardinalityHint(form.problem_type)}>
              <Input type="number" min={2} value={form.high_cardinality_threshold}
                onChange={(e) => updateForm({ high_cardinality_threshold: Number(e.target.value) })} />
            </Field>
          </CardContent>
        </Card>

        {/* Per-column imputation overrides */}
        <Card>
          <CardHeader>
            <CardTitle>Missing values · per column</CardTitle>
          </CardHeader>
          <CardContent>
            <MissingByColumnPanel
              featureCols={form.feature_cols}
              profileByName={profileByName}
              numericDefault={form.missing_strategy_numeric}
              categoricalDefault={form.missing_strategy_categorical}
              value={form.missing_strategy_by_column}
              onChange={(next) => updateForm({ missing_strategy_by_column: next })}
            />
          </CardContent>
        </Card>

        {/* Post-training analysis */}
        <Card>
          <CardHeader><CardTitle>Post-training analysis</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 gap-4">
            <Field label="Permutation importance metric"
              hint="The score whose drop-when-shuffled measures each feature's importance (all models, incl. SVM/Naive Bayes).">
              <Select value={form.permutation_metric}
                onChange={(e) => updateForm({ permutation_metric: e.target.value })}>
                {TUNING_METRICS.map((m) => <option key={m} value={m}>{m}</option>)}
              </Select>
            </Field>
            <Field label="Per-row explainability (SHAP)"
              hint="Opt-in: compute per-row SHAP contributions so the Explainability page can show WHY each prediction was made (all six models). Adds run time — the SVM/Naive Bayes path is the slow one.">
              <Switch id="explain_enabled" label="Explain predictions" checked={form.explain_enabled}
                onChange={(e) => updateForm({ explain_enabled: e.target.checked })} />
            </Field>
            {form.explain_enabled && (
              <Field label="LLM reason-code narrative (Azure OpenAI)"
                hint="Opt-in: also generate a plain-language paragraph per explained row describing how the top features drove the prediction. Requires SHAP (above) and the server's AZURE_OPEN_AI_* credentials; one LLM call per explained row, so it adds latency. Degrades to SHAP-only if unconfigured.">
                <Switch id="explain_llm" label="Narrate predictions with an LLM" checked={form.explain_llm}
                  onChange={(e) => updateForm({ explain_llm: e.target.checked })} />
              </Field>
            )}
          </CardContent>
        </Card>

        {/* LLM narrative context — only when the narrative toggle is on. Placed right after
            Post-training analysis (the card whose "Narrate predictions with an LLM" toggle reveals
            it) so it reads as that toggle's settings, not detached below Run tracking. Shapes the
            prompt, not the ML. */}
        {form.explain_enabled && form.explain_llm && (
          <Card>
            <CardHeader>
              <CardTitle>LLM narrative context</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <Field label="Context mode"
                hint="Given: use only the notes you write below. Derived: let the model infer meaning from the data (column headers, a sample row, basic stats, class base rates). Both: combine them.">
                <Select
                  value={form.explain_context_mode}
                  onChange={(e) =>
                    updateForm({
                      explain_context_mode: e.target.value as "given" | "derived" | "both",
                    })
                  }
                >
                  <option value="both">Both (given + derived)</option>
                  <option value="given">Given context only</option>
                  <option value="derived">Derived from data only</option>
                </Select>
              </Field>

              {form.explain_context_mode !== "derived" && (
                <>
                  <Field label="Dataset context"
                    hint="Free-text: what this dataset is, what the target means, any domain notes. Sent to the model to ground the explanations.">
                    <textarea
                      id="explain_dataset_context"
                      className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      placeholder="e.g. Insurance quotes for Arizona commercial policies. Target 'converted' = the quote was bound into a policy (1) or not (0)."
                      value={form.explain_dataset_context}
                      onChange={(e) => updateForm({ explain_dataset_context: e.target.value })}
                    />
                  </Field>
                  <div className="space-y-1.5">
                    <Label>Per-column context</Label>
                    <ExplainContextPanel
                      featureCols={form.feature_cols}
                      value={form.explain_column_context}
                      onChange={(next) => updateForm({ explain_column_context: next })}
                    />
                  </div>
                </>
              )}

              {form.explain_context_mode === "derived" && (
                <p className="text-sm text-muted-foreground">
                  The model will infer context from the data itself (column headers, a sample row,
                  basic stats, and class base rates). No manual notes are sent.
                </p>
              )}
            </CardContent>
          </Card>
        )}

        {/* Run tracking — opt-in MLflow logging. UI default is ON (see DEFAULT_FORM_STATE),
            deliberately differing from the engine/API default of OFF. */}
        <Card>
          <CardHeader><CardTitle>Run tracking</CardTitle></CardHeader>
          <CardContent>
            <Field label="Log this run to MLflow (run history + saved models)"
              hint="Records this run to the server's MLflow store so it appears in Runs and its models are saved for reload. Silently skipped if the store isn't configured or reachable — no error, the run still completes.">
              <Switch id="mlflow_enabled" label="Log run to MLflow" checked={form.mlflow_enabled}
                onChange={(e) => updateForm({ mlflow_enabled: e.target.checked })} />
            </Field>
          </CardContent>
        </Card>

        {/* Feature engineering — TEMPORARILY HIDDEN (Section 7 derived features unwired
            from the backend). Restore this card to re-expose the controls. The engine
            force-disables feature_engineering regardless, so leaving the form defaults
            (fe_enabled: true, etc.) is harmless — the payload still carries them and the
            runner overrides. */}
        {/* <Card>
          <CardHeader><CardTitle>Feature engineering</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Switch id="fe_enabled" label="Enabled" checked={form.fe_enabled}
              onChange={(e) => updateForm({ fe_enabled: e.target.checked })} />
            <div className="flex flex-wrap gap-6">
              <Switch id="fe_ratios" label="Ratios" checked={form.fe_ratios}
                onChange={(e) => updateForm({ fe_ratios: e.target.checked })} />
              <Switch id="fe_binning" label="Binning" checked={form.fe_binning}
                onChange={(e) => updateForm({ fe_binning: e.target.checked })} />
              <Switch id="fe_poly" label="Polynomial" checked={form.fe_polynomial}
                onChange={(e) => updateForm({ fe_polynomial: e.target.checked })} />
            </div>
            <Field label="Max polynomial features">
              <Input type="number" min={1} value={form.fe_max_poly_features}
                onChange={(e) => updateForm({ fe_max_poly_features: Number(e.target.value) })} />
            </Field>
          </CardContent>
        </Card> */}

        {/* Interactions — TEMPORARILY HIDDEN (interaction features unwired from the
            backend). Restore this card to re-expose the controls. */}
        {/* <Card>
          <CardHeader><CardTitle>Interaction features</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-6">
              <Switch id="ix_enabled" label="Enabled" checked={form.ix_enabled}
                onChange={(e) => updateForm({ ix_enabled: e.target.checked })} />
              <Switch id="ix_drop" label="Drop interacted originals" checked={form.ix_drop_original}
                onChange={(e) => updateForm({ ix_drop_original: e.target.checked })} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Max auto pairs">
                <Input type="number" min={0} value={form.ix_max_auto_pairs}
                  onChange={(e) => updateForm({ ix_max_auto_pairs: Number(e.target.value) })} />
              </Field>
              <Field label="Fill method">
                <Select value={form.ix_fill_method}
                  onChange={(e) => updateForm({ ix_fill_method: e.target.value })}>
                  {FILL.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              </Field>
            </div>
          </CardContent>
        </Card> */}

        {/* User-defined features */}
        <FeatureBuilderPanel
          inspect={inspect}
          userFeatures={form.user_features}
          onChange={(next) => updateForm({ user_features: next })}
        />

        {/* Tuning */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Hyperparameter tuning (Optuna)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Switch id="tune_enabled" label="Enable tuning (off by default — can be slow)"
              checked={form.tune_enabled} onChange={(e) => updateForm({ tune_enabled: e.target.checked })} />
            {form.tune_enabled && (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                  <Field label="Metric">
                    <Select value={form.tune_metric} onChange={(e) => updateForm({ tune_metric: e.target.value })}>
                      {TUNING_METRICS.map((m) => <option key={m} value={m}>{m}</option>)}
                    </Select>
                  </Field>
                  <Field label="CV folds">
                    <Input type="number" min={2} value={form.tune_cv_folds}
                      onChange={(e) => updateForm({ tune_cv_folds: Number(e.target.value) })} />
                  </Field>
                  <Field label="Trials / model">
                    <Input type="number" min={1} value={form.tune_n_trials}
                      onChange={(e) => updateForm({ tune_n_trials: Number(e.target.value) })} />
                  </Field>
                  <Field label="Timeout (s/model)">
                    <Input type="number" min={1} disabled={form.tune_timeout_seconds === null}
                      placeholder="no timeout"
                      value={form.tune_timeout_seconds ?? ""}
                      onChange={(e) =>
                        updateForm({ tune_timeout_seconds: e.target.value === "" ? null : Number(e.target.value) })
                      } />
                  </Field>
                </div>
                <Switch id="tune_no_timeout" label="No timeout — run all trials (default; n_trials is the only bound)"
                  checked={form.tune_timeout_seconds === null}
                  onChange={(e) => updateForm({ tune_timeout_seconds: e.target.checked ? null : 600 })} />
                <TuningOverridesPanel
                  overrides={form.tune_search_space_overrides}
                  onChange={(next) => updateForm({ tune_search_space_overrides: next })}
                />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 flex justify-end">
        <Button onClick={onRun} disabled={errors.length > 0 || form.algorithms.length === 0} size="lg">
          <Play className="h-4 w-4" />
          Run pipeline
        </Button>
      </div>
    </div>
  )
}

/** A label + control stacked vertically (used throughout the form). An optional
 *  `hint` renders as muted helper text below the control. */
function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: ReactNode
  children: ReactNode
}) {
  return (
    <div className={cn("space-y-1.5")}>
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

/** One selectable feature: a checkbox + column name, its degenerate-column flags
 *  (identifier / single-value, annotated with the value / unique-count), and — for
 *  numeric columns — a smooth distribution curve with avg · IQR · variance, or — for
 *  categorical columns — the available category values. Falls back to a plain checkbox
 *  row when the upload carried no profile block. */
function FeatureRow({
  col,
  checked,
  onToggle,
  profile,
  nRows,
}: {
  col: string
  checked: boolean
  onToggle: () => void
  profile?: ColumnProfile
  nRows: number
}) {
  const stats = profile?.dtype_group === "numeric" ? profile.stats : null
  // IQR = p75 − p25; variance = std². Both derived from the profile stats (the
  // Data Profile surfaces the same avg / spread numbers on its numeric cards).
  const iqr = stats && stats.p75 != null && stats.p25 != null ? stats.p75 - stats.p25 : null
  const variance = stats && stats.std != null ? stats.std * stats.std : null
  const flags = profile?.flags ?? []
  const isIdentifier = flags.includes("identifier")
  // A normal categorical column lists its values; skip for constant/identifier
  // (the flag badge already shows the single value / the unique count there).
  const showCategories =
    profile?.dtype_group === "categorical" && !flags.includes("constant") && !isIdentifier

  return (
    <label className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted/60">
      <input
        type="checkbox"
        className="mt-0.5 h-4 w-4 shrink-0 accent-[color:var(--primary)]"
        checked={checked}
        onChange={onToggle}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="truncate font-medium">{col}</span>
          {profile && (
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              {profile.dtype_group}
            </span>
          )}
          <ColumnFlags flags={profile?.flags} profile={profile} nRows={nRows} />
        </div>
        {stats && !isIdentifier && (
          <div className="mt-1 flex items-center gap-3">
            <MiniDensityCurve histogram={profile?.histogram} idSuffix={col} />
            <dl className="flex gap-3 font-mono text-[11px] text-muted-foreground">
              <span title="Mean (average)">avg {fmtNum(stats.mean)}</span>
              <span title="Interquartile range (p75 − p25)">IQR {fmtNum(iqr)}</span>
              <span title="Variance (std²)">var {fmtNum(variance)}</span>
            </dl>
          </div>
        )}
        {showCategories && profile && <CategoryChips profile={profile} />}
      </div>
    </label>
  )
}

/** The available category values for a categorical column, as compact chips. Scales
 *  to high cardinality: shows at most CATEGORY_CHIP_LIMIT values (the most frequent,
 *  from the engine's top-K `top_values`) then a "+N more" tail, so a column with many
 *  categories never floods the picker. When the engine listed no values, falls back to
 *  the distinct count. */
const CATEGORY_CHIP_LIMIT = 6
function CategoryChips({ profile }: { profile: ColumnProfile }) {
  const values = profile.top_values ?? []
  if (values.length === 0) {
    return (
      <p className="mt-1 text-[11px] text-muted-foreground">
        {fmtInt(profile.n_unique)} categories
      </p>
    )
  }
  const shown = values.slice(0, CATEGORY_CHIP_LIMIT)
  const remaining = profile.n_unique - shown.length
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      {shown.map((v) => (
        <span
          key={v.value}
          title={`${v.value} · ${fmtInt(v.count)} rows`}
          className="max-w-[10rem] truncate rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
        >
          {v.value}
        </span>
      ))}
      {remaining > 0 && (
        <span className="text-[10px] text-muted-foreground">+{fmtInt(remaining)} more</span>
      )}
    </div>
  )
}

/** A Catmull-Rom spline through `points`, emitted as SVG cubic-bezier path data —
 *  gives a smooth density-style curve (rather than jagged line segments) from the
 *  handful of histogram points. */
function smoothPath(points: Array<{ x: number; y: number }>): string {
  if (points.length < 2) return ""
  let d = `M ${points[0].x},${points[0].y}`
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] ?? points[i]
    const p1 = points[i]
    const p2 = points[i + 1]
    const p3 = points[i + 2] ?? p2
    const cp1x = p1.x + (p2.x - p0.x) / 6
    const cp1y = p1.y + (p2.y - p0.y) / 6
    const cp2x = p2.x - (p3.x - p1.x) / 6
    const cp2y = p2.y - (p3.y - p1.y) / 6
    d += ` C ${cp1x.toFixed(2)},${cp1y.toFixed(2)} ${cp2x.toFixed(2)},${cp2y.toFixed(2)} ${p2.x.toFixed(2)},${p2.y.toFixed(2)}`
  }
  return d
}

/** A compact, dependency-free distribution CURVE: a smoothed density line over the
 *  histogram bins (anchored to the baseline at both ends so it reads like a bell /
 *  gaussian shape), with a soft gradient fill beneath. Pure inline SVG (no chart lib)
 *  so it stays light across many features and renders in jsdom. Decorative — the
 *  numbers carry the detail. `idSuffix` keeps each gradient's id unique in the DOM. */
function MiniDensityCurve({
  histogram,
  idSuffix,
}: {
  histogram?: Histogram | null
  idSuffix: string
}) {
  if (!histogram || histogram.counts.length === 0) return null
  const W = 100
  const H = 34
  const PAD = 4
  // Pad the counts with a zero at each end so the curve rises from and returns to the
  // baseline — the familiar density-plot silhouette even for a few bins.
  const counts = [0, ...histogram.counts, 0]
  const max = Math.max(...counts, 1)
  const n = counts.length
  const points = counts.map((c, i) => ({
    x: (i / (n - 1)) * W,
    y: H - PAD - (c / max) * (H - PAD * 2),
  }))
  const line = smoothPath(points)
  const area = `${line} L ${W},${H} L 0,${H} Z`
  const gid = `density-${idSuffix.replace(/[^a-zA-Z0-9_-]/g, "-")}`

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={96}
      height={30}
      preserveAspectRatio="none"
      className="shrink-0"
      role="img"
      aria-label="Value distribution"
    >
      <title>Value distribution</title>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.35" />
          <stop offset="100%" stopColor="var(--primary)" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path
        d={line}
        fill="none"
        stroke="var(--primary)"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

/** Explains what the engine does to categorical columns whose unique-value count
 *  exceeds the threshold. Such columns skip one-hot/ordinal encoding (which would
 *  explode width or impose a fake order) and fall back to target encoding on binary
 *  problems, or frequency encoding on multiclass/multilabel — mirroring the engine's
 *  Preprocessor (preprocess.py). */
/** Note for the decision-threshold mode selector. The threshold is binary-only; for
 *  multiclass/multilabel the model uses argmax and this setting is ignored (engine-side). */
function thresholdModeHint(mode: string, problemType: string): string {
  if (problemType !== "binary")
    return "Applies to binary problems only — multiclass/multilabel use argmax and ignore this."
  switch (mode) {
    case "tuned":
      return "The engine picks the probability cutoff that maximises the chosen metric, on train-only CV folds (never the test set)."
    case "fixed":
      return "Use the exact cutoff you set below to turn a probability into the positive class."
    default:
      return "Cut at 0.5 (sklearn's default). Rarely optimal on imbalanced data — try Auto-tune."
  }
}

function highCardinalityHint(problemType: string): string {
  const fallback =
    problemType === "binary"
      ? "target encoding (category → mean of the target)"
      : "frequency encoding (category → its training frequency)"
  return `Categorical columns with more unique values than this skip one-hot/ordinal encoding and use ${fallback} instead.`
}

/** Strategy-specific note for the NUMERIC missing-values selector. The strategy is
 *  applied only to numeric columns (categorical has its own selector), mirroring the
 *  engine's Preprocessor (preprocess.py). */
function missingNumericHint(strategy: string): string | undefined {
  switch (strategy) {
    case "mean":
    case "median":
      return `Each numeric column is filled with its training ${strategy}.`
    case "mode":
      return "Each numeric column is filled with its most frequent value (mode)."
    case "ffill":
      return "Forward-fills each numeric column from the previous row; leading rows with no prior value fall back to the training median."
    case "bfill":
      return "Backward-fills each numeric column from the next row; trailing rows with no later value fall back to the training median."
    case "knn":
      return "k-nearest-neighbours imputation (sklearn KNNImputer, k=5) fitted on the training numeric columns; values are estimated from the most similar rows."
    case "iterative":
      return "Iterative (model-based) imputation (sklearn IterativeImputer) fitted on the training numeric columns; each column is modelled from the others."
    case "drop":
      return "Training rows with a missing numeric value are dropped. At prediction time rows are imputed with the training median instead — rows are never dropped there."
    default:
      return undefined
  }
}

/** Missingness state for the selected feature columns of one kind (numeric vs
 *  everything-else). `summary` is the one-line note rendered above the per-strategy
 *  hint so the imputation choice is made knowing how much there is to impute; it
 *  mirrors the numeric/categorical split of the two selectors (and
 *  MissingByColumnPanel's `isNumeric`).
 *
 *  `disableSelector` is true ONLY when there ARE profiled selected columns of this
 *  kind and NONE of them have gaps: the per-type strategy would never fire, so the
 *  selector is locked (nothing to impute for this category) — the options stay listed,
 *  but the analyst can't pick one that has no effect. When no profiled column of that
 *  kind is selected the missingness is unknown (an older upload with no profile, or
 *  none picked), so `summary` is null and the selector stays enabled (unchanged). */
function missingState(
  featureCols: string[],
  profileByName: Map<string, ColumnProfile>,
  numeric: boolean,
): { summary: ReactNode; disableSelector: boolean } {
  const cols = featureCols
    .map((c) => profileByName.get(c))
    .filter((p): p is ColumnProfile => !!p && (p.dtype_group === "numeric") === numeric)
  const kind = numeric ? "numeric" : "categorical"
  if (cols.length === 0) return { summary: null, disableSelector: false }
  const withGaps = cols.filter((p) => p.n_missing > 0)
  const totalMissing = withGaps.reduce((sum, p) => sum + p.n_missing, 0)
  if (withGaps.length === 0) {
    return {
      summary: (
        <span className="text-emerald-600">
          No missing values in the {cols.length} selected {kind} column
          {cols.length === 1 ? "" : "s"} — nothing to impute for this category.{" "}
        </span>
      ),
      disableSelector: true,
    }
  }
  return {
    summary: (
      <span className="font-medium text-amber-700">
        {withGaps.length} of {cols.length} {kind} column{cols.length === 1 ? "" : "s"} with gaps
        ({fmtInt(totalMissing)} missing cell{totalMissing === 1 ? "" : "s"}).{" "}
      </span>
    ),
    disableSelector: false,
  }
}

/** Strategy-specific note for the CATEGORICAL (non-numeric) missing-values selector.
 *  Numeric statistics (mean/median) and the model-based imputers are intentionally
 *  not offered here — they are undefined for categorical values. */
function missingCategoricalHint(strategy: string): string | undefined {
  switch (strategy) {
    case "mode":
      return "Each categorical column is filled with its most frequent value (mode)."
    case "ffill":
      return "Forward-fills each categorical column from the previous row; leading rows with no prior value fall back to the mode."
    case "bfill":
      return "Backward-fills each categorical column from the next row; trailing rows with no later value fall back to the mode."
    case "drop":
      return "Training rows with a missing categorical value are dropped. At prediction time rows are imputed with the training mode instead — rows are never dropped there."
    default:
      return undefined
  }
}
