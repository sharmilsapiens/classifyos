# Why ClassifyOS — Fine-Tuned for Insurance

*Why a specialized tool, what makes it insurance-specific, and what it adds.*

> Companion to [`business_overview.md`](business_overview.md) (the plain-language overview) and
> [`technical_overview.md`](technical_overview.md) (the engineering map). This document answers
> the question a reviewer will ask: **"Why build ClassifyOS instead of using a general AutoML
> tool such as Databricks AutoML or DataRobot?"** — and what makes it *specialized for
> insurance*.

---

## 1. Why ClassifyOS, and not an off-the-shelf AutoML?

General AutoML platforms (Databricks AutoML, DataRobot, and similar) are powerful, broad, and
**domain-agnostic** — they can model almost any problem in any industry and are strong at
breadth, ensembling, and enterprise MLOps. ClassifyOS is deliberately the **opposite**: narrow,
owned, and shaped for **insurance classification**, driven by an **analyst in a browser**.

It is not an either/or with the platform. ClassifyOS **runs on** Databricks — it offloads heavy
training to Databricks Jobs and records runs in Databricks MLflow. So it competes with the
AutoML *feature*, while *complementing* the platform you already pay for.

| Dimension | **ClassifyOS** | **Databricks AutoML** | **DataRobot** |
|---|---|---|---|
| What it is | A focused, in-house **web app** (owned code) | A glass-box AutoML feature (generates notebooks) | A commercial AutoML platform |
| Primary user | **Business analyst**, no coding | Data scientist | Analyst → data scientist |
| Scope | Insurance **classification** only | Classification, regression, forecasting | Very broad + ensembles |
| Domain | **Insurance-native** | Domain-agnostic | Domain-agnostic |
| Cost / ownership | No license; reuses your Azure + Databricks; fully modifiable | Bundled with Databricks | Significant licensing |

**Honest boundary.** The commercial platforms are ahead on breadth of algorithms and automatic
ensembling, on regression/forecasting, and on mature production MLOps (monitoring, drift,
retraining, compliance docs). ClassifyOS trades that breadth for **fit, focus, ownership, low
cost, and insurance-native design** — the right choice when a full platform is overkill, too
costly, too general, or too much for a non-data-scientist to drive.

---

## 2. What makes it fine-tuned for insurance

The insurance specialization is built into the design, not bolted on:

1. **Ships around real insurance problems.** Built and validated against seven canonical use
   cases — policy lapse, claim likelihood, **fraud**, risk tier, customer segment, claim
   severity, and product recommendation — each with a sample dataset. An analyst starts from
   something recognizable, not a blank canvas.
2. **The problem shapes insurers actually need.** Binary (lapse / fraud), multiclass (risk
   tier / segment / severity), and multilabel (product recommendation) — the categorical
   outcomes insurance predicts.
3. **Rare events are handled by default.** Fraud can run ~99:1. So plain accuracy is
   deliberately de-emphasized (a model that never flags fraud is still "99% accurate"); the
   tool **leads with F1 / MCC / PR-AUC** and has built-in imbalance handling (SMOTE /
   undersample / class-weight), applied to the training data only.
4. **Reason codes for underwriters — the regulatory need.** Each decision can be explained as
   a plain-language **adverse-action narrative** ("flagged high lapse-risk *chiefly because of*
   a high number of late payments, only partly offset by a longer tenure"), citing the
   **original, un-scaled values**. This is the explainability insurers must produce for
   decisions.
5. **Trustworthy probabilities and tunable cut-offs.** Probability **calibration** is on by
   default, and the **decision threshold** is tunable — so you can set where the fraud-flag or
   lapse cut-off sits, which matters because 0.5 is rarely the best operating point on skewed
   insurance data.
6. **Guards against classic insurance-data traps.** It flags **identifier-like columns**
   (policy/reference numbers that leak the answer or won't generalize) and enforces
   no-data-leakage by design — it actually caught suspected target leakage on a real dataset
   during testing.
7. **Domain features without code.** Analysts build insurance-relevant derived columns from
   menus — e.g. *premium ÷ sum-assured*, or *policy duration = end − start* — never by writing
   a formula.
8. **Reads data where insurers keep it, and respects governance.** It runs against database
   and Databricks Unity Catalog tables **as that user's own identity**, and keeps a run
   history / audit trail — appropriate for a regulated industry.

---

## 3. What ClassifyOS adds

Compared with pointing a **general AutoML tool** at the problem (or an analyst working by
hand), ClassifyOS layers on the insurance-specific value:

| A general AutoML gives you… | …ClassifyOS adds |
|---|---|
| A trained model and a leaderboard | **Insurance use-case templates + sample data** to start from |
| Generic evaluation metrics | **Rare-event-first metrics** (F1 / MCC / PR-AUC) — fraud-ready out of the box |
| Feature importance / SHAP inside a notebook | **Underwriter-ready reason-code narratives** that cite real values |
| A blank canvas to configure yourself | **Insurance defaults**, ID/leakage guards, calibrated probabilities + tunable thresholds |
| Notebooks aimed at a data scientist | A **no-code browser workflow** an analyst can drive end to end |
| A platform to license and learn | **Owned source, no license**, running on your **existing** Azure + Databricks |

In short, it adds the **insurance framing, the guard-rails, the explanations, and the
self-service workflow** on top of the raw modelling — the parts a general tool leaves you to
assemble yourself.

---

## 4. Impact & benefits

A short view of why that specialization matters in practice:

- **Faster ideas → answers.** A first, evaluated model in **minutes instead of a multi-week
  data-science project** — cheap to try an idea before committing to it.
- **Frees scarce expertise.** Analysts self-serve the routine models in the browser; the
  data-science team is freed for the genuinely hard problems.
- **Lower cost, no lock-in.** No per-seat/consumption license, and it reuses infrastructure the
  business already pays for (Azure + Databricks).
- **Fewer bad models reach production.** Built-in leakage guards and honest, rare-event-aware
  metrics catch the failures that make a model look great in testing and fail in the real
  world.
- **Regulator- and underwriter-ready.** Per-decision reason codes and a recorded run history
  support fair, reviewable, auditable decisions — a requirement in insurance, not a nice-to-have.
- **Consistent and repeatable.** One standard, governed pipeline for everyone, instead of
  ad-hoc analyses that are hard to review or reproduce.

*(For the full benefits list and the how-to-use guide, see [`business_overview.md`](business_overview.md).)*

---

## Learn more

- [`business_overview.md`](business_overview.md) — the plain-language overview + how-to-use guide.
- [`technical_overview.md`](technical_overview.md) — architecture, what's built, and how to extend it.
- [`../README.md`](../README.md) — the full documentation index.
