#!/usr/bin/env python3
"""Populate the database with synthetic consumer-credit applications.

    python3 populate.py [count] [--seed N] [--rebuild] [--default-intensity X]

Insert order matters: `decision_reason` before `decision` (the
`trg_declined_needs_reason` trigger checks that a decline is motivated at the
moment the decision row is written), and `outcome` after `decision`.
"""

from __future__ import annotations

import argparse
import random
from datetime import date

from creditrisk import db
from creditrisk.generator import generate_application
from creditrisk.indicators import FORMULA_VERSION
from creditrisk.rationale import write as write_rationale

TODAY = date(2026, 7, 27)


def _split(rng: random.Random) -> str:
    """Stored partition, never redrawn at export time."""
    t = rng.random()
    return "train" if t < 0.70 else "val" if t < 0.85 else "test"


def _insert(conn, app: dict, n: int, rng: random.Random) -> None:
    cur = conn.cursor()

    def create_customer(c: dict) -> int:
        cur.execute(
            """INSERT INTO customer (reference, birth_date, sex, nationality_zone,
                                     relationship_start_date)
               VALUES (?, ?, ?, ?, ?)""",
            (f"CUS-{cur.lastrowid or 0:06d}-{n:05d}", c["birth_date"], c["sex"],
             c["nationality_zone"], c["relationship_start_date"]))
        return cur.lastrowid

    customer_id = create_customer(app["customer"])
    co_id = create_customer(app["co_customer"]) if app["co_customer"] else None

    a = app["application"]
    cur.execute(
        """INSERT INTO application (reference, customer_id, co_borrower_id, application_date,
                                    channel, loan_type_code, purpose, requested_amount,
                                    term_months, nominal_rate, apr, usury_rate_cap,
                                    payment_excl_insurance, insurance_taken,
                                    monthly_insurance_cost, monthly_payment, down_payment,
                                    split, source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (f"APP-{a['application_date'][:4]}-{n:06d}", customer_id, co_id, a["application_date"],
         a["channel"], a["loan_type_code"], a["purpose"], a["requested_amount"],
         a["term_months"], a["nominal_rate"], a["apr"], a["usury_rate_cap"],
         a["payment_excl_insurance"], a["insurance_taken"], a["monthly_insurance_cost"],
         a["monthly_payment"], a["down_payment"], _split(rng), "generated"))
    application_id = cur.lastrowid

    h = app["household"]
    cur.execute("INSERT INTO household VALUES (?,?,?,?,?,?,?,?,?)",
                (application_id, h["marital_status"], h["household_size"],
                 h["dependent_children"], h["children_under_14"], h["housing_status_code"],
                 h["months_at_address"], h["department"], h["area_type"]))

    for role, employment in (("primary", app["employment"]),
                             ("co_borrower", app["co_employment"])):
        if employment is None:
            continue
        cur.execute(
            "INSERT INTO employment VALUES (?,?,?,?,?,?,?,?)",
            (application_id, role, employment["occupation_code"], employment["contract_code"],
             employment["months_in_job"], employment["in_probation_period"],
             employment["industry"], employment["employer_type"]))

    for i in app["incomes"]:
        cur.execute(
            """INSERT INTO income (application_id, role, income_type_code, monthly_amount,
                                   variability, weighting, documented)
               VALUES (?,?,?,?,?,?,?)""",
            (application_id, i["role"], i["income_type_code"], i["monthly_amount"],
             i["variability"], i["weighting"], i["documented"]))

    for e in app["expenses"]:
        cur.execute(
            """INSERT INTO expense (application_id, expense_type_code, monthly_amount,
                                    counted_in_dti) VALUES (?,?,?,?)""",
            (application_id, e["expense_type_code"], e["monthly_amount"], e["counted_in_dti"]))

    for loan in app["loans"]:
        cur.execute(
            """INSERT INTO existing_loan (application_id, loan_kind, lender,
                                          outstanding_balance, monthly_payment,
                                          remaining_months, repaid_by_this_loan, incidents_12m)
               VALUES (?,?,?,?,?,?,?,?)""",
            (application_id, loan["loan_kind"], loan["lender"], loan["outstanding_balance"],
             loan["monthly_payment"], loan["remaining_months"], loan["repaid_by_this_loan"],
             loan["incidents_12m"]))

    b = app["behaviour"]
    cur.execute(
        "INSERT INTO account_behaviour VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (application_id, b["average_balance"], b["days_overdrawn_12m"],
         b["rejected_debits_12m"], b["overdraft_fees_12m"], b["overdraft_limit"],
         b["max_overdraft_used"], b["liquid_savings"], b["total_savings"],
         b["products_held"], b["salary_domiciled"], b["ficp_flagged"], b["fcc_flagged"],
         b["loans_repaid_clean"]))

    ind = app["indicators"]
    cur.execute(
        """INSERT INTO indicators (application_id, gross_income, weighted_income,
             variable_income_share, counted_expenses, existing_payments, retained_payments,
             dti_before_pct, dti_after_pct, above_hcsf_threshold, consumption_units,
             residual_income, residual_income_per_cu, payment_shock,
             savings_months_of_expenses, formula_version)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (application_id, ind.gross_income, ind.weighted_income, ind.variable_income_share,
         ind.counted_expenses, ind.existing_payments, ind.retained_payments,
         ind.dti_before_pct, ind.dti_after_pct, ind.above_hcsf_threshold,
         ind.consumption_units, ind.residual_income, ind.residual_income_per_cu,
         ind.payment_shock, ind.savings_months_of_expenses, ind.formula_version))

    d = app["decision"]
    # Reasons precede the decision: the declined-needs-reason trigger requires them.
    for code in dict.fromkeys(d["reasons"]):
        cur.execute("INSERT INTO decision_reason VALUES (?,?)", (application_id, code))

    cur.execute(
        """INSERT INTO decision (application_id, result, approved_amount, approved_term_months,
             risk_score, risk_grade, conditions, rationale, decided_by, decision_date)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (application_id, d["result"], d["approved_amount"], d["approved_term_months"],
         d["risk_score"], d["risk_grade"], d["conditions"],
         write_rationale(app, rng), "rule_engine", app["decision_date"]))

    if app.get("counterfactual"):
        cf = app["counterfactual"]
        cur.execute("INSERT INTO counterfactual_outcome VALUES (?,?,?,?)",
                    (application_id, cf["status"], cf["observation_months"],
                     cf["missed_payments"]))

    if app["outcome"]:
        o = app["outcome"]
        cur.execute(
            "INSERT INTO outcome VALUES (?,?,?,?,?,?,?,?,?)",
            (application_id, o["status"], o["observation_months"], o["payments_made"],
             o["missed_payments"], o["first_missed_payment_date"], o["balance_at_default"],
             o["sent_to_collections"], o["closed_date"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("count", nargs="?", type=int, default=40000)
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--rebuild", action="store_true",
                        help="drop and recreate the database")
    parser.add_argument(
        "--default-intensity", type=float, default=0.0,
        help="shift of the latent-risk intercept. 0 = realistic rate (~7%%). "
             "A positive value over-samples defaults and REQUIRES recalibrating the "
             "predicted probabilities. Recorded in generation_metadata.")
    args = parser.parse_args()

    conn = db.initialise(overwrite=args.rebuild)
    rng = random.Random(args.seed)
    # Dedicated stream: guarantees that adding the counterfactual does not shift
    # any application already generated with the same seed.
    cf_rng = random.Random(args.seed + 1)

    produced = rejected = 0
    while produced < args.count:
        app = generate_application(rng, TODAY, args.default_intensity, cf_rng)
        if app is None:
            rejected += 1
            continue
        _insert(conn, app, produced + 1, rng)
        produced += 1
        if produced % 5000 == 0:
            conn.commit()
            print(f"  {produced}/{args.count} applications")

    conn.execute(
        """INSERT INTO generation_metadata (n_applications, seed, default_intensity,
                                            reference_date, formula_version, comment)
           VALUES (?,?,?,?,?,?)""",
        (produced, args.seed, args.default_intensity, TODAY.isoformat(), FORMULA_VERSION,
         "realistic default rate" if args.default_intensity == 0
         else f"defaults over-sampled (intensity {args.default_intensity}): RECALIBRATE"))
    conn.commit()

    print(f"\n{produced} applications inserted ({rejected} draws rejected as incoherent)")
    for row in conn.execute("SELECT * FROM v_class_balance"):
        print("  ", dict(row))
    conn.close()


if __name__ == "__main__":
    main()
