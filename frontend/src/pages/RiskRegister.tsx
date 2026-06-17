/* Risk Register — the project's known ML risks and how the engine mitigates each.

   WHY STATIC: these are the engine's real [RISK] points (embedded as inline
   comments at leakage / imbalance / calibration / multicollinearity / threshold
   sites) plus the GenAI governance checks. They live in engine source + the
   planning docs (CLAUDE.md "critical constraints", scope §9/§12), not in any API
   response — there is no endpoint exposing them, and adding one would be a
   frozen-backend change. Authored here from the real build so it is accurate, not
   aspirational. Each entry is risk → mitigation (what the engine actually does).

   Sources: CLAUDE.md "Critical constraints", the engine [RISK] comments
   (preprocess/balance/metrics/tuning/runner), plan_tweak.md, and the governance
   checklist in PROJECT_STATE.md. */

import { Link } from "react-router-dom"
import { ShieldAlert, ShieldCheck } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { PageHeader } from "@/components/common/States"

type Severity = "high" | "medium" | "low"

interface Risk {
  id: string
  title: string
  severity: Severity
  risk: string
  mitigation: string
}

// Each mitigation describes what the engine ACTUALLY does (not what it aspires to).
const RISKS: Risk[] = [
  {
    id: "leakage",
    title: "Data leakage (train/test contamination)",
    severity: "high",
    risk: "If the encoder, scaler, imputer, or SMOTE see the test set, information leaks from test into training and metrics are optimistic — the model looks better than it is.",
    mitigation: "The pipeline splits BEFORE preprocessing. Encoder/scaler/imputer are fitted on the TRAINING split only and merely applied to the test set; balancing (SMOTE/undersample/class-weight) takes no test argument at all, so it is train-only by construction. Dedicated leakage tests guard binning edges, MI auto-discovery, and 'test set untouched'.",
  },
  {
    id: "imbalance",
    title: "Class imbalance (misleading accuracy)",
    severity: "high",
    risk: "On a skewed target (e.g. fraud ~99:1) raw accuracy is misleading — 'always predict the majority' scores ~99% while catching zero positives.",
    mitigation: "F1-weighted is the primary metric; MCC and PR-AUC are reported alongside accuracy. Balancing offers SMOTE / undersample / class-weight; the Class Report surfaces the weakest-recall class so a poorly-predicted minority is visible.",
  },
  {
    id: "smote-tiny",
    title: "Synthetic minority realism (tiny minorities)",
    severity: "medium",
    risk: "SMOTE interpolates between neighbours; with a very small minority it errors, and with a single minority sample it cannot synthesise variety at all.",
    mitigation: "k_neighbors is auto-reduced to min(5, minority_count − 1); a minority of ≤1 sample falls back to RandomOverSampler (duplication, logged). The fallback adds no synthetic variety — that is flagged rather than hidden.",
  },
  {
    id: "calibration",
    title: "Probability calibration",
    severity: "medium",
    risk: "Predicted probabilities may not match observed frequencies, so a 0.8 score doesn't mean 80% — risky when probabilities drive downstream decisions or thresholds.",
    mitigation: "A reliability diagram (plot5, binary) plots predicted vs observed against the perfect diagonal so miscalibration is visible. SVM uses CalibratedClassifierCV. Calibration is binary-only; multiclass shows a labelled placeholder rather than implying it was checked.",
  },
  {
    id: "multicollinearity",
    title: "Multicollinearity from engineered features",
    severity: "medium",
    risk: "Polynomial and interaction features are correlated with their source columns; piling them on inflates collinearity, destabilises linear-model coefficients, and explodes feature width.",
    mitigation: "Polynomial features default OFF and are capped (max_poly_features, ranked by |train corr|). Interaction auto-discovery caps the candidate pool at the 15 most target-correlated numerics and keeps only positive-MI-gain pairs. The Interaction Features page shows exactly which columns were created.",
  },
  {
    id: "threshold",
    title: "Threshold sensitivity",
    severity: "medium",
    risk: "A binary decision threshold (default 0.5) trades precision against recall; the wrong threshold for an imbalanced problem can make a usable model look useless (or vice-versa).",
    mitigation: "Threshold is an explicit config field. ROC and PR curves (full test set, from the single sanctioned curve helper so the PNG and the JSON never drift) show the whole precision/recall trade-off, not just the operating point at one threshold.",
  },
  {
    id: "temporal",
    title: "Temporal leakage",
    severity: "medium",
    risk: "A random split on time-ordered data lets the model 'see the future' — training on later events to predict earlier ones — overstating real-world performance.",
    mitigation: "A time_split_col enables a temporal (last-fraction) split instead of a random stratified one, and an inline [RISK] comment marks the temporal-leakage point in the split code. The run profile records which split was used.",
  },
  {
    id: "proba-shape",
    title: "Probability matrix shape/order assumption",
    severity: "low",
    risk: "Downstream code indexes probability columns by class; if a wrapper returned a different column order or a 1-column binary proba, every metric and curve would be silently wrong.",
    mitigation: "Every model wrapper guarantees predict_proba returns (n_samples, n_classes) aligned to classes_ (two columns for binary, never one). A shared template base implements this once so it cannot drift between the six models; an inline [RISK] comment marks the engine-wide assumption.",
  },
  {
    id: "governance",
    title: "GenAI-generated code (hallucination / governance)",
    severity: "high",
    risk: "This framework is GenAI-developed: a model can hallucinate a library API that doesn't exist in the installed version, or generated code can deviate silently from the signed plan.",
    mitigation: "Every phase runs a hallucination check against the INSTALLED library versions (pinned in requirements.lock); generation prompts are archived under prompts/ (version control); each section has unit tests on real sample data; and every deviation from the scope is recorded in plan_tweak.md. [RISK] comments are never removed without documented rationale.",
  },
]

// The governance checklist (scope §12) — what's signed off vs still open.
const GOVERNANCE: Array<{ item: string; done: boolean }> = [
  { item: "Prompt version control — prompts/ populated per section", done: true },
  { item: "Section-level unit tests passing on real sample data", done: true },
  { item: "Output schema contract locked (/api/v1/run, schema_version 1.0)", done: true },
  { item: "Hallucination check — library calls verified against installed versions", done: true },
  { item: "[RISK] comments reviewed by team lead", done: false },
  { item: "Leakage audit (encoder/scaler/SMOTE train-only) signed off", done: false },
  { item: "Per-phase team-lead sign-off (Naveen)", done: false },
]

const SEVERITY_VARIANT: Record<Severity, "destructive" | "warning" | "secondary"> = {
  high: "destructive",
  medium: "warning",
  low: "secondary",
}

export default function RiskRegister() {
  return (
    <div>
      <PageHeader
        title="Risk Register"
        subtitle="Known ML risks and the mitigations actually built into the engine."
      />

      <div className="mb-5 flex items-start gap-3 rounded-lg border bg-card p-4 text-sm text-muted-foreground">
        <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />
        <p>
          These are the engine's real <span className="font-mono">[RISK]</span> points — embedded as
          inline comments at the leakage, imbalance, calibration, multicollinearity, and threshold
          sites — plus the GenAI governance checks. Each mitigation describes what the code does
          today, on synthetic sample data; real-data and multilabel validation are Week-4 work.
        </p>
      </div>

      <div className="space-y-4">
        {RISKS.map((r) => (
          <Card key={r.id}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-3 text-base">
                <span>{r.title}</span>
                <Badge variant={SEVERITY_VARIANT[r.severity]}>{r.severity}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 text-sm sm:grid-cols-2">
              <div>
                <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  <ShieldAlert className="h-3.5 w-3.5" aria-hidden /> Risk
                </div>
                <p className="text-foreground">{r.risk}</p>
              </div>
              <div>
                <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-emerald">
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> Mitigation
                </div>
                <p className="text-foreground">{r.mitigation}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Governance checklist */}
      <Card className="mt-5">
        <CardHeader>
          <CardTitle>Governance checklist (scope §12)</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2 text-sm">
            {GOVERNANCE.map((g) => (
              <li key={g.item} className="flex items-start gap-2.5">
                <Badge variant={g.done ? "success" : "warning"} className="mt-0.5 shrink-0">
                  {g.done ? "done" : "open"}
                </Badge>
                <span className={g.done ? "text-foreground" : "text-muted-foreground"}>{g.item}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted-foreground">
            The open items are the Week-4 (Phase 10–11) agenda: [RISK]-comment review, the
            leakage-audit sign-off, and per-phase team-lead approval.
          </p>
          <div className="mt-3">
            <Link to="/setup" className={buttonVariants({ variant: "outline", size: "sm" })}>
              Back to the Setup Guide
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
