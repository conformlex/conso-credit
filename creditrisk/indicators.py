"""Affordability indicators for a consumer-credit application.

These values are never captured by hand: they follow from the income, expense
and existing-loan lines. They are stored frozen in the `indicators` table with a
`formula_version`, so that changing a formula does not make earlier rows
uninterpretable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

FORMULA_VERSION = "v1"

# Cap set by the Haut Conseil de stabilité financière, the French
# macroprudential authority. Applies to the post-loan debt-to-income ratio.
HCSF_THRESHOLD_PCT = 35.0


def monthly_payment(principal: float, annual_rate_pct: float, term_months: int) -> float:
    """Instalment of an amortising loan with level payments."""
    if term_months <= 0:
        raise ValueError("term_months must be strictly positive")
    if principal <= 0:
        raise ValueError("principal must be strictly positive")
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return round(principal / term_months, 2)
    return round(principal * r / (1 - (1 + r) ** -term_months), 2)


def consumption_units(household_size: int, dependent_children: int,
                      children_under_14: int) -> float:
    """Modified OECD equivalence scale.

    1 for the first adult, 0.5 per further person aged 14 or over, 0.3 per child
    under 14. This is the only way to make residual income comparable between a
    single person and a family of five.
    """
    adults = household_size - dependent_children
    children_14_plus = dependent_children - children_under_14
    return round(1 + 0.5 * (adults - 1) + 0.5 * children_14_plus + 0.3 * children_under_14, 2)


@dataclass
class Indicators:
    gross_income: float
    weighted_income: float
    variable_income_share: float
    counted_expenses: float
    existing_payments: float
    retained_payments: float
    dti_before_pct: float
    dti_after_pct: float
    above_hcsf_threshold: int
    consumption_units: float
    residual_income: float
    residual_income_per_cu: float
    payment_shock: float
    savings_months_of_expenses: float
    formula_version: str = FORMULA_VERSION

    def as_dict(self) -> dict:
        return asdict(self)


def compute(
    *,
    incomes: list[dict],
    expenses: list[dict],
    loans: list[dict],
    household: dict,
    monthly_payment_total: float,
    liquid_savings: float,
) -> Indicators:
    """Compute the indicators from the application's elementary lines.

    `incomes`   : {monthly_amount, weighting, variability}
    `expenses`  : {monthly_amount, counted_in_dti}
    `loans`     : {monthly_payment, repaid_by_this_loan}
    `household` : {household_size, dependent_children, children_under_14}
    """
    gross = sum(i["monthly_amount"] for i in incomes)
    weighted = sum(i["monthly_amount"] * i["weighting"] for i in incomes)
    variable = sum(i["monthly_amount"] for i in incomes if i["variability"] == "variable")

    counted_expenses = sum(e["monthly_amount"] for e in expenses if e["counted_in_dti"])

    existing_payments = sum(loan["monthly_payment"] for loan in loans)
    # Loans refinanced by this operation drop out of the future burden; without
    # this distinction a debt consolidation always looks unaffordable.
    refinanced = sum(loan["monthly_payment"] for loan in loans if loan["repaid_by_this_loan"])
    retained_payments = existing_payments - refinanced

    if weighted <= 0:
        raise ValueError("weighted income is zero: the application cannot be assessed")

    dti_before = (existing_payments + counted_expenses) / weighted * 100
    dti_after = (retained_payments + monthly_payment_total + counted_expenses) / weighted * 100

    cu = consumption_units(
        household["household_size"],
        household["dependent_children"],
        household["children_under_14"],
    )
    residual = weighted - counted_expenses - retained_payments - monthly_payment_total
    expenses_after = counted_expenses + retained_payments + monthly_payment_total

    return Indicators(
        gross_income=round(gross, 2),
        weighted_income=round(weighted, 2),
        variable_income_share=round(variable / gross, 4) if gross else 0.0,
        counted_expenses=round(counted_expenses, 2),
        existing_payments=round(existing_payments, 2),
        retained_payments=round(retained_payments, 2),
        dti_before_pct=round(dti_before, 2),
        dti_after_pct=round(dti_after, 2),
        above_hcsf_threshold=int(dti_after > HCSF_THRESHOLD_PCT),
        consumption_units=cu,
        residual_income=round(residual, 2),
        residual_income_per_cu=round(residual / cu, 2),
        payment_shock=round(monthly_payment_total - refinanced, 2),
        savings_months_of_expenses=round(liquid_savings / expenses_after, 2)
        if expenses_after > 0 else 0.0,
    )
