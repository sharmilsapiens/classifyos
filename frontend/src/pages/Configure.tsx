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

import { useApp } from "@/store/AppStore"
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

// Allowed values — mirror config.py's tuples exactly.
const PROBLEM_TYPES = ["binary", "multiclass", "multilabel"] as const
const CLASS_BALANCE = ["smote", "undersample", "class_weight", "none"] as const
const MISSING = ["median", "mean", "mode", "ffill", "drop"] as const
const ENCODING = ["onehot", "label", "ordinal", "target"] as const
const SCALING = ["standard", "minmax", "robust", "none"] as const
const OUTLIER = ["iqr", "zscore", "none"] as const
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
              <div className="grid max-h-44 grid-cols-2 gap-x-4 gap-y-1.5 overflow-y-auto rounded-md border p-3 sm:grid-cols-3">
                {featureCandidates.map((col) => (
                  <label key={col} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-[color:var(--primary)]"
                      checked={form.feature_cols.includes(col)}
                      onChange={() => toggleFeature(col)}
                    />
                    <span className="truncate">{col}</span>
                  </label>
                ))}
              </div>
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
            <Field label="Decision threshold">
              <Input type="number" min={0} max={1} step={0.05} value={form.threshold}
                onChange={(e) => updateForm({ threshold: Number(e.target.value) })} />
            </Field>
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
            <Field label="Missing values" hint={missingValuesHint(form.missing_strategy)}>
              <Select value={form.missing_strategy}
                onChange={(e) => updateForm({ missing_strategy: e.target.value })}>
                {MISSING.map((c) => <option key={c} value={c}>{c}</option>)}
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
            <Field label="High-cardinality threshold">
              <Input type="number" min={2} value={form.high_cardinality_threshold}
                onChange={(e) => updateForm({ high_cardinality_threshold: Number(e.target.value) })} />
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

/** Strategy-specific note for the missing-values selector. Mean/median are
 *  numeric-only statistics, so categorical columns fall back to the most frequent
 *  value (mode); this mirrors the engine's Preprocessor (preprocess.py). */
function missingValuesHint(strategy: string): string | undefined {
  switch (strategy) {
    case "mean":
    case "median":
      return `Numeric columns use the ${strategy}. Categorical columns fall back to the most frequent value (mode), since a ${strategy} is undefined for them.`
    case "ffill":
      return "Forward-fills each column from the previous row. Categorical columns (and any leading rows with no prior value) fall back to the most frequent value (mode)."
    case "mode":
      return "Every column — numeric and categorical — is filled with its most frequent value (mode)."
    case "drop":
      return "Training rows with any missing value are dropped. At prediction time, rows are imputed with the training median (numeric) or mode (categorical) instead — rows are never dropped there."
    default:
      return undefined
  }
}
