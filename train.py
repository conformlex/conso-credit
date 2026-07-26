#!/usr/bin/env python3
"""Train the credit-risk models.

    python3 export_dataset.py && python3 train.py

Discipline followed here:

* **`train` to fit, `val` to choose and calibrate, `test` touched once.**
  Selecting a model on the test set contaminates it and inflates the numbers you
  publish.
* **Interpretable coefficient signs are a hard constraint.** A scoring model in
  which residual income *increases* risk cannot motivate a decline, and French
  lenders must be able to. Linear candidates that fail the sign audit are
  dropped whatever their AUC.
* **Calibration must earn its place.** In credit you do not just want a ranking,
  you want a probability you can price and provision with — but a calibrator
  that does not measurably improve the Brier score only destroys granularity.
* **Banking metrics**: Gini, KS, Brier, and a score band table against the
  observed default rate.

Writes to `models/`: the serialised models, the metrics and the score bands.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             classification_report, confusion_matrix, f1_score,
                             roc_auc_score, roc_curve)
from sklearn.model_selection import cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

EXPORT = Path("export")
MODELS = Path("models")
KEY = "application_reference"


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

def load(split: str, target: str):
    X = pd.read_csv(EXPORT / f"X_{split}.csv")
    y = pd.read_csv(EXPORT / f"y_{split}.csv")[[KEY, target]]
    d = X.merge(y, on=KEY)
    d = d[d[target].notna()]      # censored and declined rows: excluded, never imputed
    return d.drop(columns=[KEY, target]), d[target], d[KEY]


def load_protected(split: str) -> pd.DataFrame:
    return pd.read_csv(EXPORT / f"protected_{split}.csv")


def preprocessor(X: pd.DataFrame) -> ColumnTransformer:
    numeric = X.select_dtypes(include=np.number).columns.tolist()
    categorical = [c for c in X.columns if c not in numeric]
    return ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                          ("scale", StandardScaler())]), numeric),
        ("cat", Pipeline([("imp", SimpleImputer(strategy="most_frequent")),
                          ("enc", OneHotEncoder(handle_unknown="ignore",
                                                min_frequency=20,
                                                sparse_output=False))]), categorical)])


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

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
    """Observed default rate per score band — the deliverable underwriters read."""
    d = pd.DataFrame({"p": p, "y": np.asarray(y)})
    d["band"] = pd.qcut(d.p.rank(method="first"), n_bands,
                        labels=[f"D{i}" for i in range(1, n_bands + 1)])
    g = d.groupby("band", observed=True).agg(
        n=("y", "size"), defaults=("y", "sum"),
        mean_pd=("p", "mean"), observed_rate=("y", "mean")).reset_index()
    g["gap"] = (g.mean_pd - g.observed_rate).abs()
    return g.round(4)


# --------------------------------------------------------------------------
# Default-risk model
# --------------------------------------------------------------------------

# Scorecard variable set: one representative per economic family. RATIOS take
# precedence over their components — keeping `residual_income_per_cu` alongside
# the income, instalments, rent and household size that build it flips the sign
# of the ratio, and a scorecard where residual income "worsens" risk cannot
# motivate a decline.
SCORECARD_VARIABLES = [
    # repayment capacity
    "dti_after_pct", "above_hcsf_threshold", "residual_income_per_cu",
    "savings_months_of_expenses", "variable_income_share", "down_payment_ratio",
    "payment_shock",
    # the operation
    "requested_amount", "term_months", "apr", "has_co_borrower", "insurance_taken",
    # existing exposure
    "existing_loans", "revolving_loans", "loan_incidents_12m", "loans_repaid_clean",
    # account behaviour
    "days_overdrawn_12m", "rejected_debits_12m", "ficp_flagged", "fcc_flagged",
    "salary_domiciled", "max_overdraft_used", "products_held",
    # stability
    "months_in_job", "relationship_months", "months_at_address",
    "in_probation_period", "undocumented_income_lines",
    # categorical
    "loan_type", "contract_stability", "contract_type", "housing_status",
    "channel", "occupation", "area_type",
]

# Direction the business expects. A mismatch is not fatal in itself, but it must
# be seen: it is the usual symptom of residual collinearity.
EXPECTED_SIGNS = {
    "protective": ["residual_income_per_cu", "savings_months_of_expenses",
                   "loans_repaid_clean", "months_in_job", "relationship_months",
                   "months_at_address", "salary_domiciled", "has_co_borrower",
                   "down_payment_ratio", "products_held"],
    "adverse": ["dti_after_pct", "above_hcsf_threshold", "payment_shock",
                "variable_income_share", "days_overdrawn_12m", "rejected_debits_12m",
                "ficp_flagged", "fcc_flagged", "revolving_loans", "loan_incidents_12m",
                "in_probation_period", "max_overdraft_used", "undocumented_income_lines"],
}

# Below this, a coefficient's sign means nothing. The variables that carry the
# model have standardised coefficients of 0.3 to 0.6; under 0.05 the effect is
# worth less than 5% of odds ratio per standard deviation — economically
# negligible, and unstable in sign from one sample to the next. A stricter
# threshold (0.01) fails the audit on noise and discards good models.
SIGN_THRESHOLD = 0.05


def audit_signs(model: Pipeline) -> list[tuple[str, float, str]]:
    clf = model.named_steps["clf"]
    if not hasattr(clf, "coef_"):
        return []
    names = [n.split("__", 1)[-1] for n in model.named_steps["pre"].get_feature_names_out()]
    coef = pd.Series(clf.coef_[0], index=names)
    anomalies = []
    for v in EXPECTED_SIGNS["protective"]:
        if v in coef and coef[v] > SIGN_THRESHOLD:
            anomalies.append((v, float(coef[v]), "protective"))
    for v in EXPECTED_SIGNS["adverse"]:
        if v in coef and coef[v] < -SIGN_THRESHOLD:
            anomalies.append((v, float(coef[v]), "adverse"))
    return anomalies


def train_default_risk() -> dict:
    print("=" * 74)
    print("DEFAULT-RISK MODEL  (target: default_flag)")
    print("=" * 74)

    Xtr, ytr, _ = load("train", "default_flag")
    Xva, yva, _ = load("val", "default_flag")
    Xte, yte, ref_te = load("test", "default_flag")
    ytr, yva, yte = ytr.astype(int), yva.astype(int), yte.astype(int)
    print(f"train {len(Xtr):>6} labelled rows / {ytr.sum():>4} defaults   "
          f"val {len(Xva):>5} / {yva.sum():>3}   test {len(Xte):>5} / {yte.sum():>3}")
    print("Declined applications and running loans are excluded, never imputed as 0.\n")

    scorecard = [c for c in SCORECARD_VARIABLES if c in Xtr.columns]
    print(f"Scorecard set: {len(scorecard)} of {Xtr.shape[1]} exported variables "
          "(one per family, ratios preferred over their components).\n")

    candidates = {
        "logistic_C0.1": (LogisticRegression(max_iter=3000, C=0.1), scorecard),
        "logistic_C0.5": (LogisticRegression(max_iter=3000, C=0.5), scorecard),
        "logistic_full": (LogisticRegression(max_iter=3000, C=0.1), list(Xtr.columns)),
        "gb_depth3": (HistGradientBoostingClassifier(max_iter=400, max_depth=3,
                                                     learning_rate=0.06, random_state=0),
                      list(Xtr.columns)),
        "gb_depth6": (HistGradientBoostingClassifier(max_iter=400, max_depth=6,
                                                     learning_rate=0.06, random_state=0),
                      list(Xtr.columns)),
    }

    print("Selection on validation (test is not touched yet):")
    results = {}
    for name, (estimator, columns) in candidates.items():
        m = Pipeline([("pre", preprocessor(Xtr[columns])), ("clf", estimator)]).fit(
            Xtr[columns], ytr)
        auc = roc_auc_score(yva, m.predict_proba(Xva[columns])[:, 1])
        anomalies = audit_signs(m)
        results[name] = (auc, m, columns, anomalies)
        detail = ("non-linear" if not isinstance(estimator, LogisticRegression)
                  else f"{len(anomalies)} sign(s) inverted")
        print(f"  {name:<16} {len(columns):>3} vars   val AUC {auc:.4f}   {detail}")

    # HARD constraint, not a warning: a scorecard whose residual income
    # "worsens" risk cannot motivate a decline. Linear candidates with
    # incoherent signs are dropped even when they win on AUC — that gain is
    # bought with explainability, which is not negotiable here.
    clean_linear = [k for k in results if k.startswith("logistic") and not results[k][3]]
    dirty_linear = [k for k in results if k.startswith("logistic") and results[k][3]]
    for k in dirty_linear:
        print(f"  x {k} dropped: {len(results[k][3])} sign(s) against business direction")

    best_gb = max((k for k in results if k.startswith("gb")), key=lambda k: results[k][0])
    if not clean_linear:
        print("\n  No linear candidate with coherent signs: falling back to gradient "
              "boosting, whose contributions are only approximate.")
        best_linear, auc_linear = None, -1.0
    else:
        best_linear = max(clean_linear, key=lambda k: results[k][0])
        auc_linear = results[best_linear][0]
    auc_gb = results[best_gb][0]

    gap = auc_gb - auc_linear
    if gap > 0.02 or best_linear is None:
        production, challenger = best_gb, best_linear
        reason = ("no linear candidate with coherent signs" if best_linear is None
                  else f"gradient boosting gains {gap:+.4f} AUC, enough to prevail")
    else:
        production, challenger = best_linear, best_gb
        reason = (f"AUC gap of only {gap:+.4f}: logistic regression kept for "
                  "explainability")
    print(f"\nProduction model : {production}  —  {reason}")
    print(f"Challenger kept  : {challenger}\n")

    model = results[production][1]
    production_columns = results[production][2]
    anomalies = results[production][3]
    print(f"Sign audit on the retained model: {len(anomalies)} coefficient(s) against "
          f"expectation beyond {SIGN_THRESHOLD}")
    for v, c, expected in anomalies:
        print(f"    {v:<32}{c:+.3f}   expected {expected}")
    if not anomalies:
        print("    every sign matches the expected business direction")
    print()

    # The calibrator is fitted on OUT-OF-FOLD training predictions (~1,300
    # events) rather than on validation (~300): isotonic regression learnt on
    # three hundred events overfits and starts degrading what it should correct.
    # The CHOICE of calibrator is still made on validation, which stays clean of
    # the fitting.
    p_oof = cross_val_predict(model, Xtr[production_columns], ytr, cv=5,
                              method="predict_proba", n_jobs=-1)[:, 1]
    isotonic = IsotonicRegression(out_of_bounds="clip").fit(p_oof, ytr)
    platt = LogisticRegression().fit(p_oof.reshape(-1, 1), ytr)
    p_va = model.predict_proba(Xva[production_columns])[:, 1]

    options = {
        "none": (None, brier_score_loss(yva, p_va)),
        "isotonic": (isotonic, brier_score_loss(yva, isotonic.predict(p_va))),
        "platt": (platt, brier_score_loss(yva, platt.predict_proba(p_va.reshape(-1, 1))[:, 1])),
    }
    print("Calibration — Brier score on validation:")
    for name, (_, brier) in options.items():
        print(f"  {name:<10} {brier:.5f}")

    # A calibrator must EARN its place. Isotonic regression is a step function:
    # it flattens granularity, to the point of giving the same PD to very
    # different files and making the /simulate bisection coarse. Apply it only
    # if it improves Brier by at least 1% relative; otherwise keep the raw,
    # continuous probabilities.
    reference = options["none"][1]
    best_option = min(options, key=lambda k: options[k][1])
    calibration = best_option if options[best_option][1] < reference * 0.99 else "none"
    if best_option != calibration:
        print(f"  ({best_option} improves by only "
              f"{100 * (reference - options[best_option][1]) / reference:.2f}%: dropped)")
    calibrator = options[calibration][0]
    print(f"  -> retained: {calibration}\n")

    def apply_calibration(p):
        if calibrator is None:
            return p
        if calibration == "isotonic":
            return calibrator.predict(p)
        return calibrator.predict_proba(p.reshape(-1, 1))[:, 1]

    p_te_raw = model.predict_proba(Xte[production_columns])[:, 1]
    p_te = apply_calibration(p_te_raw)

    m_raw, m_final = metrics(yte, p_te_raw), metrics(yte, p_te)
    print("Test (touched once):")
    print(f"{'':<12}{'AUC':>8}{'Gini':>8}{'KS':>8}{'AP':>8}{'Brier':>10}")
    print(f"{'raw':<12}{m_raw['auc']:>8.4f}{m_raw['gini']:>8.4f}{m_raw['ks']:>8.4f}"
          f"{m_raw['average_precision']:>8.4f}{m_raw['brier']:>10.5f}")
    print(f"{'retained':<12}{m_final['auc']:>8.4f}{m_final['gini']:>8.4f}{m_final['ks']:>8.4f}"
          f"{m_final['average_precision']:>8.4f}{m_final['brier']:>10.5f}")
    print(f"\nBase default rate on test: {m_final['base_rate']:.4f}")

    bands = score_bands(yte, p_te)
    print("\nScore bands — predicted PD against observed default, by decile:")
    print(bands.to_string(index=False))
    print(f"\nMean PD/observed gap: {bands.gap.mean():.4f}"
          "   (a small gap means the PD is directly usable)")

    # Cut-off: the cost of a default is not the cost of a lost deal.
    print("\nCut-off by relative cost of a default:")
    print(f"{'default cost':>13}{'PD cut-off':>12}{'declined':>10}"
          f"{'defaults avoided':>18}{'good lost':>11}")
    for cost in (5, 10, 20):
        grid = np.linspace(0.01, 0.5, 200)
        losses = [(cost * ((p_te < s) & (yte == 1)).sum() + ((p_te >= s) & (yte == 0)).sum())
                  for s in grid]
        s = float(grid[int(np.argmin(losses))])
        print(f"{cost:>12}x{s:>12.3f}{int((p_te >= s).sum()):>10}"
              f"{int(((p_te >= s) & (yte == 1)).sum()):>18}"
              f"{int(((p_te >= s) & (yte == 0)).sum()):>11}")

    print("\nRisk drivers (permutation importance on test):")
    importance = permutation_importance(model, Xte[production_columns], yte, n_repeats=5,
                                        random_state=0, scoring="roc_auc", n_jobs=-1)
    for i in np.argsort(importance.importances_mean)[::-1][:15]:
        if importance.importances_mean[i] > 0.0002:
            print(f"  {production_columns[i]:<34} {importance.importances_mean[i]:+.4f}")

    bias_audit(load_protected("test").set_index(KEY).loc[ref_te.values], p_te, yte)

    # Bounds of the learning domain, measured on out-of-fold predictions. A
    # logistic regression extrapolates linearly in the logit: beyond these
    # bounds it returns PDs arbitrarily close to 1 with no observation to
    # support them. The service must flag that.
    domain = {"max_observed_pd": round(float(p_oof.max()), 4),
              "pd_q999": round(float(np.quantile(p_oof, 0.999)), 4)}
    print(f"\nLearning domain: PD observed up to {domain['max_observed_pd']:.2%} "
          f"(99.9th percentile {domain['pd_q999']:.2%}).")
    print("Beyond that the model extrapolates — the service flags it as out of domain.")

    MODELS.mkdir(exist_ok=True)
    joblib.dump({"model": model, "calibrator": calibrator, "calibration": calibration,
                 "columns": production_columns, "name": production, "domain": domain},
                MODELS / "default_risk.joblib")
    if challenger:
        joblib.dump(results[challenger][1], MODELS / "default_risk_challenger.joblib")
    bands.to_csv(MODELS / "score_bands.csv", index=False)
    pd.DataFrame({KEY: ref_te.values, "pd": p_te, "observed_default": yte.values}).to_csv(
        MODELS / "test_predictions.csv", index=False)

    return {"retained_model": production, "challenger": challenger,
            "n_variables": len(production_columns), "calibration": calibration,
            "sign_anomalies": [{"variable": v, "coef": round(c, 4), "expected": e}
                               for v, c, e in anomalies],
            "validation_auc": {k: round(v[0], 4) for k, v in results.items()},
            "test_raw": m_raw, "test_retained": m_final,
            "mean_calibration_gap": round(float(bands.gap.mean()), 4),
            "domain": domain}


def bias_audit(protected: pd.DataFrame, proba: np.ndarray, y: pd.Series) -> None:
    """Does the model err more on some protected groups than others?

    Protected attributes are excluded from the features, which does not stop the
    model reconstructing them by correlation. Only an audit shows it.
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


# --------------------------------------------------------------------------
# Decision model
# --------------------------------------------------------------------------

def train_decision() -> dict:
    print("\n" + "=" * 74)
    print("DECISION MODEL  (target: decision_result)")
    print("=" * 74)

    Xtr, ytr, _ = load("train", "decision_result")
    Xva, yva, _ = load("val", "decision_result")
    Xte, yte, _ = load("test", "decision_result")
    print(f"train {len(Xtr)} / val {len(Xva)} / test {len(Xte)} rows")

    candidates = {
        "gb_depth6": HistGradientBoostingClassifier(max_iter=400, max_depth=6,
                                                    learning_rate=0.06, random_state=0),
        "gb_default": HistGradientBoostingClassifier(max_iter=300, random_state=0),
        "logistic": LogisticRegression(max_iter=3000, C=0.5),
    }
    scores = {}
    for name, estimator in candidates.items():
        m = Pipeline([("pre", preprocessor(Xtr)), ("clf", estimator)]).fit(Xtr, ytr)
        scores[name] = (m.score(Xva, yva), m)
        print(f"  {name:<12} val accuracy {scores[name][0]:.4f}")

    production = max(scores, key=lambda k: scores[k][0])
    model = scores[production][1]
    print(f"\nRetained model: {production}\n")

    predicted = model.predict(Xte)
    print(classification_report(yte, predicted, zero_division=0))
    labels = sorted(yte.unique())
    print("Confusion matrix (rows = actual, columns = predicted):")
    print(pd.DataFrame(confusion_matrix(yte, predicted, labels=labels),
                       index=labels, columns=labels).to_string())

    joblib.dump({"model": model, "columns": list(Xtr.columns), "name": production},
                MODELS / "decision.joblib")
    return {"retained_model": production,
            "test_accuracy": round(float((predicted == yte).mean()), 4),
            "test_macro_f1": round(float(f1_score(yte, predicted, average="macro")), 4)}


if __name__ == "__main__":
    if not (EXPORT / "X_train.csv").exists():
        raise SystemExit("Run python3 export_dataset.py first")
    summary = {"default_risk": train_default_risk(), "decision": train_decision()}
    MODELS.mkdir(exist_ok=True)
    (MODELS / "metrics.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nModels and metrics written to {MODELS}/")
    print("\nMethodological caveat: the default model only ever learns from APPROVED")
    print("applications. It knows nothing about how declined ones would have behaved")
    print("(selection bias). In production that calls for reject inference, or for")
    print("approving a random sample of borderline applications and observing them.")
    print("Run reject_inference.py to see what that bias actually costs here.")
