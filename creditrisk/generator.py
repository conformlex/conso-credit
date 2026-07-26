"""Synthetic French consumer-credit application generator.

Guiding principle: the model you learn will never be better than the diversity
of this generator. Three mechanisms stop it from trivially recovering a
threshold rule:

1. A **latent risk** distinct from the assigned score. The observed default
   depends on latent risk, not on the underwriter's grade, so a model cannot
   deduce the outcome from the score.
2. **Decision noise.** Two underwriters do not rule identically on a file at 36%
   debt-to-income; the policy reflects that.
3. **Overrides.** A share of out-of-policy files is approved with an override
   reason. A dataset without exceptions teaches arithmetic, not a trade.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from .indicators import HCSF_THRESHOLD_PCT, compute, monthly_payment

# Deliberately old window: a recent application has too little hindsight for its
# outcome to be known, and a heavily censored dataset trains no default model.
# The most recent months stay censored, which is what a live book looks like.
DATE_MIN = date(2021, 1, 1)
DATE_MAX = date(2025, 6, 30)
# Minimum hindsight for an outcome to be considered observed.
OBSERVATION_MONTHS = 18

# --------------------------------------------------------------------------
# Socio-economic distributions (French orders of magnitude, net monthly)
# --------------------------------------------------------------------------

OCCUPATIONS = {
    "MANAGER_PROFESSIONAL": {"income": (3400, 900), "weight": 14},
    "INTERMEDIATE":         {"income": (2300, 500), "weight": 21},
    "CLERICAL":             {"income": (1750, 330), "weight": 27},
    "MANUAL_WORKER":        {"income": (1800, 340), "weight": 18},
    "SELF_EMPLOYED_TRADE":  {"income": (2400, 1100), "weight": 6},
    "FARMER":               {"income": (1700, 750), "weight": 2},
    "RETIRED":              {"income": (1650, 600), "weight": 9},
    "STUDENT":              {"income": (750, 280), "weight": 2},
    "INACTIVE":             {"income": (950, 300), "weight": 1},
}

# Plausible contracts per occupation, with relative weights.
CONTRACTS_BY_OCCUPATION = {
    "MANAGER_PROFESSIONAL": [("PERMANENT", 82), ("FIXED_TERM", 8),
                             ("SELF_EMPLOYED", 9), ("TEMP_AGENCY", 1)],
    "INTERMEDIATE":         [("PERMANENT", 66), ("CIVIL_SERVANT", 18),
                             ("FIXED_TERM", 12), ("TEMP_AGENCY", 4)],
    "CLERICAL":             [("PERMANENT", 58), ("CIVIL_SERVANT", 14),
                             ("FIXED_TERM", 18), ("TEMP_AGENCY", 10)],
    "MANUAL_WORKER":        [("PERMANENT", 55), ("FIXED_TERM", 17),
                             ("TEMP_AGENCY", 26), ("APPRENTICE", 2)],
    "SELF_EMPLOYED_TRADE":  [("SELF_EMPLOYED", 100)],
    "FARMER":               [("SELF_EMPLOYED", 100)],
    "RETIRED":              [("RETIRED", 100)],
    "STUDENT":              [("APPRENTICE", 62), ("FIXED_TERM", 28), ("TEMP_AGENCY", 10)],
    "INACTIVE":             [("UNEMPLOYED", 100)],
}

STABILITY = {
    "PERMANENT": "stable", "CIVIL_SERVANT": "stable", "RETIRED": "stable",
    "FIXED_TERM": "intermediate", "SELF_EMPLOYED": "intermediate",
    "TEMP_AGENCY": "precarious", "APPRENTICE": "precarious", "UNEMPLOYED": "precarious",
}

LOAN_TYPES = [
    # (code, weight, min_amount, max_amount, min_term, max_term, mean_rate)
    ("PERSONAL_LOAN",      32, 3000, 40000, 12, 84, 6.2),
    ("AUTO",               28, 5000, 45000, 24, 84, 4.9),
    ("HOME_IMPROVEMENT",   16, 4000, 50000, 24, 96, 5.4),
    ("REVOLVING",           9, 1000, 6000, 12, 48, 17.5),
    ("DEBT_CONSOLIDATION", 10, 8000, 60000, 48, 120, 7.1),
    ("LEASE_TO_OWN",        5, 8000, 35000, 24, 60, 5.8),
]

# Legal APR ceiling, approximated by amount bracket.
USURY_CAP = {"small": 21.0, "medium": 9.5, "large": 8.2}

DEPARTMENTS = ["75", "13", "69", "31", "44", "33", "59", "34", "35", "67",
               "06", "38", "76", "83", "51", "21", "29", "45", "63", "87"]


def _weighted_choice(rng: random.Random, options: list[tuple]) -> str:
    total = sum(w for _, w in options)
    threshold = rng.uniform(0, total)
    cumulative = 0.0
    for value, weight in options:
        cumulative += weight
        if threshold <= cumulative:
            return value
    return options[-1][0]


def _lognormal(rng: random.Random, mean: float, sd: float, floor: float) -> float:
    """Skewed draw: few very high incomes, realistic floor."""
    sigma = math.sqrt(math.log(1 + (sd / mean) ** 2))
    mu = math.log(mean) - sigma ** 2 / 2
    return max(floor, round(rng.lognormvariate(mu, sigma), 2))


# --------------------------------------------------------------------------
# Building one application
# --------------------------------------------------------------------------

def _draw_customer(rng: random.Random, application_date: date) -> dict:
    age = rng.randint(19, 78)
    birth = application_date - timedelta(days=int(age * 365.25) + rng.randint(0, 364))
    max_tenure = min((application_date - birth).days - 6570, 30 * 365)
    tenure = rng.randint(30, max(60, max_tenure))
    return {
        "birth_date": birth.isoformat(),
        "sex": rng.choice(["M", "F", "F", "M", "NR"]),
        "nationality_zone": _weighted_choice(rng, [("FR", 88), ("EU", 8), ("NON_EU", 4)]),
        "relationship_start_date": (application_date - timedelta(days=tenure)).isoformat(),
    }


def _draw_employment(rng: random.Random, age: int) -> dict:
    occupation = _weighted_choice(rng, [(c, d["weight"]) for c, d in OCCUPATIONS.items()])
    if age >= 63 and rng.random() < 0.75:
        occupation = "RETIRED"
    if age < 26 and occupation in ("RETIRED", "SELF_EMPLOYED_TRADE", "FARMER"):
        occupation = "CLERICAL"
    contract = _weighted_choice(rng, CONTRACTS_BY_OCCUPATION[occupation])
    if occupation == "RETIRED":
        contract = "RETIRED"

    max_tenure = max(6, (age - 20) * 12)
    tenure = min(max_tenure, int(abs(rng.gauss(0, 1)) * 60) + rng.randint(0, 12))
    probation = int(contract == "PERMANENT" and tenure < 4 and rng.random() < 0.55)

    return {
        "occupation_code": occupation,
        "contract_code": contract,
        "months_in_job": int(tenure),
        "in_probation_period": probation,
        "industry": rng.choice(
            ["Retail", "Manufacturing", "Healthcare", "Construction", "Transport",
             "IT", "Education", "Hospitality", "Services", "Public sector"]),
        "employer_type": (
            "self_employed" if contract == "SELF_EMPLOYED"
            else "public" if contract == "CIVIL_SERVANT"
            else "private"),
    }


def _draw_household(rng: random.Random, age: int) -> dict:
    if age < 26:
        status = _weighted_choice(rng, [("single", 70), ("cohabiting", 22), ("married", 8)])
    elif age < 60:
        status = _weighted_choice(rng, [
            ("married", 38), ("single", 24), ("cohabiting", 16),
            ("civil_union", 12), ("divorced", 10)])
    else:
        status = _weighted_choice(rng, [
            ("married", 46), ("widowed", 16), ("divorced", 18), ("single", 20)])

    couple = status in ("married", "civil_union", "cohabiting")
    adults = 2 if couple else 1
    children = 0
    if 24 < age < 60:
        children = int(_weighted_choice(rng, [(0, 44), (1, 24), (2, 22), (3, 8), (4, 2)]))
    young = rng.randint(0, children) if children else 0

    housing = _weighted_choice(rng, [
        ("TENANT", 46), ("OWNER_WITH_MORTGAGE", 24), ("OWNER_OUTRIGHT", 16),
        ("HOUSED_FREE", 11), ("EMPLOYER_HOUSING", 3)])
    if age < 25 and rng.random() < 0.4:
        housing = "HOUSED_FREE"
    if age < 30 and housing == "OWNER_OUTRIGHT":
        housing = "TENANT"

    return {
        "marital_status": status,
        "household_size": adults + children,
        "dependent_children": children,
        "children_under_14": young,
        "housing_status_code": housing,
        "months_at_address": min(int(abs(rng.gauss(0, 1)) * 70) + 3, max(6, (age - 18) * 12)),
        "department": rng.choice(DEPARTMENTS),
        "area_type": _weighted_choice(rng, [("urban", 52), ("suburban", 31), ("rural", 17)]),
        "_couple": couple,
    }


def _draw_incomes(rng: random.Random, employment: dict, household: dict,
                  co_employment: dict | None) -> list[dict]:
    incomes: list[dict] = []
    mean, sd = OCCUPATIONS[employment["occupation_code"]]["income"]
    primary = _lognormal(rng, mean, sd, 620)

    contract = employment["contract_code"]
    if contract == "RETIRED":
        incomes.append({"role": "primary", "income_type_code": "PENSION",
                        "monthly_amount": primary, "variability": "fixed",
                        "weighting": 1.0, "documented": 1})
    elif contract == "UNEMPLOYED":
        incomes.append({"role": "primary", "income_type_code": "UNEMPLOYMENT_BENEFIT",
                        "monthly_amount": primary, "variability": "fixed",
                        "weighting": 0.0, "documented": 1})
    elif contract == "SELF_EMPLOYED":
        incomes.append({"role": "primary", "income_type_code": "SELF_EMPLOYED_PROFIT",
                        "monthly_amount": primary, "variability": "variable",
                        "weighting": 0.9, "documented": 1})
    else:
        code = "CIVIL_SERVICE_PAY" if contract == "CIVIL_SERVANT" else "SALARY"
        incomes.append({"role": "primary", "income_type_code": code,
                        "monthly_amount": primary, "variability": "fixed",
                        "weighting": 1.0, "documented": int(rng.random() > 0.03)})

    if contract in ("PERMANENT", "CIVIL_SERVANT") and rng.random() < 0.3:
        incomes.append({"role": "primary", "income_type_code": "VARIABLE_BONUS",
                        "monthly_amount": round(primary * rng.uniform(0.05, 0.3), 2),
                        "variability": "variable", "weighting": 0.7,
                        "documented": int(rng.random() > 0.15)})

    if co_employment is not None:
        co_mean, co_sd = OCCUPATIONS[co_employment["occupation_code"]]["income"]
        incomes.append({"role": "co_borrower", "income_type_code": "SALARY",
                        "monthly_amount": _lognormal(rng, co_mean, co_sd, 620),
                        "variability": "fixed", "weighting": 1.0, "documented": 1})

    if household["dependent_children"] >= 2:
        incomes.append({"role": "household", "income_type_code": "FAMILY_BENEFITS",
                        "monthly_amount": round(140 + 90 * (household["dependent_children"] - 2), 2),
                        "variability": "fixed", "weighting": 1.0, "documented": 1})

    if rng.random() < 0.06:
        incomes.append({"role": "primary", "income_type_code": "RENTAL_INCOME",
                        "monthly_amount": round(rng.uniform(250, 1100), 2),
                        "variability": "variable", "weighting": 0.7, "documented": 1})

    return incomes


def _draw_expenses(rng: random.Random, household: dict, weighted_income: float) -> list[dict]:
    expenses: list[dict] = []
    if household["housing_status_code"] == "TENANT":
        base = weighted_income * rng.uniform(0.18, 0.34)
        expenses.append({"expense_type_code": "RENT",
                         "monthly_amount": round(max(280, base), 2),
                         "counted_in_dti": 1})
    if household["marital_status"] == "divorced" and rng.random() < 0.4:
        expenses.append({"expense_type_code": "ALIMONY_PAID",
                         "monthly_amount": round(rng.uniform(120, 480), 2),
                         "counted_in_dti": 1})
    if rng.random() < 0.22:
        expenses.append({"expense_type_code": "MONTHLY_TAX",
                         "monthly_amount": round(weighted_income * rng.uniform(0.02, 0.07), 2),
                         "counted_in_dti": 1})
    # Miscellaneous recurring expense: childcare, health cover, memberships.
    if rng.random() < 0.14:
        expenses.append({"expense_type_code": "OTHER_EXPENSE",
                         "monthly_amount": round(weighted_income * rng.uniform(0.02, 0.06), 2),
                         "counted_in_dti": 1})

    # An expense ending within a few months is declared on the file but left out
    # of the debt-to-income ratio, which is what `counted_in_dti` encodes. Rent
    # is excluded from the draw: it does not expire.
    for e in expenses:
        if e["expense_type_code"] != "RENT" and rng.random() < 0.12:
            e["counted_in_dti"] = 0
    return expenses


def _draw_existing_loans(rng: random.Random, household: dict, fragility: float,
                         loan_type: str, weighted_income: float) -> list[dict]:
    """Existing exposures.

    Instalments are drawn as a share of income rather than in absolute terms: an
    exposure drawn independently of income produces absurd debt ratios on low
    salaries. The total is capped — beyond it, the earlier loans would not have
    been granted in the first place.
    """
    loans: list[dict] = []
    if household["housing_status_code"] == "OWNER_WITH_MORTGAGE":
        payment = round(weighted_income * rng.uniform(0.14, 0.28), 2)
        term = rng.randint(36, 264)
        loans.append({"loan_kind": "mortgage",
                      "lender": "internal" if rng.random() < 0.5 else "external",
                      "outstanding_balance": round(payment * term * 0.88, 2),
                      "monthly_payment": payment, "remaining_months": term,
                      "repaid_by_this_loan": 0, "incidents_12m": 0})

    n_consumer = int(_weighted_choice(rng, [(0, 48), (1, 29), (2, 15), (3, 6), (4, 2)]))
    if fragility > 0.7 and rng.random() < 0.5:
        n_consumer += 1
    for _ in range(n_consumer):
        revolving = rng.random() < (0.22 + 0.35 * fragility)
        term = rng.randint(6, 36) if revolving else rng.randint(12, 60)
        payment = round(weighted_income * (rng.uniform(0.012, 0.045) if revolving
                                           else rng.uniform(0.025, 0.085)), 2)
        loans.append({
            "loan_kind": "revolving" if revolving else "amortising_consumer",
            "lender": "external" if rng.random() < 0.7 else "internal",
            "outstanding_balance": round(payment * term * 0.9, 2),
            "monthly_payment": payment,
            "remaining_months": term,
            "repaid_by_this_loan": 0,
            "incidents_12m": int(rng.random() < fragility * 0.35),
        })

    # Plausibility cap: an exposure already above 42% of income means the
    # previous loans would not have been approved.
    while loans and sum(loan["monthly_payment"] for loan in loans) > weighted_income * 0.42:
        loans.pop()

    # A consolidation loan by definition repays all or part of the consumer book.
    if loan_type == "DEBT_CONSOLIDATION":
        for loan in loans:
            if loan["loan_kind"] != "mortgage":
                loan["repaid_by_this_loan"] = 1
    return loans


def _draw_behaviour(rng: random.Random, fragility: float, income: float,
                    relationship_months: int) -> dict:
    days_overdrawn = int(min(366, max(0, rng.gauss(fragility * 95, 30))))
    rejections = int(max(0, rng.gauss(fragility * 3.2, 1.4)))

    # Moderate sigma and a 36-month-of-income cap: a heavy-tailed lognormal
    # produces manual workers with 68,000 EUR of savings, which corrupts both
    # the SOLID_SAVINGS reason and the latent risk.
    total_savings = round(max(0.0, rng.lognormvariate(math.log(max(400, income * 1.9)), 0.85)), 2)
    if fragility > 0.6:
        total_savings = round(total_savings * (1 - fragility * 0.8), 2)
    total_savings = round(min(total_savings, income * 36), 2)
    liquid = round(total_savings * rng.uniform(0.4, 1.0), 2)

    ficp = int(rng.random() < fragility ** 2 * 0.16)
    return {
        "average_balance": round(rng.gauss(income * (0.42 - 0.75 * fragility), income * 0.3), 2),
        "days_overdrawn_12m": days_overdrawn,
        "rejected_debits_12m": rejections,
        "overdraft_fees_12m": int(rejections * rng.uniform(1.0, 3.5)),
        "overdraft_limit": round(rng.choice([0, 200, 300, 500, 800, 1500]), 2),
        "max_overdraft_used": round(max(0, rng.gauss(fragility * 900, 350)), 2),
        "liquid_savings": liquid,
        "total_savings": total_savings,
        "products_held": max(1, int(rng.gauss(3.4, 1.5))),
        "salary_domiciled": int(rng.random() < 0.55 + 0.3 * min(1, relationship_months / 120)),
        "ficp_flagged": ficp,
        "fcc_flagged": int(ficp and rng.random() < 0.35),
        "loans_repaid_clean": max(0, int(rng.gauss(2.2 * (1 - fragility), 1.3))),
    }


# --------------------------------------------------------------------------
# Decision policy
# --------------------------------------------------------------------------

ADVERSE_REASONS = {
    "EXCESSIVE_DTI", "LOW_RESIDUAL_INCOME", "HIGH_PAYMENT_SHOCK",
    "INSUFFICIENT_INCOME", "TOO_MUCH_VARIABLE_PAY", "UNDOCUMENTED_INCOME",
    "PRECARIOUS_CONTRACT", "PROBATION_PERIOD", "SHORT_JOB_TENURE",
    "RECENT_MOVE", "PAYMENT_INCIDENTS", "HEAVY_OVERDRAFT_USE",
    "LOAN_INCIDENTS", "MULTIPLE_REVOLVING", "FICP_FLAG", "FCC_FLAG",
    "NO_SECURITY", "ABOVE_USURY_RATE",
}


def _reasons(ind, behaviour, employment, household, application, rng) -> list[str]:
    """Coded reasons derived from the state of the file."""
    codes: list[str] = []
    if ind.dti_after_pct > HCSF_THRESHOLD_PCT:
        codes.append("EXCESSIVE_DTI")
    elif ind.dti_after_pct < 28:
        codes.append("COMFORTABLE_DTI")

    if ind.residual_income_per_cu < 700:
        codes.append("LOW_RESIDUAL_INCOME")
    elif ind.residual_income_per_cu > 1300:
        codes.append("AMPLE_RESIDUAL_INCOME")

    if ind.payment_shock > ind.weighted_income * 0.20:
        codes.append("HIGH_PAYMENT_SHOCK")
    if ind.variable_income_share > 0.30:
        codes.append("TOO_MUCH_VARIABLE_PAY")
    if application["requested_amount"] > ind.weighted_income * 12:
        codes.append("INSUFFICIENT_INCOME")

    if STABILITY[employment["contract_code"]] == "precarious":
        codes.append("PRECARIOUS_CONTRACT")
    elif STABILITY[employment["contract_code"]] == "stable" and employment["months_in_job"] >= 24:
        codes.append("STABLE_EMPLOYMENT")
    if employment["in_probation_period"]:
        codes.append("PROBATION_PERIOD")
    if employment["months_in_job"] < 12 and employment["contract_code"] != "RETIRED":
        codes.append("SHORT_JOB_TENURE")
    if household["months_at_address"] < 6:
        codes.append("RECENT_MOVE")

    if behaviour["ficp_flagged"]:
        codes.append("FICP_FLAG")
    if behaviour["fcc_flagged"]:
        codes.append("FCC_FLAG")
    if behaviour["rejected_debits_12m"] >= 2:
        codes.append("PAYMENT_INCIDENTS")
    if behaviour["days_overdrawn_12m"] > 60:
        codes.append("HEAVY_OVERDRAFT_USE")
    if application["_revolving_loans"] >= 2:
        codes.append("MULTIPLE_REVOLVING")
    if application["_loan_incidents"] > 0:
        codes.append("LOAN_INCIDENTS")
    if ind.savings_months_of_expenses >= 3:
        codes.append("SOLID_SAVINGS")
    if (behaviour["rejected_debits_12m"] == 0
            and behaviour["days_overdrawn_12m"] <= 5
            and not behaviour["ficp_flagged"]):
        codes.append("CLEAN_HISTORY")
    if application["_relationship_months"] >= 96:
        codes.append("LONG_RELATIONSHIP")
    if behaviour["salary_domiciled"]:
        codes.append("SALARY_DOMICILED")
    if behaviour["loans_repaid_clean"] >= 2:
        codes.append("LOANS_REPAID_CLEAN")

    if application["has_co_borrower"]:
        codes.append("SOLID_CO_BORROWER")
    if application["down_payment"] > application["requested_amount"] * 0.15:
        codes.append("MEANINGFUL_DOWN_PAYMENT")
    if (not application["has_co_borrower"] and application["down_payment"] == 0
            and ind.savings_months_of_expenses < 1):
        codes.append("NO_SECURITY")
    if any(not i["documented"] for i in application["_incomes"]):
        codes.append("UNDOCUMENTED_INCOME")
    return codes


def _latent_risk(ind, behaviour, employment, application, rng,
                 intensity: float = 0.0) -> float:
    """True probability of default. Deliberately distinct from the assigned score.

    The underwriter observes noisy signals of this quantity, so a learned model
    must not be able to deduce the outcome from the grade.

    `intensity` shifts the logit intercept to over-sample defaults. At 0 the rate
    is realistic (~7% of approved, observed loans). Any non-zero value DISTORTS
    calibration: the learned model will overstate default probability and must be
    recalibrated against the real target rate. The value used is recorded in
    `generation_metadata`.
    """
    z = -3.05 + intensity
    z += 0.055 * max(0.0, ind.dti_after_pct - 30)
    z += 1.30 * (ind.residual_income_per_cu < 650)
    z += 0.95 * (STABILITY[employment["contract_code"]] == "precarious")
    z += 0.40 * (STABILITY[employment["contract_code"]] == "intermediate")
    z += 1.55 * behaviour["ficp_flagged"]
    z += 0.24 * min(6, behaviour["rejected_debits_12m"])
    z += 0.011 * behaviour["days_overdrawn_12m"]
    z += 0.34 * application["_revolving_loans"]
    z -= 0.55 * (ind.savings_months_of_expenses >= 3)
    z -= 0.22 * min(4, behaviour["loans_repaid_clean"])
    z -= 0.30 * application["has_co_borrower"]
    z -= 0.018 * min(60, employment["months_in_job"] / 2)
    z += rng.gauss(0, 0.55)  # unobserved heterogeneity
    return 1 / (1 + math.exp(-z))


def _decide(ind, behaviour, employment, application, reasons, risk, rng) -> dict:
    """Decision policy: noisy signal of risk + business rules + overrides."""
    perceived = risk + rng.gauss(0, 0.09)   # the underwriter does not see exact risk
    score = int(max(0, min(100, round(100 * (1 - perceived) + rng.gauss(0, 4)))))

    hard_decline = (
        behaviour["ficp_flagged"]
        or ind.dti_after_pct > 48
        or ind.residual_income_per_cu < 420
        or "INSUFFICIENT_INCOME" in reasons
    )
    grey_zone = 33 < ind.dti_after_pct <= 42 or 55 <= score < 68

    override = None
    if hard_decline and rng.random() < 0.07:
        if ind.savings_months_of_expenses >= 4:
            override = "OVERRIDE_WEALTH"
        elif application["_relationship_months"] >= 120:
            override = "OVERRIDE_RELATIONSHIP"
        else:
            override = "OVERRIDE_COMMERCIAL"

    if hard_decline and override is None:
        result = "declined"
    elif score < 45 and rng.random() < 0.82:
        result = "declined"
    elif grey_zone or override is not None or ind.dti_after_pct > HCSF_THRESHOLD_PCT:
        result = "approved_with_conditions" if rng.random() < 0.72 else (
            "approved" if rng.random() < 0.5 else "declined")
    elif score >= 68:
        result = "approved" if rng.random() < 0.88 else "approved_with_conditions"
    else:
        result = _weighted_choice(rng, [("approved", 45),
                                        ("approved_with_conditions", 40), ("declined", 15)])

    # A deferral means a document is missing, not a coin flip: a class with no
    # observable cause is unlearnable, and a model trained on it would defer
    # for no reason. It is therefore anchored on undocumented income or on a
    # relationship too new to assess.
    if "UNDOCUMENTED_INCOME" in reasons and rng.random() < 0.45:
        result = "deferred"
    elif application["_relationship_months"] < 6 and rng.random() < 0.20:
        result = "deferred"

    amount = term = conditions = None
    if result in ("approved", "approved_with_conditions"):
        amount = application["requested_amount"]
        term = application["term_months"]
        if result == "approved_with_conditions":
            lines = []
            if ind.dti_after_pct > HCSF_THRESHOLD_PCT and rng.random() < 0.7:
                amount = round(amount * rng.uniform(0.55, 0.85), 2)
                lines.append(f"montant ramene a {amount:.0f} EUR")
            if rng.random() < 0.35:
                term = max(6, int(term * rng.uniform(0.75, 1.0)))
                lines.append(f"duree ramenee a {term} mois")
            if not application["insurance_taken"] and rng.random() < 0.5:
                lines.append("souscription de l'assurance emprunteur exigee")
            if not lines:
                lines.append("justificatifs de revenus complementaires exiges avant deblocage")
            conditions = " ; ".join(lines)

    final_reasons = list(reasons)
    if override:
        final_reasons.append(override)
    if result == "declined" and not any(r in ADVERSE_REASONS for r in final_reasons):
        final_reasons.append("INSUFFICIENT_INCOME")

    grade = ("A" if score >= 82 else "B" if score >= 68 else
             "C" if score >= 52 else "D" if score >= 38 else "E")
    return {"result": result, "risk_score": score, "risk_grade": grade,
            "approved_amount": amount, "approved_term_months": term,
            "conditions": conditions, "reasons": final_reasons}


def _outcome(rng, risk, decision, application, application_date, today) -> dict | None:
    """What actually happened after disbursement."""
    if decision["result"] not in ("approved", "approved_with_conditions"):
        return None

    # A counter-offer that cuts the amount also cuts the real risk.
    ratio = decision["approved_amount"] / application["requested_amount"]
    effective_risk = risk * (0.55 + 0.45 * ratio)

    hindsight = (today - application_date).days // 30
    horizon = min(hindsight, decision["approved_term_months"], 48)
    # A loan is observable once it has run its course, even if its term was
    # shorter than the minimum hindsight: a 12-month loan taken out three years
    # ago is repaid, not "ongoing". Censor only what is still running AND has
    # not reached the observation window.
    if hindsight < min(decision["approved_term_months"], OBSERVATION_MONTHS):
        return {"status": "ongoing", "observation_months": max(0, horizon),
                "payments_made": max(0, horizon), "missed_payments": 0,
                "first_missed_payment_date": None, "balance_at_default": None,
                "sent_to_collections": 0, "closed_date": None}

    draw = rng.random()
    if draw < effective_risk:
        month_of_default = rng.randint(3, max(4, horizon))
        owed = round(decision["approved_amount"] * rng.uniform(0.35, 0.92), 2)
        return {"status": "default", "observation_months": horizon,
                "payments_made": month_of_default - 1,
                "missed_payments": rng.randint(3, 9),
                "first_missed_payment_date":
                    (application_date + timedelta(days=30 * month_of_default)).isoformat(),
                "balance_at_default": owed,
                "sent_to_collections": int(rng.random() < 0.55),
                "closed_date": None}
    if draw < effective_risk + 0.13:
        month_of_incident = rng.randint(2, max(3, horizon))
        return {"status": "minor_incidents", "observation_months": horizon,
                "payments_made": horizon, "missed_payments": rng.randint(1, 2),
                "first_missed_payment_date":
                    (application_date + timedelta(days=30 * month_of_incident)).isoformat(),
                "balance_at_default": None, "sent_to_collections": 0, "closed_date": None}
    if rng.random() < 0.10:
        return {"status": "early_repayment", "observation_months": horizon,
                "payments_made": horizon, "missed_payments": 0,
                "first_missed_payment_date": None, "balance_at_default": None,
                "sent_to_collections": 0,
                "closed_date": (application_date + timedelta(days=30 * horizon)).isoformat()}
    return {"status": "repaid_clean", "observation_months": horizon,
            "payments_made": horizon, "missed_payments": 0,
            "first_missed_payment_date": None, "balance_at_default": None,
            "sent_to_collections": 0,
            "closed_date": (application_date + timedelta(days=30 * horizon)).isoformat()
            if horizon >= decision["approved_term_months"] else None}


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def generate_application(rng: random.Random, today: date,
                         default_intensity: float = 0.0,
                         counterfactual_rng: random.Random | None = None) -> dict | None:
    """Produce a complete application, or None if the draw is incoherent."""
    span = (DATE_MAX - DATE_MIN).days
    application_date = DATE_MIN + timedelta(days=rng.randint(0, span))

    customer = _draw_customer(rng, application_date)
    age = (application_date - date.fromisoformat(customer["birth_date"])).days // 365
    employment = _draw_employment(rng, age)
    household = _draw_household(rng, age)

    co_customer = co_employment = None
    if household["_couple"] and rng.random() < 0.42:
        co_customer = _draw_customer(rng, application_date)
        co_age = (application_date - date.fromisoformat(co_customer["birth_date"])).days // 365
        co_employment = _draw_employment(rng, max(20, co_age))

    incomes = _draw_incomes(rng, employment, household, co_employment)
    weighted_income = sum(i["monthly_amount"] * i["weighting"] for i in incomes)
    if weighted_income < 500:
        return None
    expenses = _draw_expenses(rng, household, weighted_income)

    # Latent fragility: drives account behaviour and existing exposures.
    fragility = min(1.0, max(0.0, rng.betavariate(2, 4.5)
                             + 0.20 * (STABILITY[employment["contract_code"]] == "precarious")
                             - 0.12 * (employment["months_in_job"] > 60)))

    code, _, min_amt, max_amt, min_term, max_term, mean_rate = _weighted_choice(
        rng, [(t, t[1]) for t in LOAN_TYPES])
    term = rng.randint(min_term, max_term)
    rate = round(max(0.9, rng.gauss(mean_rate, mean_rate * 0.18)), 2)

    # The amount follows capacity, not the reverse: a borrower sizes the request
    # against what they think they can repay, and the network pre-filters
    # obviously unaffordable ones. Draw a target effort rate, then back out the
    # matching principal.
    effort = min(0.32, max(0.02, rng.gauss(0.105, 0.052)))
    r = rate / 100 / 12
    target_principal = (weighted_income * effort) * (1 - (1 + r) ** -term) / r
    amount = round(min(max_amt, max(min_amt, target_principal)), 2)

    loans = _draw_existing_loans(rng, household, fragility, code, weighted_income)
    relationship_months = (
        application_date - date.fromisoformat(customer["relationship_start_date"])).days // 30
    behaviour = _draw_behaviour(rng, fragility, weighted_income, relationship_months)

    insurance = int(rng.random() < 0.62)
    payment_excl = monthly_payment(amount, rate, term)
    insurance_cost = round(amount * 0.00035, 2) if insurance else 0.0
    total_payment = round(payment_excl + insurance_cost, 2)

    apr = round(rate + rng.uniform(0.3, 1.1), 2)
    cap = (USURY_CAP["small"] if amount < 3000
           else USURY_CAP["medium"] if amount < 6000 else USURY_CAP["large"])
    if apr > cap:
        return None  # unlawful operation: the file would never be submitted

    down_payment = round(amount * rng.uniform(0.05, 0.3), 2) if (
        code in ("AUTO", "HOME_IMPROVEMENT", "LEASE_TO_OWN") and rng.random() < 0.45) else 0.0

    application = {
        "application_date": application_date.isoformat(),
        "channel": _weighted_choice(rng, [("branch", 41), ("online", 27),
                                          ("broker", 12), ("point_of_sale", 20)]),
        "loan_type_code": code,
        "purpose": {"AUTO": "Vehicle", "HOME_IMPROVEMENT": "Home improvement works",
                    "PERSONAL_LOAN": "Personal project", "REVOLVING": "Cash reserve",
                    "DEBT_CONSOLIDATION": "Debt consolidation",
                    "LEASE_TO_OWN": "Lease with purchase option"}[code],
        "requested_amount": amount, "term_months": term,
        "nominal_rate": rate, "apr": apr, "usury_rate_cap": cap,
        "payment_excl_insurance": payment_excl, "insurance_taken": insurance,
        "monthly_insurance_cost": insurance_cost, "monthly_payment": total_payment,
        "down_payment": down_payment, "has_co_borrower": co_customer is not None,
        "_incomes": incomes,
        "_revolving_loans": sum(1 for loan in loans if loan["loan_kind"] == "revolving"),
        "_loan_incidents": sum(loan["incidents_12m"] for loan in loans),
        "_relationship_months": relationship_months,
    }

    ind = compute(incomes=incomes, expenses=expenses, loans=loans, household=household,
                  monthly_payment_total=total_payment,
                  liquid_savings=behaviour["liquid_savings"])
    if not (0 <= ind.dti_before_pct <= 190 and 0 <= ind.dti_after_pct <= 190):
        return None

    reasons = _reasons(ind, behaviour, employment, household, application, rng)
    risk = _latent_risk(ind, behaviour, employment, application, rng, default_intensity)
    decision = _decide(ind, behaviour, employment, application, reasons, risk, rng)
    if decision["approved_term_months"] and decision["approved_term_months"] > term:
        decision["approved_term_months"] = term
    outcome = _outcome(rng, risk, decision, application, application_date, today)

    # Counterfactual: what would have happened had this NON-approved application
    # been granted, at the amount and term requested. Drawn on a SEPARATE random
    # stream — otherwise every application shifts the sequence for the next one
    # and the whole database changes between runs, references included.
    counterfactual = None
    if outcome is None and counterfactual_rng is not None:
        counterfactual = _outcome(
            counterfactual_rng, risk,
            {"result": "approved", "approved_amount": application["requested_amount"],
             "approved_term_months": application["term_months"]},
            application, application_date, today)

    decision_date = application_date + timedelta(days=rng.randint(0, 6))

    return {
        "customer": customer, "co_customer": co_customer,
        "employment": employment, "co_employment": co_employment, "household": household,
        "incomes": incomes, "expenses": expenses, "loans": loans,
        "behaviour": behaviour, "indicators": ind, "application": application,
        "decision": decision, "outcome": outcome, "counterfactual": counterfactual,
        "decision_date": decision_date.isoformat(),
        "latent_risk": round(risk, 4),
    }
