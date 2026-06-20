/* ════════════════════════════════════════════════════════════════════════
   Shared E2E flow helpers.

   These are the reusable "drive the real UI" routines the specs build on. They
   are written for a reader new to Playwright, so the key APIs are explained
   inline the first time they appear:

   • `page`               — the browser tab Playwright controls.
   • `page.goto(path)`    — navigate (path is relative to baseURL = the Vite app).
   • `page.getByRole(...)`/`getByLabel(...)` — find elements the ACCESSIBLE way
     (by their role/name as a screen-reader sees them), not by brittle CSS.
   • `locator.click()/fill()/check()/selectOption()` — act on an element.
   • `expect(locator).toBeVisible()` — an auto-waiting assertion: Playwright keeps
     retrying until it's true or the timeout fires, so we don't sleep() manually.

   IMPORTANT design note — the app's run result lives in IN-MEMORY React state
   (the AppStore context). A full page reload (page.goto) WIPES it. So after a
   run, the specs reach the result pages via the in-app links (client-side
   routing), which preserve the store — never via page.goto. (See gotoResult.)
   ════════════════════════════════════════════════════════════════════════ */

import path from "node:path"
import { fileURLToPath } from "node:url"
import { expect, type Page } from "@playwright/test"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
// The committed sample CSVs the E2E uploads through the browser (these are the
// same files DATA_DIR points at — see playwright.config.ts).
const SAMPLES_DIR = path.resolve(__dirname, "..", "..", "backend", "data", "samples")

/** One insurance use case to drive end-to-end. Phase 11 extends this list to all
 *  seven; Phase 10 runs only the binary + multiclass entries below. */
export interface UseCase {
  /** Sample CSV filename under backend/data/samples (uploaded via the browser). */
  file: string
  /** Target column to predict. */
  target: string
  /** Problem framing — drives the binary-vs-multiclass curve/heatmap assertions. */
  problem_type: "binary" | "multiclass" | "multilabel"
  /** A couple of algorithms to train (kept small so the live run stays fast). */
  algorithms: string[]
  /** Known-good feature columns (curated — excludes id/datetime columns). */
  features: string[]
  /** Expected class labels (for confusion-matrix / curve-count assertions). */
  expectedClasses: string[]
}

// Curated feature lists per use case (exclude id/date columns). These mirror the backend
// conftest feature constants where one exists. expectedClasses are SORTED (the engine sorts
// classes, and the confusion-matrix labels / curve order follow that).
const LAPSE_FEATURES = [
  "age", "occupation", "region", "policy_type", "channel", "payment_frequency",
  "policy_tenure_years", "annual_premium", "sum_assured", "num_late_payments",
  "claims_count", "has_agent",
]
const CLAIM_LIKELIHOOD_FEATURES = [
  "age", "gender", "region", "vehicle_type", "vehicle_age", "annual_mileage",
  "prior_claims", "policy_tenure_years", "coverage_level", "credit_score", "has_telematics",
]
const FRAUD_FEATURES = [
  "claim_amount", "policy_age_months", "report_delay_days", "num_prior_claims",
  "incident_type", "has_police_report", "has_witness", "claimant_age", "region",
]
const RISK_FEATURES = [
  "age", "bmi", "is_smoker", "annual_income", "credit_score", "prior_violations",
  "occupation_class", "vehicle_age", "region",
]
const SEGMENT_FEATURES = [
  "age", "annual_income", "total_premium", "num_policies", "tenure_years",
  "region", "digital_engagement", "claims_ratio", "occupation",
]
const SEVERITY_FEATURES = [
  "claim_amount", "incident_type", "region", "policy_age_months", "claimant_age",
  "injuries", "vehicle_damage_score", "num_parties",
]
// Product Recommendation (multilabel — "|"-delimited target). expectedClasses are the labels.
const PRODUCT_FEATURES = [
  "age", "annual_income", "family_size", "num_dependents", "owns_home",
  "owns_vehicle", "risk_appetite", "existing_life_policy", "region",
]

/** Phase 11: ALL SEVEN insurance use cases (binary ×3, multiclass ×3, multilabel ×1). */
export const USE_CASES: UseCase[] = [
  {
    file: "policy_lapse.csv",
    target: "will_lapse",
    problem_type: "binary",
    algorithms: ["LogisticRegression", "RandomForest"],
    features: LAPSE_FEATURES,
    expectedClasses: ["0", "1"],
  },
  {
    file: "claim_likelihood.csv",
    target: "will_claim",
    problem_type: "binary",
    algorithms: ["LogisticRegression", "RandomForest"],
    features: CLAIM_LIKELIHOOD_FEATURES,
    expectedClasses: ["0", "1"],
  },
  {
    file: "fraud_claims.csv",
    target: "is_fraud",
    problem_type: "binary",
    algorithms: ["LogisticRegression", "RandomForest"],
    features: FRAUD_FEATURES,
    expectedClasses: ["0", "1"],
  },
  {
    file: "risk_tier.csv",
    target: "risk_tier",
    problem_type: "multiclass",
    algorithms: ["LogisticRegression", "RandomForest"],
    features: RISK_FEATURES,
    expectedClasses: ["High", "Low", "Medium"],
  },
  {
    file: "customer_segment.csv",
    target: "segment",
    problem_type: "multiclass",
    algorithms: ["LogisticRegression", "RandomForest"],
    features: SEGMENT_FEATURES,
    expectedClasses: ["Affluent", "Budget", "HighNetWorth", "Mainstream"],
  },
  {
    file: "claim_severity.csv",
    target: "severity",
    problem_type: "multiclass",
    algorithms: ["LogisticRegression", "RandomForest"],
    features: SEVERITY_FEATURES,
    expectedClasses: ["Minor", "Moderate", "Severe"],
  },
  {
    file: "product_reco.csv",
    target: "recommended_products",
    problem_type: "multilabel",
    algorithms: ["LogisticRegression", "RandomForest"],
    features: PRODUCT_FEATURES,
    // For multilabel these are the LABELS (one-vs-rest), not mutually-exclusive classes.
    expectedClasses: ["Auto", "Health", "Home", "Investment", "Life", "Travel"],
  },
]

/** All six algorithm checkboxes on the Configure page (MODEL_REGISTRY keys). */
const ALL_ALGORITHMS = [
  "LogisticRegression", "RandomForest", "XGBoost", "LightGBM", "SVM", "NaiveBayes",
]

/**
 * Step 1 — UPLOAD a CSV through the real browser, then pick the target.
 *
 * Proves the /upload round-trip: the file's columns + class-distribution chips
 * appear, which only happens if the browser reached :8000, the file was stored,
 * and inspect_file ran. Leaves the app on the Upload page with a target chosen
 * and the "Continue to Configuration" link enabled.
 */
export async function uploadDataset(page: Page, uc: UseCase) {
  await page.goto("/upload")

  // The health banner must be green first — that confirms the browser can reach
  // the backend at all (it pings /api/v1/health on mount).
  await expect(page.getByText(/API connected/i)).toBeVisible()

  // The file <input> is visually hidden (a styled drop-zone sits on top), but
  // setInputFiles works on hidden inputs directly — no need to click the zone.
  await page.locator('input[type="file"]').setInputFiles(path.join(SAMPLES_DIR, uc.file))

  // After upload the inspection profile renders: the columns table header shows
  // the count. Wait for it before touching the target picker.
  await expect(page.getByText(/^Columns ·/)).toBeVisible()

  // Pick the target column. Selecting it re-uploads (to fetch the class
  // distribution) — the Select is disabled while that request is in flight.
  await page.locator("#target").selectOption(uc.target)

  // The class-distribution chips appear once the re-inspect returns; and the
  // "Continue" link becomes enabled (aria-disabled flips to false).
  const continueLink = page.getByRole("link", { name: /Continue to Configuration/i })
  await expect(continueLink).toHaveAttribute("aria-disabled", "false")
}

/**
 * Step 2 — CONFIGURE the run: target, features, problem type, a couple of
 * algorithms, and the class-balance strategy. Then Step 3 — RUN it. Returns once
 * the run has been kicked off (the page navigates to Overview).
 */
export async function configureAndRun(page: Page, uc: UseCase) {
  // Move to Configuration via the in-app link (client-side nav, keeps the store).
  await page.getByRole("link", { name: /Continue to Configuration/i }).click()
  await expect(page.getByRole("heading", { name: "Configuration" })).toBeVisible()

  // Target is already set from Upload; assert it so the test reads honestly.
  await expect(page.locator("#target")).toHaveValue(uc.target)

  // Select exactly our curated feature columns. Each feature is a checkbox whose
  // accessible name is the column label (the <label> wraps the <input>).
  for (const col of uc.features) {
    await page.getByRole("checkbox", { name: col, exact: true }).check()
  }

  // Problem type: the only <select> that has a "multilabel" option is the
  // problem-type one — target it by that unique option value, then choose ours.
  await page.locator('select:has(option[value="multilabel"])').selectOption(uc.problem_type)

  // Algorithms: make the checked set EXACTLY uc.algorithms (defaults include
  // XGBoost; we keep the run to a couple of models). setChecked is idempotent.
  for (const algo of ALL_ALGORITHMS) {
    await page
      .getByRole("checkbox", { name: algo, exact: true })
      .setChecked(uc.algorithms.includes(algo))
  }

  // Class balance: the only <select> with a "class_weight" option is the
  // class-balance one. class_weight is fast (no resampling) and exercises the
  // balance config path — a good, quick choice for an E2E.
  await page.locator('select:has(option[value="class_weight"])').selectOption("class_weight")

  // Disable interaction auto-discovery (the #ix_enabled switch) so the live run
  // stays fast and deterministic — we don't assert on interaction columns here.
  // The Switch's <input> is `sr-only` (visually hidden beneath a styled track),
  // so a normal click is intercepted by the overlay — `force` clicks the real
  // accessible <input> directly. (It's still a genuine checkbox toggle.)
  await page.locator("#ix_enabled").uncheck({ force: true })

  // RUN. The button navigates to Overview ("/") and kicks off the synchronous run.
  await page.getByRole("button", { name: /Run pipeline/i }).first().click()

  // Overview should immediately show the in-progress state (the run is synchronous,
  // so the UI shows the canonical pipeline stages while it waits).
  await expect(page.getByText(/Running the full pipeline/i)).toBeVisible()
}

/**
 * Wait for the run to finish and the RESULTS state to render on Overview.
 * (The KPI band + "Model scoreboard" only appear on success.)
 */
export async function waitForResults(page: Page) {
  // The "Model scoreboard" card title (a styled <div>, not a heading) is the
  // clearest "results are here" signal once the synchronous run returns.
  await expect(page.getByText("Model scoreboard", { exact: true })).toBeVisible({
    timeout: 150_000, // training real models can take a while
  })
}

/**
 * Navigate to a result page via its in-app quick-link on Overview (client-side
 * routing — preserves the in-memory run result). `name` is the link text.
 */
export async function gotoResultViaLink(page: Page, name: RegExp) {
  await page.getByRole("link", { name }).first().click()
}
