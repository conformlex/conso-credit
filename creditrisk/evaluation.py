"""Evaluation metrics for a credit scorecard.

Banking metrics rather than generic ML ones: Gini and KS are what a risk
committee reads, and the score band table is the deliverable underwriters
actually use. Kept in the library so that training, reject-inference analysis
and any downstream monitoring all measure the same way.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             roc_auc_score, roc_curve)


def ks_statistic(y, p) -> float:
    """Kolmogorov-Smirnov: largest gap between good and bad payers."""
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def metrics(y, p) -> dict:
    auc = roc_auc_score(y, p)
    return {
        "auc": round(float(auc), 4),
        "gini": round(float(2 * auc - 1), 4),          # banking standard
        "ks": round(ks_statistic(y, p), 4),
        "average_precision": round(float(average_precision_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 5),
        "base_rate": round(float(np.mean(y)), 4),
    }


def score_bands(y, p, n_bands: int = 10) -> pd.DataFrame:
    """Observed default rate per score band.

    `gap` is what makes a probability usable: a model can rank perfectly and
    still predict 25% where the observed rate is 8%, which prices nothing.
    """
    d = pd.DataFrame({"p": p, "y": np.asarray(y)})
    d["band"] = pd.qcut(d.p.rank(method="first"), n_bands,
                        labels=[f"D{i}" for i in range(1, n_bands + 1)])
    g = d.groupby("band", observed=True).agg(
        n=("y", "size"), defaults=("y", "sum"),
        mean_pd=("p", "mean"), observed_rate=("y", "mean")).reset_index()
    g["gap"] = (g.mean_pd - g.observed_rate).abs()
    return g.round(4)


def bias_audit(protected: pd.DataFrame, proba: np.ndarray, y: pd.Series) -> None:
    """Does the model err more on some protected groups than others?

    Protected attributes are excluded from the features, which does not stop the
    model reconstructing them by correlation. Only an audit shows it, and the
    test is comparative: a score gap only means bias when it is *not* backed by
    a matching gap in observed default.
    """
    print("\n  Bias audit — mean score and observed default rate by group")
    print(f"  {'attribute':<20} {'group':<16} {'n':>6} {'mean score':>11} {'observed':>10}")
    for column in protected.columns:
        values = protected[column]
        groups = (pd.qcut(values, 4, duplicates="drop")
                  if pd.api.types.is_numeric_dtype(values) else values)
        for group, idx in pd.Series(range(len(y))).groupby(groups.values):
            if len(idx) < 30:
                continue
            print(f"  {column:<20} {str(group):<16} {len(idx):>6} "
                  f"{proba[idx].mean():>11.3f} {y.iloc[idx].mean():>10.3f}")
    print("\n  A score gap not backed by a gap in observed default is a bias.")
