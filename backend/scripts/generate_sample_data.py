"""
generate_sample_data.py — Synthetic insurance datasets for ClassifyOS development.

Produces the seven insurance use-case datasets the scope validates against, all with
REAL signal (targets generated from logistic / score functions of the features), so
models trained on them yield meaningful metrics, plots, and curves:

  Binary
    policy_lapse.csv      — will_lapse      (~22% positive; date col + missing values)
    claim_likelihood.csv  — will_claim      (motor book; telematics signal)
    fraud_claims.csv      — is_fraud        (~1% positive — 99:1 imbalance for SMOTE)
  Multiclass
    risk_tier.csv         — risk_tier       (Low / Medium / High)
    customer_segment.csv  — segment         (Budget / Mainstream / Affluent / HighNetWorth)
    claim_severity.csv    — severity        (Minor / Moderate / Severe)
  Multilabel
    product_reco.csv      — recommended_products  (a "|"-delimited SET of products per row,
                            drawn from {Auto, Home, Life, Health, Travel, Investment})

Plus, with --perf, a large performance-baseline set (NOT a use case, kept out of git):
    perf_lapse_12k.csv    — will_lapse, 12,000 rows (Phase 11 performance baseline)

Datasets include a numeric + categorical mix, a high-cardinality column (occupation),
~3% missing values, and (policy_lapse) a date column for time-based split testing.

Multilabel target encoding: the contract's `target` is a SINGLE column, so the
multilabel target is one string column holding a "|"-delimited label set per row
(e.g. "Auto|Home|Life"). The engine parses it into a multi-hot indicator matrix with
sklearn's MultiLabelBinarizer (fitted on the TRAIN split only). See plan_tweak.

Usage:
    python generate_sample_data.py [output_dir]            # the 7 use-case CSVs
    python generate_sample_data.py [output_dir] --perf     # also the 12k perf CSV
"""
import sys
import numpy as np
import pandas as pd

rng = np.random.default_rng(42)

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
_flags = {a for a in sys.argv[1:] if a.startswith("--")}
OUT = _args[0] if _args else "."
WITH_PERF = "--perf" in _flags

OCCUPATIONS = [
    "Teacher", "Engineer", "Nurse", "Driver", "Farmer", "Shop Owner", "Accountant",
    "Electrician", "Software Developer", "Doctor", "Lawyer", "Tailor", "Mechanic",
    "Salesperson", "Banker", "Police Officer", "Chef", "Plumber", "Architect",
    "Pharmacist", "Welder", "Carpenter", "Civil Servant", "Security Guard",
]
REGIONS = ["North", "South", "East", "West", "Central"]


def add_missing(df, cols, frac=0.03):
    for c in cols:
        idx = rng.choice(df.index, size=int(len(df) * frac), replace=False)
        df.loc[idx, c] = np.nan
    return df


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def _make_lapse(n):
    """Binary policy-lapse frame (factored out so --perf can reuse it at scale)."""
    age = rng.integers(21, 70, n)
    tenure = np.round(rng.exponential(4, n).clip(0.1, 25), 1)
    premium = np.round(rng.lognormal(9.2, 0.5, n), 0)            # annual premium
    sum_assured = premium * rng.integers(15, 60, n)
    late_pay = rng.poisson(1.2, n)
    pay_freq = rng.choice(["Monthly", "Quarterly", "Annual"], n, p=[0.55, 0.25, 0.20])
    channel = rng.choice(["Agent", "Online", "Bancassurance", "Broker"], n, p=[0.45, 0.25, 0.2, 0.1])
    ptype = rng.choice(["Term", "Endowment", "ULIP", "WholeLife"], n, p=[0.35, 0.3, 0.2, 0.15])
    has_agent = (channel == "Agent").astype(int)
    claims_count = rng.poisson(0.3, n)
    occupation = rng.choice(OCCUPATIONS, n)
    start = pd.Timestamp("2019-01-01") + pd.to_timedelta(rng.integers(0, 2200, n), unit="D")

    z = (-1.9 + 0.45 * late_pay - 0.12 * tenure
         + 0.35 * (pay_freq == "Monthly") + 0.5 * (channel == "Online")
         - 0.4 * has_agent + 0.3 * (ptype == "ULIP")
         + 0.25 * (premium / sum_assured * 100) + rng.normal(0, 0.6, n))
    will_lapse = (rng.random(n) < sigmoid(z)).astype(int)

    return pd.DataFrame({
        "policy_id": [f"POL{100000+i}" for i in range(n)],
        "policy_start_date": start.strftime("%Y-%m-%d"),
        "age": age, "occupation": occupation, "region": rng.choice(REGIONS, n),
        "policy_type": ptype, "channel": channel, "payment_frequency": pay_freq,
        "policy_tenure_years": tenure, "annual_premium": premium,
        "sum_assured": sum_assured, "num_late_payments": late_pay,
        "claims_count": claims_count, "has_agent": has_agent,
        "will_lapse": will_lapse,
    })


# ---------- 1. Policy Lapse (binary, ~22% positive) ----------
lapse = add_missing(_make_lapse(3000), ["age", "annual_premium", "occupation"])
lapse.to_csv(f"{OUT}/policy_lapse.csv", index=False)

# ---------- 2. Fraud Detection (binary, ~1% positive) ----------
n = 8000
claim_amt = np.round(rng.lognormal(10.3, 0.8, n), 0)
policy_age_m = rng.integers(1, 240, n)
report_delay = rng.poisson(5, n)
prior_claims = rng.poisson(0.5, n)
incident = rng.choice(["Accident", "Theft", "Fire", "Medical", "NaturalDisaster"],
                      n, p=[0.4, 0.2, 0.1, 0.25, 0.05])
police_report = rng.integers(0, 2, n)
claimant_age = rng.integers(18, 75, n)
witness = rng.integers(0, 2, n)

z = (-5.35 + 1.1 * (claim_amt > np.quantile(claim_amt, 0.9))
     + 0.9 * (policy_age_m < 12) + 0.08 * report_delay
     + 0.5 * prior_claims + 0.8 * (incident == "Theft")
     - 0.9 * police_report - 0.6 * witness + rng.normal(0, 0.5, n))
is_fraud = (rng.random(n) < sigmoid(z)).astype(int)

fraud = pd.DataFrame({
    "claim_id": [f"CLM{500000+i}" for i in range(n)],
    "claim_amount": claim_amt, "policy_age_months": policy_age_m,
    "report_delay_days": report_delay, "num_prior_claims": prior_claims,
    "incident_type": incident, "has_police_report": police_report,
    "has_witness": witness, "claimant_age": claimant_age,
    "region": rng.choice(REGIONS, n), "is_fraud": is_fraud,
})
fraud = add_missing(fraud, ["report_delay_days", "claimant_age"])
fraud.to_csv(f"{OUT}/fraud_claims.csv", index=False)

# ---------- 3. Risk Tier (multiclass: Low / Medium / High) ----------
n = 3000
age = rng.integers(18, 75, n)
bmi = np.round(rng.normal(26, 4.5, n).clip(15, 48), 1)
smoker = rng.choice([0, 1], n, p=[0.75, 0.25])
income = np.round(rng.lognormal(13.2, 0.6, n), 0)
credit = rng.integers(300, 901, n)
violations = rng.poisson(0.8, n)
occ_class = rng.choice(["Class1_Office", "Class2_Field", "Class3_Manual", "Class4_Hazardous"],
                       n, p=[0.45, 0.3, 0.18, 0.07])
vehicle_age = rng.integers(0, 16, n)

score = (0.04 * (age - 18) + 0.12 * (bmi - 22).clip(0) + 1.6 * smoker
         + 0.45 * violations - 0.004 * (credit - 300) / 6
         + 0.8 * (occ_class == "Class4_Hazardous") + 0.4 * (occ_class == "Class3_Manual")
         + rng.normal(0, 0.7, n))
q1, q2 = np.quantile(score, [0.45, 0.8])
risk_tier = np.where(score < q1, "Low", np.where(score < q2, "Medium", "High"))

risk = pd.DataFrame({
    "customer_id": [f"CUS{300000+i}" for i in range(n)],
    "age": age, "bmi": bmi, "is_smoker": smoker, "annual_income": income,
    "credit_score": credit, "prior_violations": violations,
    "occupation_class": occ_class, "vehicle_age": vehicle_age,
    "region": rng.choice(REGIONS, n), "risk_tier": risk_tier,
})
risk = add_missing(risk, ["bmi", "credit_score"])
risk.to_csv(f"{OUT}/risk_tier.csv", index=False)

# ---------- 4. Claim Likelihood (binary, motor book ~18% positive) ----------
# Generated AFTER the original three (policy_lapse / fraud / risk_tier) so those keep their
# exact, already-committed RNG draws (byte-identical CSVs). New use-case datasets follow.
n = 3500
cl_age = rng.integers(18, 80, n)
gender = rng.choice(["M", "F"], n)
vehicle_type = rng.choice(["Hatchback", "Sedan", "SUV", "Van", "Sports"], n,
                          p=[0.34, 0.3, 0.22, 0.1, 0.04])
vehicle_age = rng.integers(0, 20, n)
annual_mileage = np.round(rng.normal(12000, 4500, n).clip(1000, 40000), 0)
cl_prior = rng.poisson(0.4, n)
cl_tenure = np.round(rng.exponential(5, n).clip(0.1, 30), 1)
coverage = rng.choice(["ThirdParty", "Comprehensive", "Premium"], n, p=[0.35, 0.5, 0.15])
cl_credit = rng.integers(300, 901, n)
telematics = rng.choice([0, 1], n, p=[0.7, 0.3])

z = (-2.0 + 0.04 * (cl_age < 25) * 10 + 0.06 * vehicle_age
     + 0.00004 * (annual_mileage - 12000) + 0.6 * cl_prior
     + 0.5 * (vehicle_type == "Sports") + 0.3 * (coverage == "Premium")
     - 0.003 * (cl_credit - 300) / 6 - 0.7 * telematics + rng.normal(0, 0.5, n))
will_claim = (rng.random(n) < sigmoid(z)).astype(int)

claim_like = pd.DataFrame({
    "customer_id": [f"MOT{700000+i}" for i in range(n)],
    "age": cl_age, "gender": gender, "region": rng.choice(REGIONS, n),
    "vehicle_type": vehicle_type, "vehicle_age": vehicle_age,
    "annual_mileage": annual_mileage, "prior_claims": cl_prior,
    "policy_tenure_years": cl_tenure, "coverage_level": coverage,
    "credit_score": cl_credit, "has_telematics": telematics,
    "will_claim": will_claim,
})
claim_like = add_missing(claim_like, ["age", "annual_mileage", "credit_score"])
claim_like.to_csv(f"{OUT}/claim_likelihood.csv", index=False)

# ---------- 5. Customer Segment (multiclass: Budget/Mainstream/Affluent/HighNetWorth) ----------
n = 3200
cs_age = rng.integers(21, 80, n)
cs_income = np.round(rng.lognormal(13.0, 0.7, n), 0)
total_premium = np.round(cs_income * rng.uniform(0.01, 0.06, n), 0)
num_policies = rng.integers(1, 7, n)
cs_tenure = np.round(rng.exponential(6, n).clip(0.1, 35), 1)
digital = np.round(rng.uniform(0, 1, n), 2)        # digital engagement 0..1
claims_ratio = np.round(rng.beta(2, 8, n), 3)      # claims paid / premiums

# A latent "value" score → quartile-style segments (signal mostly from income + premium).
val = (0.00002 * cs_income + 0.0004 * total_premium + 0.25 * num_policies
       + 0.04 * cs_tenure + 0.6 * digital - 1.5 * claims_ratio
       + rng.normal(0, 0.8, n))
b1, b2, b3 = np.quantile(val, [0.35, 0.7, 0.9])
segment = np.where(val < b1, "Budget",
          np.where(val < b2, "Mainstream",
          np.where(val < b3, "Affluent", "HighNetWorth")))

cust_seg = pd.DataFrame({
    "customer_id": [f"SEG{800000+i}" for i in range(n)],
    "age": cs_age, "annual_income": cs_income, "total_premium": total_premium,
    "num_policies": num_policies, "tenure_years": cs_tenure,
    "region": rng.choice(REGIONS, n), "digital_engagement": digital,
    "claims_ratio": claims_ratio, "occupation": rng.choice(OCCUPATIONS, n),
    "segment": segment,
})
cust_seg = add_missing(cust_seg, ["annual_income", "digital_engagement"])
cust_seg.to_csv(f"{OUT}/customer_segment.csv", index=False)

# ---------- 6. Claim Severity (multiclass: Minor / Moderate / Severe) ----------
n = 3000
sev_amount = np.round(rng.lognormal(10.1, 0.9, n), 0)
sev_incident = rng.choice(["Accident", "Theft", "Fire", "Weather", "Liability"],
                          n, p=[0.45, 0.15, 0.12, 0.18, 0.10])
sev_policy_age = rng.integers(1, 240, n)
sev_claimant_age = rng.integers(18, 80, n)
injuries = rng.poisson(0.3, n)
damage_score = np.round(rng.uniform(0, 10, n), 1)
num_parties = rng.integers(1, 5, n)

sev_score = (0.6 * np.log1p(sev_amount) + 1.4 * injuries + 0.35 * damage_score
             + 0.3 * num_parties + 0.8 * (sev_incident == "Fire")
             + 0.5 * (sev_incident == "Weather") + rng.normal(0, 1.0, n))
s1, s2 = np.quantile(sev_score, [0.5, 0.85])
severity = np.where(sev_score < s1, "Minor",
           np.where(sev_score < s2, "Moderate", "Severe"))

claim_sev = pd.DataFrame({
    "claim_id": [f"SEV{900000+i}" for i in range(n)],
    "claim_amount": sev_amount, "incident_type": sev_incident,
    "region": rng.choice(REGIONS, n), "policy_age_months": sev_policy_age,
    "claimant_age": sev_claimant_age, "injuries": injuries,
    "vehicle_damage_score": damage_score, "num_parties": num_parties,
    "severity": severity,
})
claim_sev = add_missing(claim_sev, ["claim_amount", "vehicle_damage_score"])
claim_sev.to_csv(f"{OUT}/claim_severity.csv", index=False)

# ---------- 7. Product Recommendation (MULTILABEL: a "|"-delimited product SET) ----------
# The contract's target is a single column, so multilabel is encoded as ONE string column
# holding a per-row label set (e.g. "Auto|Home"). The engine parses it into a multi-hot
# indicator matrix (MultiLabelBinarizer, train-only fit). Each product's inclusion is an
# independent logistic function of the features, so labels carry real, separable signal.
n = 3000
pr_age = rng.integers(21, 75, n)
pr_income = np.round(rng.lognormal(13.1, 0.6, n), 0)
family_size = rng.integers(1, 6, n)
dependents = np.clip(family_size - 1 + rng.integers(-1, 2, n), 0, 5)
owns_home = rng.choice([0, 1], n, p=[0.45, 0.55])
owns_vehicle = rng.choice([0, 1], n, p=[0.3, 0.7])
risk_appetite = rng.choice(["Low", "Medium", "High"], n, p=[0.4, 0.4, 0.2])
existing_life = rng.choice([0, 1], n, p=[0.7, 0.3])

PRODUCTS = ["Auto", "Home", "Life", "Health", "Travel", "Investment"]
# Features standardised so the per-label prevalence is controllable (raw income/age would
# otherwise dominate the logits and make almost every product fire — an unrealistic, dense
# target). Centred intercepts target ~2.3 labels/row with real per-label variation.
inc_z = (np.log(pr_income) - 13.1) / 0.6
age_z = (pr_age - 45) / 15.0
logits = {
    "Auto":       -0.7 + 1.6 * owns_vehicle + 0.25 * age_z,
    "Home":       -0.8 + 1.7 * owns_home + 0.45 * inc_z,
    "Life":       -0.6 + 0.9 * (family_size > 2) + 0.8 * (dependents > 0) - 1.1 * existing_life,
    "Health":     -0.5 + 0.30 * (family_size - 3) + 0.30 * age_z,
    "Travel":     -0.9 + 0.50 * inc_z + 0.7 * (risk_appetite == "High"),
    "Investment": -0.9 + 0.60 * inc_z + 0.6 * (pr_age > 45) - 0.4 * (dependents > 2),
}
prob = {p: sigmoid(logits[p] + rng.normal(0, 0.5, n)) for p in PRODUCTS}
draw = {p: rng.random(n) < prob[p] for p in PRODUCTS}          # independent Bernoulli per product

label_sets = []
prob_matrix = np.column_stack([prob[p] for p in PRODUCTS])
for i in range(n):
    chosen = [p for p in PRODUCTS if draw[p][i]]
    if not chosen:
        # Guarantee at least one label per row (an empty recommendation is not useful and
        # would make the indicator row all-zeros). Take the highest-probability product.
        chosen = [PRODUCTS[int(np.argmax(prob_matrix[i]))]]
    label_sets.append("|".join(chosen))

prod_reco = pd.DataFrame({
    "customer_id": [f"PRD{600000+i}" for i in range(n)],
    "age": pr_age, "annual_income": pr_income, "family_size": family_size,
    "num_dependents": dependents, "owns_home": owns_home,
    "owns_vehicle": owns_vehicle, "risk_appetite": risk_appetite,
    "existing_life_policy": existing_life, "region": rng.choice(REGIONS, n),
    "recommended_products": label_sets,
})
prod_reco = add_missing(prod_reco, ["age", "annual_income"])
prod_reco.to_csv(f"{OUT}/product_reco.csv", index=False)

# ---------- (optional) Performance baseline set — 12,000 rows, NOT a use case ----------
# Large synthetic set for the Phase 11 ModelRunner.run() timing baseline. Kept OUT of git
# (generated into DATA_DIR only) — it is a throwaway benchmark artifact, not a fixture.
if WITH_PERF:
    perf = add_missing(_make_lapse(12000), ["age", "annual_premium", "occupation"])
    perf.to_csv(f"{OUT}/perf_lapse_12k.csv", index=False)

# ---------- summary ----------
summary = [
    ("policy_lapse", lapse, "will_lapse"),
    ("claim_likelihood", claim_like, "will_claim"),
    ("fraud_claims", fraud, "is_fraud"),
    ("risk_tier", risk, "risk_tier"),
    ("customer_segment", cust_seg, "segment"),
    ("claim_severity", claim_sev, "severity"),
]
for name, df, tgt in summary:
    print(f"{name}.csv  rows={len(df)}  target={tgt}  "
          f"distribution={df[tgt].value_counts(normalize=True).round(3).to_dict()}")

# Multilabel: report per-label prevalence (how many rows carry each product).
exploded = prod_reco["recommended_products"].str.split("|").explode()
print(f"product_reco.csv  rows={len(prod_reco)}  target=recommended_products (multilabel)  "
      f"per_label_counts={exploded.value_counts().to_dict()}  "
      f"avg_labels_per_row={round(exploded.groupby(level=0).size().mean(), 2)}")

if WITH_PERF:
    print(f"perf_lapse_12k.csv  rows={len(perf)}  target=will_lapse  (perf baseline; not committed)")
