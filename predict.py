#!/usr/bin/env python3
"""Score an application from the database, with an explanation.

    python3 predict.py APP-2023-000020
    python3 predict.py --sample 3

Returns the probability of default, the risk grade, the predicted decision and
the factors that weighed — in both directions.

The explanation is **exact, not approximate**: the production model is a logistic
regression, so a variable's contribution to the logit is its coefficient times
its standardised value. That is what lets a decline be motivated, which French
lending rules require.
"""

from __future__ import annotations

import argparse
import sqlite3

import joblib
import numpy as np
import pandas as pd

from creditrisk import db

DEFAULT_MODEL = "models/default_risk.joblib"
DECISION_MODEL = "models/decision.joblib"


def _labels(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["column_name"]: r["label"]
            for r in conn.execute("SELECT column_name, label FROM variable_dictionary")}


def _grade(pd_value: float) -> str:
    return ("A" if pd_value < 0.02 else "B" if pd_value < 0.05 else
            "C" if pd_value < 0.10 else "D" if pd_value < 0.20 else "E")


def _contributions(bundle: dict, row: pd.DataFrame) -> pd.Series | None:
    """Per-variable contribution to the logit. None if the model is not linear."""
    pipe = bundle["model"]
    clf = pipe.named_steps["clf"]
    if not hasattr(clf, "coef_"):
        return None
    z = pipe.named_steps["pre"].transform(row)
    names = pipe.named_steps["pre"].get_feature_names_out()
    return pd.Series(clf.coef_[0] * np.asarray(z).ravel(), index=names)


def _pretty(name: str, labels: dict[str, str], row: pd.Series) -> str:
    """Business label, with the application's own value alongside.

    Without the value the explanation reads backwards: a positive contribution on
    "residual income" means that residual income is LOW, not that residual income
    increases risk.
    """
    name = name.split("__", 1)[-1]
    if name in labels:
        value = row.get(name)
        if isinstance(value, (int, float, np.integer, np.floating)):
            value = f"{value:,.2f}".replace(",", " ").rstrip("0").rstrip(".")
        return f"{labels[name]} ({value})"
    for column, label in labels.items():          # one-hot encoded categorical
        if name.startswith(column + "_"):
            return f"{label} = {name[len(column) + 1:]}"
    return name


def evaluate(references: list[str]) -> None:
    bundle = joblib.load(DEFAULT_MODEL)
    decision_bundle = joblib.load(DECISION_MODEL)
    conn = db.connect()
    labels = _labels(conn)

    placeholders = ",".join("?" * len(references))
    rows = pd.read_sql(
        f"SELECT * FROM v_dataset WHERE application_reference IN ({placeholders})",
        conn, params=references)
    if rows.empty:
        raise SystemExit("No application found for those references.")

    for _, row in rows.iterrows():
        X = pd.DataFrame([row])[bundle["columns"]]

        raw = bundle["model"].predict_proba(X)[0, 1]
        calibrator = bundle["calibrator"]
        if calibrator is None:
            proba = raw
        elif bundle["calibration"] == "isotonic":
            proba = float(calibrator.predict(np.array([raw]))[0])
        else:
            proba = float(calibrator.predict_proba(np.array([[raw]]))[0, 1])

        predicted = decision_bundle["model"].predict(
            pd.DataFrame([row])[decision_bundle["columns"]])[0]

        print("=" * 72)
        print(f"{row['application_reference']}   {row['loan_type']}   "
              f"{row['requested_amount']:,.0f} EUR over {row['term_months']} months"
              .replace(",", " "))
        print("-" * 72)
        print(f"Probability of default : {proba:6.2%}   grade {_grade(proba)}")
        print(f"Predicted decision     : {predicted}")
        print(f"Actual decision        : {row['decision_result']}"
              f"   (observed outcome: {row['outcome_status'] or 'not approved'})")

        contributions = _contributions(bundle, X)
        if contributions is not None:
            print("\n  What increases the risk")
            for name, v in contributions.sort_values(ascending=False).head(5).items():
                if v > 0.01:
                    print(f"    {_pretty(name, labels, row):<58} {v:+.3f}")
            print("  What reduces it")
            for name, v in contributions.sort_values().head(5).items():
                if v < -0.01:
                    print(f"    {_pretty(name, labels, row):<58} {v:+.3f}")

        rationale = conn.execute(
            """SELECT d.rationale, d.decided_by FROM decision d
               JOIN application a ON a.id = d.application_id WHERE a.reference = ?""",
            (row["application_reference"],)).fetchone()
        if rationale:
            print(f"\n  Rationale on file ({rationale['decided_by']}), in French:")
            print(f"    {rationale['rationale'][:400]}")
        print()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", nargs="*", help="application references (APP-...)")
    parser.add_argument("--sample", type=int, default=0,
                        help="draw N random applications from the test split")
    args = parser.parse_args()

    refs = list(args.references)
    if args.sample:
        conn = db.connect()
        refs += [r["application_reference"] for r in conn.execute(
            "SELECT application_reference FROM v_dataset WHERE split='test' "
            "AND default_flag IS NOT NULL ORDER BY RANDOM() LIMIT ?", (args.sample,))]
        conn.close()
    if not refs:
        raise SystemExit("Give a reference, or use --sample N")
    evaluate(refs)
