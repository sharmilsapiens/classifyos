"""
generate_sample_data.py — Synthetic insurance datasets for ClassifyOS development.

Produces 3 CSVs matching the scope's first use cases:
  policy_lapse.csv  — binary (will_lapse), ~22% positive, includes date col + missing values
  fraud_claims.csv  — binary (is_fraud), ~1% positive (99:1 imbalance for SMOTE testing)
  risk_tier.csv     — multiclass (risk_tier: Low/Medium/High)

Features have REAL signal (targets generated from logistic functions of the features),
so models trained on them produce meaningful metrics, plots, and SHAP values.
Includes: numeric + categorical mix, a high-cardinality column (occupation),
missing values (~3%), and a policy_start_date column for time-based split testing.

Usage:  python generate_sample_data.py [output_dir]
"""
import sys
import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
OUT = sys.argv[1] if len(sys.argv) > 1 else "."

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


# ---------- 1. Policy Lapse (binary, ~22% positive) ----------
n = 3000
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

lapse = pd.DataFrame({
    "policy_id": [f"POL{100000+i}" for i in range(n)],
    "policy_start_date": start.strftime("%Y-%m-%d"),
    "age": age, "occupation": occupation, "region": rng.choice(REGIONS, n),
    "policy_type": ptype, "channel": channel, "payment_frequency": pay_freq,
    "policy_tenure_years": tenure, "annual_premium": premium,
    "sum_assured": sum_assured, "num_late_payments": late_pay,
    "claims_count": claims_count, "has_agent": has_agent,
    "will_lapse": will_lapse,
})
lapse = add_missing(lapse, ["age", "annual_premium", "occupation"])
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

for name, df, tgt in [("policy_lapse", lapse, "will_lapse"),
                      ("fraud_claims", fraud, "is_fraud"),
                      ("risk_tier", risk, "risk_tier")]:
    print(f"{name}.csv  rows={len(df)}  target={tgt}  "
          f"distribution={df[tgt].value_counts(normalize=True).round(3).to_dict()}")
