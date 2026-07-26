#!/usr/bin/env python3
"""Consumer-credit risk scoring service.

    uvicorn api:app --port 8000
    open http://localhost:8000/          # bilingual console
    open http://localhost:8000/docs      # generated OpenAPI docs

The service takes a **raw** application — income, expenses, existing loans,
account behaviour — and computes the debt-to-income ratio, residual income and
every other indicator itself, using the very code that produced the training data
(`creditrisk/indicators.py`).

That is deliberate. If the caller computed its own debt-to-income ratio, sooner
or later it would compute it differently from the training set — forgetting the
instalments refinanced by the loan, weighting variable income differently — and
the model would degrade with no alarm going off. One definition, on the service
side.

The service **does not decide**. It returns a probability, a grade and the
factors that weigh. The cut-off is a policy decision, not a property of the
model: it belongs to the calling system.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Literal

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from creditrisk.indicators import HCSF_THRESHOLD_PCT, compute, monthly_payment

MODELS = Path("models")
EXAMPLES = Path("examples")
CONSOLE = Path("console.html")

STABILITY = {
    "PERMANENT": "stable", "CIVIL_SERVANT": "stable", "RETIRED": "stable",
    "FIXED_TERM": "intermediate", "SELF_EMPLOYED": "intermediate",
    "TEMP_AGENCY": "precarious", "APPRENTICE": "precarious", "UNEMPLOYED": "precarious",
}

# --------------------------------------------------------------------------
# Request contract
# --------------------------------------------------------------------------

class Income(BaseModel):
    type: str = Field(examples=["SALARY"])
    monthly_amount: float = Field(gt=0)
    variability: Literal["fixed", "variable"] = "fixed"
    weighting: float = Field(default=1.0, ge=0, le=1)
    documented: bool = True


class Expense(BaseModel):
    type: str = Field(examples=["RENT"])
    monthly_amount: float = Field(gt=0)
    counted_in_dti: bool = True


class ExistingLoan(BaseModel):
    loan_kind: Literal["mortgage", "amortising_consumer", "revolving", "lease", "overdraft"]
    monthly_payment: float = Field(ge=0)
    outstanding_balance: float = Field(ge=0)
    remaining_months: int = Field(ge=0)
    # Refinanced by this operation: its instalment leaves the future burden.
    repaid_by_this_loan: bool = False
    incidents_12m: int = Field(default=0, ge=0)


class Operation(BaseModel):
    loan_type: Literal["PERSONAL_LOAN", "AUTO", "HOME_IMPROVEMENT", "REVOLVING",
                       "DEBT_CONSOLIDATION", "LEASE_TO_OWN"]
    requested_amount: float = Field(gt=0)
    term_months: int = Field(gt=0, le=120)
    nominal_rate: float = Field(ge=0)
    apr: float = Field(ge=0, description="French TAEG")
    usury_rate_cap: float = Field(gt=0, description="legal APR ceiling (taux d'usure)")
    insurance_taken: bool = False
    monthly_insurance_cost: float = Field(default=0.0, ge=0)
    down_payment: float = Field(default=0.0, ge=0)
    channel: Literal["branch", "online", "broker", "point_of_sale"] = "branch"

    @model_validator(mode="after")
    def _usury(self):
        if self.apr > self.usury_rate_cap:
            raise ValueError(
                f"APR {self.apr} above the usury ceiling {self.usury_rate_cap}: "
                "the operation is unlawful and must not be scored")
        return self


class Borrower(BaseModel):
    occupation: str = Field(examples=["CLERICAL"])
    contract_type: Literal["PERMANENT", "FIXED_TERM", "TEMP_AGENCY", "CIVIL_SERVANT",
                           "SELF_EMPLOYED", "RETIRED", "APPRENTICE", "UNEMPLOYED"]
    months_in_job: int = Field(ge=0)
    in_probation_period: bool = False
    has_co_borrower: bool = False


class Household(BaseModel):
    household_size: int = Field(ge=1, le=15)
    dependent_children: int = Field(default=0, ge=0)
    children_under_14: int = Field(default=0, ge=0)
    housing_status: Literal["OWNER_OUTRIGHT", "OWNER_WITH_MORTGAGE", "TENANT",
                            "HOUSED_FREE", "EMPLOYER_HOUSING"]
    months_at_address: int = Field(ge=0)
    area_type: Literal["urban", "suburban", "rural"] = "urban"

    @model_validator(mode="after")
    def _coherence(self):
        if self.children_under_14 > self.dependent_children:
            raise ValueError("children_under_14 > dependent_children")
        if self.dependent_children >= self.household_size:
            raise ValueError("the household must contain at least one adult")
        return self


class AccountBehaviour(BaseModel):
    relationship_months: int = Field(ge=0)
    days_overdrawn_12m: int = Field(default=0, ge=0, le=366)
    rejected_debits_12m: int = Field(default=0, ge=0)
    max_overdraft_used: float = Field(default=0.0, ge=0)
    liquid_savings: float = Field(default=0.0, ge=0)
    products_held: int = Field(default=1, ge=0)
    salary_domiciled: bool = False
    ficp_flagged: bool = False
    fcc_flagged: bool = False
    loans_repaid_clean: int = Field(default=0, ge=0)


class Application(BaseModel):
    reference: str | None = None
    operation: Operation
    borrower: Borrower
    household: Household
    behaviour: AccountBehaviour
    incomes: list[Income] = Field(min_length=1)
    expenses: list[Expense] = []
    existing_loans: list[ExistingLoan] = []


# --------------------------------------------------------------------------
# Response contract
# --------------------------------------------------------------------------

class Factor(BaseModel):
    variable: str
    value: float | str | None
    contribution: float


class ScoreResponse(BaseModel):
    evaluation_id: str
    reference: str | None
    probability_of_default: float
    risk_grade: Literal["A", "B", "C", "D", "E"]
    out_of_domain: bool
    indicators: dict
    adverse_factors: list[Factor]
    favourable_factors: list[Factor]
    model: dict
    warnings: list[str]


# --------------------------------------------------------------------------
# Model loading
# --------------------------------------------------------------------------

def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


try:
    BUNDLE = joblib.load(MODELS / "default_risk.joblib")
    FINGERPRINT = _fingerprint(MODELS / "default_risk.joblib")
    METRICS = json.loads((MODELS / "metrics.json").read_text(encoding="utf-8"))
except FileNotFoundError as exc:  # pragma: no cover
    raise SystemExit(f"Model not found ({exc}). Run: python3 train.py") from exc

MODEL_VERSION = {
    "name": BUNDLE["name"],
    "fingerprint": FINGERPRINT,
    "n_variables": len(BUNDLE["columns"]),
    "calibration": BUNDLE["calibration"],
    "test_auc": METRICS["default_risk"]["test_retained"]["auc"],
    "test_gini": METRICS["default_risk"]["test_retained"]["gini"],
}

# Beyond the 99.9th percentile of training predictions, fewer than twenty
# applications support the estimate: the logistic regression then extrapolates
# linearly in the logit and returns PDs close to 1 with no empirical basis.
# Those files belong in manual review, not in a pricing engine.
DOMAIN_LIMIT = BUNDLE.get("domain", {}).get("pd_q999", 1.0)


def _grade(p: float) -> str:
    return ("A" if p < 0.02 else "B" if p < 0.05 else
            "C" if p < 0.10 else "D" if p < 0.20 else "E")


def _indicators_and_features(app: Application) -> tuple[dict, dict, list[str]]:
    """Compute the indicators service-side, then assemble the model row."""
    op = app.operation
    payment_excl = monthly_payment(op.requested_amount, op.nominal_rate, op.term_months)
    total_payment = round(payment_excl + op.monthly_insurance_cost, 2)

    ind = compute(
        incomes=[i.model_dump() for i in app.incomes],
        expenses=[e.model_dump() for e in app.expenses],
        loans=[loan.model_dump() for loan in app.existing_loans],
        household=app.household.model_dump(),
        monthly_payment_total=total_payment,
        liquid_savings=app.behaviour.liquid_savings,
    )

    warnings = []
    if ind.dti_after_pct > HCSF_THRESHOLD_PCT:
        warnings.append(
            f"debt-to-income after the loan is {ind.dti_after_pct:.1f}%, above the "
            f"{HCSF_THRESHOLD_PCT:.0f}% HCSF threshold")
    if app.behaviour.ficp_flagged:
        warnings.append("borrower registered on the FICP incident file")
    if ind.residual_income_per_cu < 700:
        warnings.append(
            f"residual income of {ind.residual_income_per_cu:.0f} EUR per consumption unit")

    features = {
        "dti_after_pct": ind.dti_after_pct,
        "above_hcsf_threshold": ind.above_hcsf_threshold,
        "residual_income_per_cu": ind.residual_income_per_cu,
        "savings_months_of_expenses": ind.savings_months_of_expenses,
        "variable_income_share": ind.variable_income_share,
        "down_payment_ratio": op.down_payment / op.requested_amount if op.requested_amount else 0.0,
        "payment_shock": ind.payment_shock,
        "requested_amount": op.requested_amount,
        "term_months": op.term_months,
        "apr": op.apr,
        "has_co_borrower": int(app.borrower.has_co_borrower),
        "insurance_taken": int(op.insurance_taken),
        "existing_loans": len(app.existing_loans),
        "revolving_loans": sum(loan.loan_kind == "revolving" for loan in app.existing_loans),
        "loan_incidents_12m": sum(loan.incidents_12m for loan in app.existing_loans),
        "loans_repaid_clean": app.behaviour.loans_repaid_clean,
        "days_overdrawn_12m": app.behaviour.days_overdrawn_12m,
        "rejected_debits_12m": app.behaviour.rejected_debits_12m,
        "ficp_flagged": int(app.behaviour.ficp_flagged),
        "fcc_flagged": int(app.behaviour.fcc_flagged),
        "salary_domiciled": int(app.behaviour.salary_domiciled),
        "max_overdraft_used": app.behaviour.max_overdraft_used,
        "products_held": app.behaviour.products_held,
        "months_in_job": app.borrower.months_in_job,
        "relationship_months": app.behaviour.relationship_months,
        "months_at_address": app.household.months_at_address,
        "in_probation_period": int(app.borrower.in_probation_period),
        "undocumented_income_lines": sum(not i.documented for i in app.incomes),
        "loan_type": op.loan_type,
        "contract_stability": STABILITY[app.borrower.contract_type],
        "contract_type": app.borrower.contract_type,
        "housing_status": app.household.housing_status,
        "channel": op.channel,
        "occupation": app.borrower.occupation,
        "area_type": app.household.area_type,
    }
    return ind.as_dict() | {"monthly_payment": total_payment}, features, warnings


def _score(features: dict) -> tuple[float, pd.Series | None]:
    X = pd.DataFrame([features])[BUNDLE["columns"]]
    raw = float(BUNDLE["model"].predict_proba(X)[0, 1])

    calibrator = BUNDLE["calibrator"]
    if calibrator is None:
        proba = raw
    elif BUNDLE["calibration"] == "isotonic":
        proba = float(calibrator.predict(np.array([raw]))[0])
    else:
        proba = float(calibrator.predict_proba(np.array([[raw]]))[0, 1])

    pipe = BUNDLE["model"]
    clf = pipe.named_steps["clf"]
    if not hasattr(clf, "coef_"):
        return proba, None
    z = pipe.named_steps["pre"].transform(X)
    names = [n.split("__", 1)[-1] for n in pipe.named_steps["pre"].get_feature_names_out()]
    return proba, pd.Series(clf.coef_[0] * np.asarray(z).ravel(), index=names)


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

app = FastAPI(
    title="Consumer credit risk scoring",
    version="1.0.0",
    description=__doc__,
)


@app.get("/", include_in_schema=False)
def console():
    """Bilingual try-it console, served from the same origin, so no CORS."""
    if not CONSOLE.exists():
        raise HTTPException(404, "console.html not found")
    return FileResponse(CONSOLE)


@app.get("/examples", tags=["operations"])
def examples() -> list[dict]:
    """Demonstration applications, ready to replay."""
    out = []
    for path in sorted(EXAMPLES.glob("application_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        out.append({
            "file": path.name,
            "reference": payload.get("reference"),
            "title_en": payload.get("_title_en", path.stem),
            "title_fr": payload.get("_title_fr", path.stem),
            "application": payload,
        })
    return out


@app.get("/health", tags=["operations"])
def health() -> dict:
    return {"status": "ok", "model": MODEL_VERSION}


@app.get("/model", tags=["operations"])
def model_card() -> dict:
    """Model provenance — required to replay a past decision."""
    return {
        **MODEL_VERSION,
        "variables": BUNDLE["columns"],
        "hcsf_threshold_pct": HCSF_THRESHOLD_PCT,
        "grades": {"A": "< 2%", "B": "2-5%", "C": "5-10%", "D": "10-20%", "E": "> 20%"},
        "domain": BUNDLE.get("domain", {}),
        "out_of_domain_limit": DOMAIN_LIMIT,
        "caveat": (
            "The model only ever learnt from approved applications. It understates the "
            "risk of profiles that are usually declined: usable for ranking, needs "
            "recalibration before pricing."),
    }


@app.post("/score", response_model=ScoreResponse, tags=["scoring"])
def score(application: Application) -> ScoreResponse:
    """Assess an application. Does not decide: the cut-off is a policy matter."""
    try:
        indicators, features, warnings = _indicators_and_features(application)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    proba, contributions = _score(features)

    adverse: list[Factor] = []
    favourable: list[Factor] = []
    if contributions is not None:
        for name, v in contributions.sort_values(ascending=False).head(5).items():
            if v > 0.01:
                adverse.append(Factor(variable=name, value=features.get(name),
                                      contribution=round(float(v), 4)))
        for name, v in contributions.sort_values().head(5).items():
            if v < -0.01:
                favourable.append(Factor(variable=name, value=features.get(name),
                                         contribution=round(float(v), 4)))

    out_of_domain = proba > DOMAIN_LIMIT
    if out_of_domain:
        warnings.append(
            f"probability of {proba:.1%} beyond the 99.9th percentile of the training "
            f"distribution ({DOMAIN_LIMIT:.1%}): the model is extrapolating, this value "
            "must not be used for pricing. Manual review required.")

    return ScoreResponse(
        evaluation_id=str(uuid.uuid4()),
        reference=application.reference,
        probability_of_default=round(proba, 4),
        risk_grade=_grade(proba),
        out_of_domain=out_of_domain,
        indicators=indicators,
        adverse_factors=adverse,
        favourable_factors=favourable,
        model=MODEL_VERSION,
        warnings=warnings,
    )


class SimulationRequest(BaseModel):
    application: Application
    target_pd: float = Field(default=0.05, gt=0, lt=1,
                             description="probability of default to stay under")


@app.post("/simulate", tags=["scoring"])
def simulate(request: SimulationRequest) -> dict:
    """Largest amount that keeps the PD under target, at unchanged term.

    Answers the question an adviser actually asks: *what would have to change for
    this application to pass?* Bisection search — the model is monotonic in
    amount, so the answer is exact to the euro.
    """
    application = request.application
    initial = _score(_indicators_and_features(application)[1])[0]

    def pd_for(amount: float) -> float:
        copy = application.model_copy(deep=True)
        copy.operation.requested_amount = amount
        copy.operation.monthly_insurance_cost = (
            round(amount * 0.00035, 2) if copy.operation.insurance_taken else 0.0)
        return _score(_indicators_and_features(copy)[1])[0]

    if initial <= request.target_pd:
        return {"initial_pd": round(initial, 4), "target_pd": request.target_pd,
                "requested_amount": application.operation.requested_amount,
                "maximum_amount": application.operation.requested_amount,
                "comment": "the target is already met at the requested amount"}

    low, high = 500.0, application.operation.requested_amount
    if pd_for(low) > request.target_pd:
        return {"initial_pd": round(initial, 4), "target_pd": request.target_pd,
                "requested_amount": application.operation.requested_amount,
                "maximum_amount": None,
                "comment": ("no amount brings the PD under target: the risk lies in the "
                            "profile, not in the sizing of the operation")}

    for _ in range(40):
        mid = (low + high) / 2
        if pd_for(mid) <= request.target_pd:
            low = mid
        else:
            high = mid

    return {
        "initial_pd": round(initial, 4),
        "target_pd": request.target_pd,
        "requested_amount": application.operation.requested_amount,
        "maximum_amount": round(low, 2),
        "pd_at_maximum": round(pd_for(low), 4),
        "reduction_required": round(application.operation.requested_amount - low, 2),
        "comment": (f"cutting the amount to {low:,.0f} EUR keeps the PD under "
                    f"{request.target_pd:.0%}").replace(",", " "),
    }
