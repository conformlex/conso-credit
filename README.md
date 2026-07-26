# conso-credit

A synthetic dataset, a scorecard and a scoring service for **French consumer
credit** — built to train a risk model that a chatbot can actually explain.

Everything here is synthetic. No real customer data was used, and none is
required to run it.

Released under the [MIT License](LICENSE) — use it, fork it, ship it.

> Code, schema and documentation are in English. The **decision rationales
> stored in the database are in French**, because that is what a French credit
> decision letter is, and French regulatory terms (FICP, FCC, HCSF, TAEG, taux
> d'usure) are kept as-is: they have no English equivalent.

---

## Quick start

```bash
pip install -r requirements.txt

python3 populate.py 40000 --rebuild   # build and fill credit.db  (~6 s)
sqlite3 credit.db < sql/checks.sql          # coherence checks
python3 export_dataset.py               # dictionary-driven CSV export
python3 train.py                        # train, calibrate, serialise
python3 reject_inference.py             # what selection bias costs

uvicorn api:app --port 8000             # scoring service
python3 demo_applications.py                     # ten worked applications
open http://localhost:8000/             # bilingual console (EN / FR)
```

`credit.db` is about 80 MB and rebuilds in six seconds, so it is git-ignored,
along with `export/`, `models/`, `examples/` and `rationales/`.

---

## What is in the box

| File | Role |
|---|---|
| `sql/schema.sql` | 18 tables, constraints, 3 triggers, views `v_dataset` and `v_class_balance` |
| `sql/reference_data.sql` | 7 reference tables + the 104 variable-dictionary entries |
| `sql/checks.sql` | 8 coherence checks, 6 of them blocking |
| `creditrisk/indicators.py` | debt-to-income, residual income, consumption units, payment shock |
| `creditrisk/generator.py` | application draws, decision policy, default model |
| `creditrisk/rationale.py` | template rationales, driven by the coded reasons |
| `populate.py` | fills the database |
| `export_dataset.py` | dictionary-driven CSV export |
| `train.py` | model selection, sign audit, calibration, score bands, bias audit |
| `predict.py` | score one application from the database, with an exact explanation |
| `reject_inference.py` | measures selection bias against counterfactual ground truth |
| `llm_rationales.py` | export/load of LLM-written rationales |
| `api.py` | HTTP scoring service (FastAPI) |
| `demo_applications.py` | ten demonstration applications |
| `console.html` | bilingual try-it console, served by the API |

---

## The dataset

`populate.py 40000` produces roughly 40,000 applications, of which ~26,000 carry
an observed outcome and ~1,900 a default. That is what the default model needs:
only approved *and* matured loans are labelled, and a realistic consumer-credit
default rate sits around 7%, so the yield is about **0.05 default events per
application generated**.

Below ~20,000 applications you cannot hold the usual 10-to-20 events per
variable rule, and the test split stops carrying enough events for two models to
be meaningfully compared.

`--default-intensity` shifts the latent-risk intercept to over-sample defaults if
you want a smaller set. **Any non-zero value distorts calibration**: the model
will overstate default probability and must be recalibrated against the real
target rate. The value used is recorded in `generation_metadata`, together with
the seed and the volume, so a dataset can always be traced back.

### Three choices that will bind you

**`default_flag` is `NULL` on two populations, never `0`.** Declined applications
(we cannot know what would have happened) and loans still running (right
censoring: they may yet default). Imputing 0 in either case corrupts training —
this is the selection-bias and censoring problem of credit scoring, in one
column.

**Protected attributes are stored but excluded from features.** `age`, `sex`,
`nationality_zone` and `marital_status` are protected characteristics whose use
in credit scoring is unlawful in France. They are kept because they are
indispensable for bias auditing, and exported separately to `protected_*.csv`.
`train.py` uses them to compare mean score against observed default rate per
group: *a score gap not backed by a gap in observed default is a bias*.
`department` is left as a feature despite its geographic-proxy risk — flip it if
you prefer.

**Observed default depends on a latent risk, not on the assigned score.** The
generator draws a true probability of default, then the underwriter observes a
noisy signal of it. Without that separation a model would trivially recover the
outcome from the grade, and your metrics would be fiction.

### Insert order is enforced

- `decision_reason` **before** `decision` — the `trg_declined_needs_reason`
  trigger checks that a decline is motivated at the moment the decision is
  written.
- `outcome` **after** `decision` — `trg_outcome_approved_only` refuses an outcome
  on a non-approved application.

### The dictionary drives everything

`export_dataset.py` never runs `SELECT *`: it asks `variable_dictionary` for the
columns whose role is `feature`. A column added to `v_dataset` without a
dictionary entry **fails the export** instead of silently entering `X`. That is
what stops `risk_score` or `approved_amount` from becoming a model input by
accident.

If you add a column to the view, add its row to `sql/reference_data.sql`.

---

## The models

`train.py` writes to `models/`: both serialised models, the score bands, the test
predictions and `metrics.json`.

**Default risk** — logistic regression on 35 variables, Gini around 0.44, mean
gap between predicted PD and observed default around 0.01. Gradient boosting on
the full 74 variables is kept as a challenger.

Three modelling decisions worth knowing before you touch the code:

**Ratios take precedence over their components.** Exporting both
`residual_income_per_cu` and the income, instalments, rent and household size
that build it inverts the sign of the ratio: the model then learns that *high*
residual income increases risk. With all 74 variables, 9 coefficients out of 26
pointed against business direction. The reduced set has none, for a better
validation AUC. `audit_signs()` runs that check on every training run, and it is
a **hard constraint** — a linear candidate with incoherent signs is dropped
whatever its AUC. A scorecard whose signs are wrong cannot motivate a decline,
and French lenders must be able to.

**Logistic regression is kept unless gradient boosting gains 0.02 AUC.** The
explanation of a decline has to be exact, not approximate: with a linear model a
variable's contribution is its coefficient times its standardised value. That is
what `predict.py` and the API return.

**Calibration is selected, not imposed.** The calibrator is fitted on out-of-fold
training predictions (~1,300 events) and the choice between isotonic, Platt and
*none* is made on validation Brier score. Fitted on the ~300 validation events,
isotonic regression overfitted and degraded what it was meant to fix; it is also
a step function, which flattens granularity to the point of giving three very
different applications the same PD. It is now applied only if it improves Brier
by at least 1% relative.

---

## Selection bias, measured

The default model only ever learns from **approved** applications. A real lender
never finds out how the ones it declined would have behaved. Because this data is
synthetic, the counterfactual exists: `counterfactual_default_flag` holds what
would have happened had the declined applications been granted.

That column has **no production equivalent**. It is a measuring instrument, not a
training signal, and a database trigger prevents it from ever being attached to
an approved application. `python3 reject_inference.py` compares three models on
the whole test population — the one that actually walks through the door:

| Model | AUC | Gini | mean PD | PD/observed gap |
|---|---|---|---|---|
| real (approved only) | 0.808 | 0.616 | 0.101 | 0.032 |
| reject inference | 0.808 | 0.616 | 0.101 | 0.030 |
| oracle (whole population) | 0.812 | 0.624 | 0.122 | 0.012 |
| *actual default rate* | | | *0.128* | |

The result is counter-intuitive and useful: **the bias costs almost nothing in
discrimination** (+0.004 AUC) **and a great deal in calibration**. The model
ranks applications correctly; it understates their risk. On declined applications
it predicts 17.7% default where the truth is 26.1% — eight points out. A model
used for ranking is fine; a model used for pricing or provisioning is not.

Fuzzy augmentation, the classic reject-inference technique, recovers **2%** of
the AUC gap. That follows: it weights declined applications with a probability
produced by the biased model itself. It extrapolates; it discovers nothing. The
only remedy that genuinely adds information is approving a random sample of
borderline applications and observing them.

---

## The scoring service

```bash
uvicorn api:app --port 8000
open http://localhost:8000/          # console
open http://localhost:8000/docs      # OpenAPI
```

| Route | Purpose |
|---|---|
| `GET /health` | liveness + version of the model in service |
| `GET /model` | provenance: variables, fingerprint, metrics, caveats |
| `GET /examples` | the ten demonstration applications |
| `POST /score` | assess an application |
| `POST /simulate` | largest amount that keeps the PD under a target |

**The service takes a raw application and computes the indicators itself.** This
is the design decision that matters most. If the caller computed its own
debt-to-income ratio, sooner or later it would compute it differently from the
training set — forgetting the instalments refinanced by a consolidation,
weighting variable income at 100% instead of 70% — and the model would degrade
with no alarm going off. Inputs would stay in range, outputs would stay
plausible, and the PD would be wrong. One definition,
`creditrisk/indicators.py`, on the service side.

**The service does not decide.** It returns a probability, a grade, the computed
indicators and the factors that weigh. The cut-off is a policy decision,
revisable according to the relative cost of a default; freezing it inside the
model means it cannot be changed without retraining. `train.py` prints a cut-off
table for default costs of 5x, 10x and 20x a lost deal.

**Every response carries the model's SHA-256 fingerprint and an
`evaluation_id`.** Without those two fields a past decision cannot be replayed,
and replayability is a requirement.

**Out-of-domain files are flagged.** On an application combining an FICP flag, an
FCC flag, six rejected debits and 77% debt-to-income, the model returns a
probability above 97%. No consumer loan defaults with that certainty — the
logistic regression is extrapolating linearly in the logit, well past what the
data supports. Beyond the 99.9th percentile of training predictions the response
carries `out_of_domain: true` and an explicit warning: the value must not be used
for pricing, and the file belongs in manual review.

`POST /simulate` answers the question an adviser actually asks: *what would have
to change for this application to pass?* Bisection on the amount; the model is
monotonic, so the answer is exact to the euro. When no amount is low enough, the
service says so — the risk then lies in the profile, not the sizing.

---

## Rationales

Two origins, traced by `decision.decided_by`:

- `rule_engine` — deterministic template driven by the coded reasons. Covers the
  volume; text and reasons cannot disagree.
- `llm` — written by a language model from the application summary. More natural
  register, and the intended training signal for a chatbot. **Audit it**: the
  model you train will imitate that register, not banking expertise. This is
  distillation, and it is worth being explicit about.

```bash
python3 llm_rationales.py export     # writes rationales/batch_NN_in.json
# ... a language model writes ...     → rationales/batch_NN_out.json
python3 llm_rationales.py load       # updates the database
```

Loading rejects three categories: text under 100 characters, text that
contradicts the decision it explains, and **files older than their input batch**.
That last guard matters: references (`APP-YYYY-NNNNNN`) are reassigned on every
rebuild, so loading a stale batch would silently attach rationales to the wrong
applications.

---

## Is a chatbot the right interface?

Not for the decision itself. A credit application is a form, not a conversation:
the variables are known in advance and arrive from the origination system.
Decisions must be reproducible and auditable, and credit scoring is classified as
high-risk under the EU AI Act. A language model adds no predictive value — the PD
comes from 35 coefficients — and adds one real risk: stating a figure that
contradicts the model.

Where conversation genuinely wins is around the decision: the *what would have to
change* question, pre-application simulation, and writing the decline letter. The
architecture that follows is a deterministic model that computes, and a
constrained language model that puts it into words and invents nothing.

---

## Known limits

- **AUC around 0.74 on approved applications is the honest ceiling**, not a
  shortfall. The generator injects Gaussian noise into the latent risk to
  represent unobserved heterogeneity; no model can recover it. If you ever score
  much higher, look for a leak before celebrating.
- **The ceiling is the generator, not the volume.** Past a few tens of thousands
  of applications drawn from the same decision policy, adding rows only
  re-samples the same function. Plot a learning curve against a fixed test split:
  if it plateaus, the generator is the constraint.
- **The LLM rationales are distillation.** The tabular side is solid; the
  language side is capped by the quality of the generation prompt. Having a
  credit analyst review a core set of them is where the best return lies.
- **No automated test suite.** Verification runs through `sql/checks.sql` and the
  audits printed by `train.py`. If the generator changes, nothing will
  automatically catch a distribution regression.

---

## License

MIT. Do what you like with it; just keep the copyright notice.

The dataset it generates is synthetic and carries no personal data, so it is
free of GDPR constraints. That is a property of *this* generator, not of the
pipeline: point the same code at real applications and every obligation applies
again — lawful basis, minimisation, the right to an explanation for automated
decisions, and the high-risk classification that the EU AI Act attaches to
creditworthiness assessment.
