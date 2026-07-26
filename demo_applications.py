#!/usr/bin/env python3
"""Ten demonstration applications for the scoring service.

    uvicorn api:app --port 8000 &
    python3 demo_applications.py

Writes the ten payloads to `examples/` — reusable as-is with curl — then sends
them to the service and prints the results.

They deliberately span the range: from a manager on a permanent contract to an
FICP-flagged file, via a debt consolidation (which exercises the handling of
instalments refinanced by the loan) and a self-employed applicant (which
exercises income weighting). A set of examples where everything is green is
worth nothing. Cardinalities are covered end to end: 0 to 4 expense lines, 1 to 5
income lines, 0 to 6 existing loans, every reference code used at least once.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

EXAMPLES_DIR = Path("examples")
URL = "http://localhost:8000"


def _application(reference, title_en, title_fr, operation, borrower, household,
                 behaviour, incomes, expenses=(), loans=()):
    return {
        "_title_en": title_en,
        "_title_fr": title_fr,
        "reference": reference,
        "operation": operation,
        "borrower": borrower,
        "household": household,
        "behaviour": behaviour,
        "incomes": list(incomes),
        "expenses": list(expenses),
        "existing_loans": list(loans),
    }


def _op(loan_type, amount, term, rate, apr, cap=8.2, insurance=True,
        down_payment=0.0, channel="branch"):
    return {
        "loan_type": loan_type, "requested_amount": amount, "term_months": term,
        "nominal_rate": rate, "apr": apr, "usury_rate_cap": cap,
        "insurance_taken": insurance,
        "monthly_insurance_cost": round(amount * 0.00035, 2) if insurance else 0.0,
        "down_payment": down_payment, "channel": channel,
    }


def _behaviour(relationship_months, **kw):
    base = {
        "relationship_months": relationship_months, "days_overdrawn_12m": 0,
        "rejected_debits_12m": 0, "max_overdraft_used": 0.0, "liquid_savings": 0.0,
        "products_held": 2, "salary_domiciled": True, "ficp_flagged": False,
        "fcc_flagged": False, "loans_repaid_clean": 0,
    }
    return base | kw


def _income(amount, weighting=1.0, variability="fixed", documented=True, type_="SALARY"):
    return {"type": type_, "monthly_amount": amount, "variability": variability,
            "weighting": weighting, "documented": documented}


def _loan(kind, payment, balance, months, repaid=False, incidents=0):
    return {"loan_kind": kind, "monthly_payment": payment,
            "outstanding_balance": balance, "remaining_months": months,
            "repaid_by_this_loan": repaid, "incidents_12m": incidents}


APPLICATIONS = [
    _application(
        "APP-EX-01",
        "Manager on a permanent contract, car loan with a down payment",
        "Cadre en CDI, credit auto avec apport",
        _op("AUTO", 22000, 60, 4.6, 5.1, down_payment=6000),
        {"occupation": "MANAGER_PROFESSIONAL", "contract_type": "PERMANENT",
         "months_in_job": 120, "in_probation_period": False, "has_co_borrower": False},
        {"household_size": 2, "dependent_children": 0, "children_under_14": 0,
         "housing_status": "OWNER_OUTRIGHT", "months_at_address": 84, "area_type": "urban"},
        _behaviour(180, liquid_savings=18000, products_held=6, loans_repaid_clean=3),
        [_income(3900)],
    ),
    _application(
        "APP-EX-02",
        "Clerical employee, debt-to-income at the regulatory threshold",
        "Employe en CDI, endettement a la limite du seuil HCSF",
        _op("PERSONAL_LOAN", 15000, 60, 6.1, 6.7),
        {"occupation": "CLERICAL", "contract_type": "PERMANENT",
         "months_in_job": 72, "in_probation_period": False, "has_co_borrower": False},
        {"household_size": 3, "dependent_children": 1, "children_under_14": 1,
         "housing_status": "TENANT", "months_at_address": 36, "area_type": "suburban"},
        _behaviour(96, days_overdrawn_12m=12, liquid_savings=2200, loans_repaid_clean=1),
        [_income(1950), _income(130, type_="FAMILY_BENEFITS"),
         _income(210, weighting=0.7, variability="variable", type_="VARIABLE_BONUS")],
        [{"type": "RENT", "monthly_amount": 620, "counted_in_dti": True},
         {"type": "MONTHLY_TAX", "monthly_amount": 95, "counted_in_dti": True}],
        [_loan("amortising_consumer", 120, 2800, 24)],
    ),
    _application(
        "APP-EX-03",
        "Temporary agency worker, personal loan — precarious contract",
        "Interimaire, pret personnel — contrat precaire",
        _op("PERSONAL_LOAN", 9000, 48, 7.2, 7.9, channel="online"),
        {"occupation": "MANUAL_WORKER", "contract_type": "TEMP_AGENCY",
         "months_in_job": 9, "in_probation_period": False, "has_co_borrower": False},
        {"household_size": 1, "dependent_children": 0, "children_under_14": 0,
         "housing_status": "TENANT", "months_at_address": 14, "area_type": "urban"},
        _behaviour(28, days_overdrawn_12m=45, rejected_debits_12m=1,
                   max_overdraft_used=800, liquid_savings=300, salary_domiciled=False),
        [_income(1720), _income(180, weighting=0.0, type_="UNEMPLOYMENT_BENEFIT")],
        [{"type": "RENT", "monthly_amount": 540, "counted_in_dti": True}],
    ),
    _application(
        "APP-EX-04",
        "FICP-flagged applicant — four expense lines, four existing loans",
        "Emprunteur fiche FICP — quatre charges, quatre encours",
        _op("DEBT_CONSOLIDATION", 25000, 96, 7.4, 8.0),
        {"occupation": "CLERICAL", "contract_type": "FIXED_TERM",
         "months_in_job": 8, "in_probation_period": False, "has_co_borrower": False},
        {"household_size": 4, "dependent_children": 2, "children_under_14": 2,
         "housing_status": "TENANT", "months_at_address": 9, "area_type": "urban"},
        _behaviour(36, days_overdrawn_12m=150, rejected_debits_12m=6,
                   max_overdraft_used=1500, ficp_flagged=True, fcc_flagged=True,
                   salary_domiciled=False),
        [_income(1680), _income(220, type_="FAMILY_BENEFITS")],
        [{"type": "RENT", "monthly_amount": 700, "counted_in_dti": True},
         {"type": "ALIMONY_PAID", "monthly_amount": 260, "counted_in_dti": True},
         {"type": "MONTHLY_TAX", "monthly_amount": 70, "counted_in_dti": True},
         {"type": "OTHER_EXPENSE", "monthly_amount": 85, "counted_in_dti": True}],
        [_loan("revolving", 95, 2400, 30, repaid=True, incidents=2),
         _loan("revolving", 110, 3100, 30, repaid=True, incidents=1),
         _loan("amortising_consumer", 180, 4900, 28, repaid=True),
         _loan("overdraft", 0, 1500, 0)],
    ),
    _application(
        "APP-EX-05",
        "Retired applicant, modest home improvement loan",
        "Retraite, credit travaux modeste",
        _op("HOME_IMPROVEMENT", 12000, 60, 5.2, 5.8),
        {"occupation": "RETIRED", "contract_type": "RETIRED",
         "months_in_job": 0, "in_probation_period": False, "has_co_borrower": False},
        {"household_size": 2, "dependent_children": 0, "children_under_14": 0,
         "housing_status": "OWNER_OUTRIGHT", "months_at_address": 264, "area_type": "rural"},
        _behaviour(360, liquid_savings=24000, products_held=7, loans_repaid_clean=4),
        [_income(1900, type_="PENSION"), _income(620, type_="PENSION")],
    ),
    _application(
        "APP-EX-06",
        "Debt consolidation — three balances refinanced by the loan",
        "Regroupement de credits — trois encours soldes par l'operation",
        _op("DEBT_CONSOLIDATION", 32000, 108, 7.0, 7.6),
        {"occupation": "INTERMEDIATE", "contract_type": "PERMANENT",
         "months_in_job": 60, "in_probation_period": False, "has_co_borrower": False},
        {"household_size": 3, "dependent_children": 1, "children_under_14": 0,
         "housing_status": "TENANT", "months_at_address": 60, "area_type": "suburban"},
        _behaviour(120, days_overdrawn_12m=30, liquid_savings=1500, loans_repaid_clean=2),
        [_income(2600), _income(90, type_="FAMILY_BENEFITS"),
         _income(320, weighting=0.7, variability="variable", type_="VARIABLE_BONUS"),
         _income(410, weighting=0.7, variability="variable", type_="RENTAL_INCOME")],
        [{"type": "RENT", "monthly_amount": 750, "counted_in_dti": True}],
        [_loan("amortising_consumer", 310, 9800, 34, repaid=True),
         _loan("amortising_consumer", 240, 7200, 32, repaid=True),
         _loan("revolving", 130, 3400, 28, repaid=True, incidents=1)],
    ),
    _application(
        "APP-EX-07",
        "Couple with a co-borrower — five income sources, five existing loans",
        "Couple avec co-emprunteur — cinq sources de revenus",
        _op("AUTO", 28000, 72, 4.8, 5.3, down_payment=4000),
        {"occupation": "INTERMEDIATE", "contract_type": "PERMANENT",
         "months_in_job": 96, "in_probation_period": False, "has_co_borrower": True},
        {"household_size": 4, "dependent_children": 2, "children_under_14": 2,
         "housing_status": "OWNER_WITH_MORTGAGE", "months_at_address": 72,
         "area_type": "suburban"},
        _behaviour(144, liquid_savings=9000, products_held=5, loans_repaid_clean=2),
        [_income(2400), _income(2100, type_="CIVIL_SERVICE_PAY"),
         _income(140, type_="FAMILY_BENEFITS"),
         _income(480, weighting=0.7, variability="variable", type_="RENTAL_INCOME"),
         _income(250, weighting=0.7, variability="variable", type_="VARIABLE_BONUS")],
        [{"type": "MONTHLY_TAX", "monthly_amount": 310, "counted_in_dti": True}],
        [_loan("mortgage", 890, 148000, 192),
         _loan("amortising_consumer", 145, 3500, 24),
         _loan("lease", 210, 6300, 30),
         _loan("revolving", 40, 800, 20),
         _loan("overdraft", 0, 300, 0)],
    ),
    _application(
        "APP-EX-08",
        "Self-employed, variable income, one declared expense not counted",
        "Independant, revenus variables, une charge declaree non retenue",
        _op("PERSONAL_LOAN", 20000, 72, 6.4, 7.0, channel="broker"),
        {"occupation": "SELF_EMPLOYED_TRADE", "contract_type": "SELF_EMPLOYED",
         "months_in_job": 48, "in_probation_period": False, "has_co_borrower": False},
        {"household_size": 2, "dependent_children": 0, "children_under_14": 0,
         "housing_status": "TENANT", "months_at_address": 30, "area_type": "urban"},
        _behaviour(60, days_overdrawn_12m=22, liquid_savings=5500, loans_repaid_clean=1),
        [_income(3100, weighting=0.9, variability="variable", type_="SELF_EMPLOYED_PROFIT")],
        # The last expense ends in two months: declared, not counted.
        [{"type": "RENT", "monthly_amount": 820, "counted_in_dti": True},
         {"type": "MONTHLY_TAX", "monthly_amount": 180, "counted_in_dti": True},
         {"type": "OTHER_EXPENSE", "monthly_amount": 130, "counted_in_dti": False}],
        [_loan("amortising_consumer", 95, 2100, 22),
         _loan("amortising_consumer", 70, 1400, 20),
         _loan("revolving", 45, 900, 20),
         _loan("lease", 180, 5400, 30),
         _loan("overdraft", 0, 600, 0),
         _loan("amortising_consumer", 55, 1100, 20)],
    ),
    _application(
        "APP-EX-09",
        "Apprentice housed free of charge, small loan — very short tenure",
        "Apprenti heberge, petit pret — faible anciennete",
        _op("PERSONAL_LOAN", 4500, 36, 8.1, 8.1, cap=9.5, channel="point_of_sale"),
        {"occupation": "STUDENT", "contract_type": "APPRENTICE",
         "months_in_job": 5, "in_probation_period": False, "has_co_borrower": False},
        {"household_size": 1, "dependent_children": 0, "children_under_14": 0,
         "housing_status": "HOUSED_FREE", "months_at_address": 5, "area_type": "urban"},
        _behaviour(14, days_overdrawn_12m=25, liquid_savings=400, products_held=1,
                   salary_domiciled=False),
        [_income(1050)],
    ),
    _application(
        "APP-EX-10",
        "Undocumented income and payment incidents",
        "Revenus non justifies et incidents bancaires",
        _op("AUTO", 16000, 60, 5.5, 6.1),
        {"occupation": "CLERICAL", "contract_type": "PERMANENT",
         "months_in_job": 30, "in_probation_period": False, "has_co_borrower": False},
        {"household_size": 2, "dependent_children": 1, "children_under_14": 1,
         "housing_status": "TENANT", "months_at_address": 18, "area_type": "urban"},
        _behaviour(48, days_overdrawn_12m=95, rejected_debits_12m=4,
                   max_overdraft_used=1200, liquid_savings=200),
        [_income(2050),
         _income(450, weighting=0.7, variability="variable", documented=False,
                 type_="VARIABLE_BONUS")],
        [{"type": "RENT", "monthly_amount": 690, "counted_in_dti": True}],
        [_loan("revolving", 85, 2100, 26, incidents=1),
         _loan("amortising_consumer", 130, 3300, 26)],
    ),
]


def _post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{URL}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "_detail": json.load(exc)}


def main() -> None:
    # Write the payloads first, unconditionally: the console reads them through
    # GET /examples, so they must exist even when the service is not up yet.
    EXAMPLES_DIR.mkdir(exist_ok=True)
    for i, raw in enumerate(APPLICATIONS, 1):
        (EXAMPLES_DIR / f"application_{i:02d}.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(APPLICATIONS)} payloads written to {EXAMPLES_DIR}/\n")

    try:
        urllib.request.urlopen(f"{URL}/health", timeout=5)
    except Exception:
        sys.exit(f"Service unreachable at {URL}. Run: uvicorn api:app --port 8000")

    results = [(i, raw["_title_en"], raw, _post("/score", raw))
               for i, raw in enumerate(APPLICATIONS, 1)]

    print(f"{'#':>2}  {'reference':<12}{'PD':>7}{'gr':>4}{'DTI':>8}{'resid/CU':>10}"
          f"{'payment':>9}  description")
    print("-" * 116)
    for i, title, _, r in results:
        if "_error" in r:
            print(f"{i:>2}  {'—':<12}{'rejected':>7}  {title}  [{r['_error']}]")
            continue
        ind = r["indicators"]
        print(f"{i:>2}  {r['reference']:<12}{r['probability_of_default']:>7.2%}"
              f"{r['risk_grade']:>4}{ind['dti_after_pct']:>8.1f}"
              f"{ind['residual_income_per_cu']:>10.0f}{ind['monthly_payment']:>9.0f}"
              f"  {title}")

    print("\nKey drivers, application by application:")
    for i, title, _, r in results:
        if "_error" in r:
            continue
        print(f"\n{i:>2}. {r['reference']} — {title}")
        print(f"    PD {r['probability_of_default']:.2%} (grade {r['risk_grade']})")
        if r["adverse_factors"]:
            print("    increases : " + " ; ".join(
                f"{f['variable']} = {f['value']} ({f['contribution']:+.2f})"
                for f in r["adverse_factors"][:2]))
        if r["favourable_factors"]:
            print("    reduces   : " + " ; ".join(
                f"{f['variable']} ({f['contribution']:+.2f})"
                for f in r["favourable_factors"][:2]))
        for w in r["warnings"]:
            print(f"    ! {w}")

    print("\n\nSimulation — largest amount keeping the PD under 5%:")
    print(f"{'#':>2}  {'reference':<12}{'initial PD':>12}{'requested':>11}{'maximum':>10}"
          f"{'reduction':>11}")
    print("-" * 60)
    for i, _, payload, r in results:
        if "_error" in r:
            continue
        s = _post("/simulate", {"application": payload, "target_pd": 0.05})
        maximum = s.get("maximum_amount")
        reduction = s.get("reduction_required")
        print(f"{i:>2}  {payload['reference']:<12}{s['initial_pd']:>12.2%}"
              f"{s['requested_amount']:>11.0f}"
              f"{(f'{maximum:.0f}' if maximum else 'none'):>10}"
              f"{(f'-{reduction:.0f}' if reduction else '—'):>11}")

    print(f"\nThe ten payloads are in {EXAMPLES_DIR}/ — usable as-is:")
    print(f"  curl -s -X POST {URL}/score -H 'Content-Type: application/json' "
          f"-d @{EXAMPLES_DIR}/application_03.json")


if __name__ == "__main__":
    main()
