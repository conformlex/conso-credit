#!/usr/bin/env python3
"""Export the dataset to training-ready CSV files.

    python3 export_dataset.py [--out export/]

The export is **driven by `variable_dictionary`**, never by `SELECT *`. That is
the mechanism which stops `risk_score` or `approved_amount` from becoming a model
input by accident. Any v_dataset column missing from the dictionary fails the
export rather than silently entering X.

Produces, per split (`train` / `val` / `test`):
  X_<split>.csv          columns with role `feature`
  y_<split>.csv          columns with role `target`
  protected_<split>.csv  columns with role `protected`, for bias auditing
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from creditrisk import db

KEY = "application_reference"  # present in every file so X, y and protected can be rejoined


class InconsistentExport(RuntimeError):
    pass


def _view_columns(conn) -> list[str]:
    return [r["name"] for r in conn.execute("PRAGMA table_info(v_dataset)")]


def _dictionary(conn) -> dict[str, str]:
    return {r["column_name"]: r["role"]
            for r in conn.execute("SELECT column_name, role FROM variable_dictionary")}


def export(out: Path) -> None:
    conn = db.connect()
    columns = _view_columns(conn)
    dictionary = _dictionary(conn)

    orphans = [c for c in columns if c not in dictionary]
    if orphans:
        raise InconsistentExport(
            "v_dataset columns missing from the dictionary: " + ", ".join(orphans)
            + "\nDeclare them in variable_dictionary before exporting.")
    stale = [c for c in dictionary if c not in columns]
    if stale:
        raise InconsistentExport(
            "dictionary entries with no matching column: " + ", ".join(stale))

    by_role = {role: [c for c in columns if dictionary[c] == role]
               for role in ("feature", "target", "protected")}

    out.mkdir(parents=True, exist_ok=True)
    summary: list[tuple] = []

    for split in ("train", "val", "test"):
        rows = conn.execute(
            "SELECT * FROM v_dataset WHERE split = ? ORDER BY application_id",
            (split,)).fetchall()
        for role, prefix in (("feature", "X"), ("target", "y"), ("protected", "protected")):
            fields = [KEY] + [c for c in by_role[role] if c != KEY]
            path = out / f"{prefix}_{split}.csv"
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(fields)
                for row in rows:
                    writer.writerow(["" if row[c] is None else row[c] for c in fields])
            summary.append((path.name, len(rows), len(fields)))

    print(f"Exported to {out}/\n")
    print(f"{'file':<26} {'rows':>7} {'columns':>9}")
    for name, n, c in summary:
        print(f"{name:<26} {n:>7} {c:>9}")

    print("\nReminder: `default_flag` is NULL on applications that were not approved,")
    print("and on loans still running. Do not impute 0 — that is the selection bias")
    print("and the right-censoring problem of credit scoring, in one column.")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("export"))
    export(parser.parse_args().out)
