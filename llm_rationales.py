#!/usr/bin/env python3
"""LLM-written decision rationales.

    python3 llm_rationales.py export [--batches 8] [--per-batch 25]
    python3 llm_rationales.py load

`export` picks a stratified subset of applications and writes one JSON file per
batch, to hand to a language model. `load` reads the returned files back and
updates the database, flipping `decided_by` to `llm` — a training set where you
no longer know who wrote what cannot be audited.

The rationale text itself is **French**: it is a French credit decision letter.
Only the tooling around it is English.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from creditrisk import db

BATCH_DIR = Path(__file__).resolve().parent / "rationales"

CONTRACT_FR = {
    "PERMANENT": "CDI", "FIXED_TERM": "CDD", "TEMP_AGENCY": "interim",
    "CIVIL_SERVANT": "fonctionnaire", "SELF_EMPLOYED": "independant",
    "RETIRED": "retraite", "APPRENTICE": "apprenti", "UNEMPLOYED": "sans emploi",
}


def _summary(row, reasons: list[dict]) -> dict:
    """Readable summary of an application, designed to be written from."""
    return {
        "reference": row["application_reference"],
        "operation": {
            "loan_type": row["loan_type"],
            "requested_amount_eur": row["requested_amount"],
            "term_months": row["term_months"],
            "apr_pct": row["apr"],
            "monthly_payment_eur": row["monthly_payment"],
            "down_payment_eur": row["down_payment"],
            "channel": row["channel"],
        },
        "borrower": {
            "contract_fr": CONTRACT_FR.get(row["contract_type"], row["contract_type"]),
            "months_in_job": row["months_in_job"],
            "in_probation_period": bool(row["in_probation_period"]),
            "occupation": row["occupation"],
            "has_co_borrower": bool(row["has_co_borrower"]),
            "household_size": row["household_size"],
            "dependent_children": row["dependent_children"],
            "housing_status": row["housing_status"],
            "relationship_months": row["relationship_months"],
        },
        "financials": {
            "weighted_income_eur": row["weighted_income"],
            "counted_expenses_eur": row["counted_expenses"],
            "existing_loans": row["existing_loans"],
            "existing_loan_payments_eur": row["existing_loan_payments"],
            "dti_before_pct": row["dti_before_pct"],
            "dti_after_pct": row["dti_after_pct"],
            "residual_income_per_cu_eur": row["residual_income_per_cu"],
            "liquid_savings_eur": row["liquid_savings"],
            "savings_months_of_expenses": row["savings_months_of_expenses"],
        },
        "behaviour": {
            "days_overdrawn_12m": row["days_overdrawn_12m"],
            "rejected_debits_12m": row["rejected_debits_12m"],
            "ficp_flagged": bool(row["ficp_flagged"]),
            "fcc_flagged": bool(row["fcc_flagged"]),
            "loans_repaid_clean": row["loans_repaid_clean"],
            "salary_domiciled": bool(row["salary_domiciled"]),
        },
        "decision": {
            "result": row["decision_result"],
            "approved_amount_eur": row["approved_amount"],
            "approved_term_months": row["approved_term_months"],
            "conditions": row["conditions"],
            "risk_grade": row["risk_grade"],
        },
        "reasons": reasons,
    }


def export(batches: int, per_batch: int) -> None:
    conn = db.connect()
    needed = batches * per_batch

    # Stratify: every stratum must be represented, otherwise the rare cases
    # (overrides, incident flags, precarious contracts) vanish from the set that
    # gets hand-written prose.
    strata = {
        "declined":            "decision_result = 'declined'",
        "approved":            "decision_result = 'approved'",
        "conditional":         "decision_result = 'approved_with_conditions'",
        "deferred":            "decision_result = 'deferred'",
        "override":            "reasons LIKE '%OVERRIDE%'",
        "ficp":                "ficp_flagged = 1",
        "precarious_contract": "contract_stability = 'precarious'",
        "above_hcsf_approved": "above_hcsf_threshold = 1 AND decision_result LIKE 'approved%'",
        "observed_default":    "default_flag = 1",
        "consolidation":       "loan_type = 'DEBT_CONSOLIDATION'",
    }
    quota = max(4, needed // len(strata))

    seen: set[str] = set()
    summaries: list[dict] = []
    for name, predicate in strata.items():
        rows = conn.execute(
            f"SELECT * FROM v_dataset WHERE {predicate} ORDER BY application_id LIMIT ?",
            (quota * 3,)).fetchall()
        taken = 0
        for row in rows:
            if row["application_reference"] in seen or taken >= quota:
                continue
            reasons = conn.execute(
                """SELECT r.code, r.label, r.polarity FROM decision_reason dr
                   JOIN reason r ON r.code = dr.reason_code WHERE dr.application_id = ?""",
                (row["application_id"],)).fetchall()
            summary = _summary(row, [dict(r) for r in reasons])
            summary["_stratum"] = name
            summaries.append(summary)
            seen.add(row["application_reference"])
            taken += 1

    # Shuffle: without it each batch is homogeneous (25 declines in a row), which
    # pushes the writer to repeat itself from one file to the next.
    random.Random(4242).shuffle(summaries)

    BATCH_DIR.mkdir(exist_ok=True)
    for i in range(batches):
        batch = summaries[i * per_batch:(i + 1) * per_batch]
        if not batch:
            break
        (BATCH_DIR / f"batch_{i + 1:02d}_in.json").write_text(
            json.dumps(batch, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"batch_{i + 1:02d}_in.json : {len(batch)} applications")
    conn.close()


# A rationale that announces the opposite of the decision it explains poisons the
# training set: the model would learn to pair a decline reason with an approval.
CONTRADICTIONS = {
    "declined": ("accord.", "accord,", "nous donnons une suite favorable",
                 "position favorable", "avis favorable", "demande acceptée"),
    "deferred": ("accord.", "refus.", "nous refusons"),
    "approved": ("refus.", "nous ne pouvons pas donner suite", "position défavorable",
                 "avis défavorable", "demande rejetée"),
    "approved_with_conditions": ("refus.", "nous ne pouvons pas donner suite",
                                 "position défavorable", "demande rejetée"),
}


def _contradicts(text: str, result: str) -> bool:
    opening = text[:160].lower()
    return any(marker in opening for marker in CONTRADICTIONS.get(result, ()))


def load() -> None:
    conn = db.connect()
    loaded = short = contradictory = unknown = stale = 0
    for path in sorted(BATCH_DIR.glob("batch_*_out.json")):
        # Guard: an output older than its input was written for an earlier
        # generation. References (APP-YYYY-NNNNNN) are reassigned on every
        # rebuild, so loading a stale file would silently attach rationales to
        # the wrong applications.
        source = path.with_name(path.name.replace("_out", "_in"))
        if source.exists() and path.stat().st_mtime < source.stat().st_mtime:
            stale += 1
            continue

        for item in json.loads(path.read_text(encoding="utf-8")):
            text = (item.get("rationale") or "").strip()
            row = conn.execute(
                """SELECT a.id, d.result FROM application a
                   JOIN decision d ON d.application_id = a.id WHERE a.reference = ?""",
                (item.get("reference"),)).fetchone()
            if row is None:
                unknown += 1
                continue
            if len(text) < 100:
                short += 1
                continue
            if _contradicts(text, row["result"]):
                contradictory += 1
                continue
            conn.execute(
                "UPDATE decision SET rationale = ?, decided_by = 'llm' WHERE application_id = ?",
                (text, row["id"]))
            loaded += 1
    conn.commit()
    print(f"{loaded} rationales loaded ({short} too short, "
          f"{contradictory} contradicting the decision, {unknown} unknown references, "
          f"{stale} stale files skipped)")
    for row in conn.execute(
            "SELECT decided_by, COUNT(*) n, ROUND(AVG(LENGTH(rationale))) mean_length "
            "FROM decision GROUP BY decided_by"):
        print("  ", dict(row))
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    e = sub.add_parser("export")
    e.add_argument("--batches", type=int, default=8)
    e.add_argument("--per-batch", type=int, default=25)
    sub.add_parser("load")
    args = parser.parse_args()
    if args.action == "export":
        export(args.batches, args.per_batch)
    else:
        load()
