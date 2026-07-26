"""Feature set and preprocessing for the credit scorecard.

This is domain knowledge, not training plumbing: which variables a scorecard is
allowed to use, and which direction each is expected to push. It lives in the
library so that anything scoring or auditing a model can reach it without
importing a training script.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

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

# Materiality threshold for the sign audit. The variables that carry the model
# have standardised coefficients of 0.3 to 0.6; under 0.05 the effect is worth
# less than 5% of odds ratio per standard deviation — economically negligible,
# and unstable in sign from one sample to the next. Auditing below that level
# reports noise and rejects sound models.
SIGN_THRESHOLD = 0.05


def preprocessor(X: pd.DataFrame) -> ColumnTransformer:
    """Median-impute and scale numerics, one-hot the rest.

    `min_frequency` folds rare categories into an "infrequent" bucket, which
    keeps a department seen twice from becoming its own coefficient.
    """
    numeric = X.select_dtypes(include=np.number).columns.tolist()
    categorical = [c for c in X.columns if c not in numeric]
    return ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                          ("scale", StandardScaler())]), numeric),
        ("cat", Pipeline([("imp", SimpleImputer(strategy="most_frequent")),
                          ("enc", OneHotEncoder(handle_unknown="ignore",
                                                min_frequency=20,
                                                sparse_output=False))]), categorical)])


def audit_signs(model: Pipeline) -> list[tuple[str, float, str]]:
    """Coefficients pointing against the expected business direction.

    Returns an empty list for non-linear models, which have no coefficients to
    audit — and, for the same reason, no exact explanation to offer either.
    """
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
