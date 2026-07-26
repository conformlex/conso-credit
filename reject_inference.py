#!/usr/bin/env python3
"""Selection bias: what it costs, and what reject inference recovers.

    python3 export_dataset.py && python3 reject_inference.py

A default model only ever learns from **approved** applications: a lender never
finds out how the ones it declined would have behaved. The model therefore learns
on a truncated population, and is then asked to score the whole population that
walks through the door. That is selection bias.

Because this data is **synthetic**, the counterfactual exists: the generator
knows what would have happened to the declined applications. That makes three
things possible which production never allows:

1. measure the gap between the real model and an "oracle" trained on the whole
   population;
2. test reject inference against ground truth;
3. decide whether the technique is worth deploying at all.

Nothing that uses `counterfactual_default_flag` is reproducible in production.
It is a measuring instrument, not a shippable model.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from creditrisk.evaluation import metrics, score_bands
from creditrisk.features import SCORECARD_VARIABLES, preprocessor

EXPORT = Path("export")
KEY = "application_reference"


def load(split: str) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Whole population: approved (real outcome) + declined (counterfactual)."""
    X = pd.read_csv(EXPORT / f"X_{split}.csv")
    y = pd.read_csv(EXPORT / f"y_{split}.csv")[
        [KEY, "default_flag", "counterfactual_default_flag", "decision_result"]]
    d = X.merge(y, on=KEY)

    approved = d.decision_result.isin(["approved", "approved_with_conditions"])
    target = np.where(approved, d.default_flag, d.counterfactual_default_flag)
    d["target"] = target
    d["approved"] = approved
    d = d[d.target.notna()]        # censoring stays excluded on both sides

    columns = [c for c in SCORECARD_VARIABLES if c in d.columns]
    return d[columns], d.target.astype(int), d.approved


def fit(X, y, weights=None):
    pipe = Pipeline([("pre", preprocessor(X)),
                     ("clf", LogisticRegression(max_iter=3000, C=0.5))])
    return pipe.fit(X, y, clf__sample_weight=weights) if weights is not None else pipe.fit(X, y)


def fuzzy_augmentation(Xtr, ytr, approved_tr):
    """Fuzzy augmentation — the classic reject-inference technique.

    Each declined application is fed back **twice**: once as a good payer with
    weight `1 - p`, once as a defaulter with weight `p`, where `p` comes from a
    first model fitted on approved files only. No label is invented: the file is
    split between the two outcomes in proportion to its estimated risk.

    The structural weakness: `p` comes from a model that has never seen a
    declined application. The technique extrapolates, it discovers nothing.
    """
    base = fit(Xtr[approved_tr], ytr[approved_tr])
    p_declined = base.predict_proba(Xtr[~approved_tr])[:, 1]

    X_aug = pd.concat([Xtr[approved_tr], Xtr[~approved_tr], Xtr[~approved_tr]],
                      ignore_index=True)
    y_aug = np.concatenate([ytr[approved_tr].values,
                            np.ones(len(p_declined)), np.zeros(len(p_declined))])
    w_aug = np.concatenate([np.ones(approved_tr.sum()), p_declined, 1 - p_declined])
    return fit(X_aug, y_aug, w_aug)


def main() -> None:
    Xtr, ytr, approved_tr = load("train")
    Xte, yte, approved_te = load("test")

    print("=" * 76)
    print("SELECTION BIAS — measured against counterfactual ground truth")
    print("=" * 76)
    print(f"Training : {approved_tr.sum():>6} approved ({ytr[approved_tr].mean():.1%} default)"
          f" | {(~approved_tr).sum():>6} declined "
          f"({ytr[~approved_tr].mean():.1%} counterfactual)")
    print(f"Test     : {len(Xte):>6} applications, whole population "
          f"({yte.mean():.1%} default)\n")

    models = {
        "real (approved only)": fit(Xtr[approved_tr], ytr[approved_tr]),
        "reject inference": fuzzy_augmentation(Xtr, ytr, approved_tr),
        "oracle (whole population)": fit(Xtr, ytr),
    }

    print("Evaluated on the WHOLE test population — the one that actually walks")
    print("through the door, declined applications included:\n")
    print(f"{'model':<28}{'AUC':>8}{'Gini':>8}{'KS':>8}{'Brier':>10}{'mean PD':>10}")
    scores = {}
    for name, m in models.items():
        p = m.predict_proba(Xte)[:, 1]
        scores[name] = (p, metrics(yte, p))
        s = scores[name][1]
        print(f"{name:<28}{s['auc']:>8.4f}{s['gini']:>8.4f}{s['ks']:>8.4f}"
              f"{s['brier']:>10.5f}{p.mean():>10.4f}")
    print(f"{'actual default rate':<28}{'':>34}{yte.mean():>10.4f}")

    auc_real = scores["real (approved only)"][1]["auc"]
    auc_ri = scores["reject inference"][1]["auc"]
    auc_oracle = scores["oracle (whole population)"][1]["auc"]
    gap = auc_oracle - auc_real
    recovered = (auc_ri - auc_real) / gap if abs(gap) > 1e-9 else 0.0

    print(f"\nCost of selection bias: {gap:+.4f} AUC")
    print(f"Recovered by reject inference: {recovered:.0%} of that gap")

    print("\nRisk understatement on DECLINED applications:")
    print(f"{'model':<28}{'mean PD':>10}{'actual':>10}{'gap':>10}")
    actual_declined = yte[~approved_te].mean()
    for name, (p, _) in scores.items():
        mean_pd = p[~approved_te.values].mean()
        print(f"{name:<28}{mean_pd:>10.4f}{actual_declined:>10.4f}"
              f"{mean_pd - actual_declined:>+10.4f}")

    print("\nCalibration on the whole population — mean PD/observed gap:")
    for name, (p, _) in scores.items():
        print(f"  {name:<28}{score_bands(yte, p).gap.mean():.4f}")

    print("\n" + "-" * 76)
    print("Reading: the real model systematically understates the risk of files it")
    print("has never seen — it only ever learnt on an already-filtered population.")
    print("Reject inference recovers part of that without ever closing the gap,")
    print("because it extrapolates from that very model. The only remedy that")
    print("genuinely adds information is approving a random sample of borderline")
    print("applications and observing what happens.")


if __name__ == "__main__":
    if not (EXPORT / "y_train.csv").exists():
        raise SystemExit("Run python3 export_dataset.py first")
    main()
