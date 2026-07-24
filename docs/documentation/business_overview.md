# ClassifyOS — Business Overview

*A self-service machine-learning tool for insurance teams.*
*Built for Sapiens (AI/ML Data) using an AI-assisted (GenAI) development workflow.*

> **Audience:** business stakeholders, managers, and anyone who wants to understand *what
> ClassifyOS is and why it matters* — no technical background needed. For the engineering
> side, see [`technical_overview.md`](technical_overview.md).

---

## 1. What ClassifyOS is, in one paragraph

ClassifyOS is an in-house web application that lets an insurance analyst turn ordinary
tabular data (spreadsheets, database tables) into a working prediction model — **without
writing any code**. You bring your data, tell it what you want to predict, and click *Run*.
In a few minutes it trains several machine-learning models, tells you how good each one is,
shows you which factors drove the predictions, and can explain *why* it made an individual
decision in plain language. It is built specifically around the questions insurers ask every
day: *will this policy lapse? is this claim fraudulent? which risk tier does this customer
belong to?*

Think of it as **"a data scientist's first week of work, delivered in a few minutes, through
a browser."**

---

## 2. The problem it solves

Insurance teams sit on large amounts of structured data — policies, claims, customers,
payments — that could power better decisions. But turning that data into a reliable
prediction model normally requires:

- a **data scientist** (a scarce, expensive skill),
- **weeks** of hand-written code, experimentation, and review, and
- careful attention to subtle mistakes that make a model look great in testing but fail in
  the real world.

ClassifyOS removes those barriers. It packages the standard, careful, end-to-end modelling
workflow into a guided web tool that an analyst can drive themselves — while still applying
the safeguards and rigour a good data scientist would insist on.

---

## 3. Business benefits

| Benefit | What it means for the business |
|---|---|
| **Speed** | A first, evaluated model in **minutes instead of weeks** — analysts can test an idea before committing a data-science project to it. |
| **Self-service, no coding** | Analysts build models themselves through the browser. The scarce data-science team is freed for the hardest problems, not every first cut. |
| **Built for insurance** | Ships ready for the real problems: lapse, claims, fraud, risk tiering, segmentation, claim severity, and product recommendation (see §4). |
| **Explainable & audit-ready** | Every prediction can be explained in **plain-language reason codes** ("flagged high lapse-risk *because* of X and Y"). Essential for underwriting decisions and regulatory scrutiny — and every run is recorded so results are traceable. |
| **Trustworthy by design** | Actively guards against the ways models silently "cheat" (learning from information they wouldn't have in real life), and reports honest scores — it leads with measures that stay meaningful even when the event is rare. |
| **Handles rare events** | Fraud can be roughly **1 in 100** cases. ClassifyOS is built to handle these lopsided problems properly, rather than being fooled by them. |
| **Reuses existing investment** | Runs on the organisation's **existing Azure and Databricks** platforms — heavy work is offloaded to Databricks; no new large infrastructure is required. |
| **Scales with the work** | From a laptop for quick experiments to Databricks for large datasets — the same tool, the same screens. |
| **Consistent & repeatable** | One standard, governed process for everyone, instead of ad-hoc, one-off analyses that are hard to review or reproduce. |

---

## 4. What it can predict — the insurance use cases

ClassifyOS is validated against seven representative insurance problems. Each is just a
column in your data that you want to predict:

| Use case | Business question | Type |
|---|---|---|
| **Policy lapse** | Will this policy lapse / not renew? | Yes / No |
| **Claim likelihood** | Will this policyholder file a claim? | Yes / No |
| **Fraud detection** | Is this claim likely fraudulent? *(rare event, ~99:1)* | Yes / No |
| **Risk tier** | Which risk band does this customer fall into? | One of several |
| **Customer segment** | Which segment does this customer belong to? | One of several |
| **Claim severity** | How severe is this claim likely to be? | One of several |
| **Product recommendation** | Which products should we recommend? | Several at once |

The same tool handles all three shapes of question: **yes/no**, **one-of-several**, and
**several-at-once**. If your business has a different question, as long as the answer is a
category you can point ClassifyOS at your own data and predict it.

---

## 5. How to use it — a step-by-step guide

ClassifyOS is a website. Once it is deployed (see §6), a user simply opens it in their
browser — there is nothing to install. The whole experience is **Upload → Configure → Run →
Explore.**

1. **Open ClassifyOS** in your web browser at your organisation's address. A status light
   confirms the service is connected and ready.

2. **Bring your data.** Choose one of three sources:
   - **Upload a file** — drag in a CSV or Excel/Parquet file; or
   - **Pick a database table** — select from a connected database; or
   - **Pick a Databricks table** — browse your data catalog and choose a table (recommended
     for large datasets, so the data never has to leave the platform).

3. **Review the Data Profile.** The tool instantly summarises your data — each column's
   distribution and key numbers, how much data is missing, and how columns relate to one
   another. It also **flags risky columns** (for example an ID-like column that would mislead
   the model) so you can exclude them before you start.

4. **Configure the run.** In plain forms you choose:
   - **what to predict** (the target column) and **which columns to use**,
   - the options you care about (how to handle missing values, whether to let the tool
     **automatically search for the best model settings**, whether to produce per-decision
     **explanations**, and more).
   - You can also build your own derived columns (e.g. *premium ÷ sum-assured*, or *policy
     duration in days*) by **picking from menus** — never by typing a formula.

5. **Run.** Click once. ClassifyOS trains several models, scores them, and produces the
   charts and tables. Large runs are handed to Databricks and you watch the progress.

6. **Explore the results:**
   - a **scoreboard** ranking each model, so you can see the best performer at a glance;
   - **charts** showing where each model is right and wrong, how confidently it separates the
     classes, and which factors it relied on;
   - a **predictions table** you can download;
   - an **Explainability** view that, for a single case, shows *why* the model decided the way
     it did — and can write it up as a short, plain-language paragraph an underwriter can read.

7. **Keep a record.** Runs can be saved to a **run history**, so results survive, can be
   revisited later, and stack up as an auditable trail of what was tried.

That is the entire workflow — no scripts, no notebooks, no code.

---

## 6. Where it runs today, and the deployment plan (AKS)

**Today**, ClassifyOS runs in two ways:
- on a developer's machine for demonstrations and experiments, and
- with its heavy model-training **offloaded to Databricks**, reading data straight from the
  organisation's data catalog.

**The next step** is to deploy ClassifyOS on **Azure Kubernetes Service (AKS)** — Microsoft
Azure's managed platform for running web applications reliably at scale. In practice this
means ClassifyOS becomes an **always-on internal web app** that anyone on the team can open
from a company web address, with:

- **no installation** — it is just a website;
- **central and secure** hosting inside the organisation's Azure environment;
- **heavy training still offloaded to Databricks**, so the app itself stays lightweight and
  responsive even for large datasets;
- room to **grow with demand** — more people can use it at once without slowdowns.

A complete, step-by-step **deployment guide has already been written and handed to the DevOps
team** (see [`../deployment/deploy.md`](../deployment/deploy.md)); carrying out that
deployment is the planned next milestone.

---

## 7. Trust, governance, and responsible use

ClassifyOS was built to be trusted with decisions that matter, so it is deliberately honest
about what it does and does not do:

- **Guards against "cheating."** A common, silent failure in machine learning is a model that
  learns from information it would not actually have when making a real prediction — making it
  look far better in testing than it will be in practice. ClassifyOS is designed from the
  ground up to prevent this, and it warns you about columns that look suspicious.
- **Honest scoring.** On rare-event problems like fraud, simple "accuracy" is misleading (a
  model that never flags fraud can still be 99% "accurate"). ClassifyOS leads with measures
  that stay meaningful for rare events.
- **Explainability for decisions.** Predictions can be explained per case, which supports
  fair, reviewable, and regulator-friendly decision-making in underwriting and claims.
- **A recorded trail.** Runs can be logged with their settings, scores, and outputs — so a
  result can always be traced back to how it was produced.
- **Human in the loop.** ClassifyOS is a **decision-support tool**. Its outputs are meant to
  inform expert judgement, not replace it, and a formal review/sign-off process is part of its
  release.
- **Validated on realistic sample data so far.** To date the tool has been proven on
  synthetic (realistic but manufactured) insurance datasets. **Re-validation on real business
  data** is a planned step before it is relied upon for live decisions.

---

## 8. Status and what's next

**Status:** the software is **feature-complete for its first version (v1.0)** — all seven
insurance use cases run end-to-end, through the browser, with full results, charts, and
explanations. It is going through **final review and sign-off** before formal release.

**On the roadmap (business view):**

- **Deploy on AKS** so the whole team can use it from a browser (the immediate next step —
  guide already written).
- **Validate on real business data** (today's results are on realistic synthetic data).
- **Handle larger datasets and run faster** — process bigger tables and train models in
  parallel so results come back sooner (details in the technical overview).
- **Broaden data connections** and **wider team rollout** as adoption grows.

---

## 9. Learn more

- [`technical_overview.md`](technical_overview.md) — the engineering companion to this
  document (architecture, how it's built, how to run it, and how to extend it).
- [`../deployment/deploy.md`](../deployment/deploy.md) — the AKS deployment guide (for
  DevOps).
- [`../README.md`](../README.md) — the full documentation index.
