-- =====================================================================
-- French consumer-credit application database (synthetic data)
-- Purpose : train a credit-risk model that a chatbot can explain
-- Engine  : SQLite
-- =====================================================================
-- Conventions:
--   * dates and timestamps as ISO-8601 TEXT ('YYYY-MM-DD')
--   * booleans as INTEGER 0/1
--   * amounts as NUMERIC, in euros
--   * no derivable column is stored without reason (age, relationship
--     length: computed in the view from application_date)
--
-- French regulatory terms are kept as-is because they have no English
-- equivalent: FICP and FCC are Banque de France incident registers, HCSF
-- is the macroprudential authority behind the 35% debt-to-income cap,
-- and the usury rate (taux d'usure) is a legal APR ceiling.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 1. REFERENCE DATA
-- ---------------------------------------------------------------------

CREATE TABLE loan_type (
    code   TEXT PRIMARY KEY,
    label  TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE employment_contract (
    code      TEXT PRIMARY KEY,
    label     TEXT NOT NULL,
    -- Job-security tier: drives both the generator and the explanation.
    stability TEXT NOT NULL CHECK (stability IN ('stable', 'intermediate', 'precarious')),
    active    INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE housing_status (
    code          TEXT PRIMARY KEY,
    label         TEXT NOT NULL,
    -- Is a rent line expected in the expense table for this status?
    rent_expected INTEGER NOT NULL CHECK (rent_expected IN (0, 1)),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE occupation (
    code   TEXT PRIMARY KEY,
    label  TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE income_type (
    code            TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    -- Share of the amount underwriters usually count (French practice).
    default_weight  NUMERIC NOT NULL CHECK (default_weight BETWEEN 0 AND 1),
    -- Family used to pivot the export view.
    family          TEXT NOT NULL CHECK (family IN
                      ('salary', 'bonus', 'benefits', 'pension', 'rental', 'other')),
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE expense_type (
    code   TEXT PRIMARY KEY,
    label  TEXT NOT NULL,
    family TEXT NOT NULL CHECK (family IN ('rent', 'alimony', 'tax', 'other')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE reason (
    code     TEXT PRIMARY KEY,
    label    TEXT NOT NULL,
    polarity TEXT NOT NULL CHECK (polarity IN ('favourable', 'adverse')),
    category TEXT NOT NULL CHECK (category IN
                ('affordability', 'income', 'stability', 'behaviour',
                 'collateral', 'regulatory', 'override')),
    active   INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

-- ---------------------------------------------------------------------
-- 2. CUSTOMER
-- ---------------------------------------------------------------------
-- Whatever does not depend on a specific application. Age and relationship
-- length are NOT stored: they are computed at application_date, otherwise
-- an old case can no longer be replayed as it stood.

CREATE TABLE customer (
    id                      INTEGER PRIMARY KEY,
    reference               TEXT NOT NULL UNIQUE,        -- CUS-000123
    birth_date              TEXT NOT NULL,               -- protected attribute
    sex                     TEXT NOT NULL CHECK (sex IN ('M', 'F', 'NR')),
    nationality_zone        TEXT NOT NULL CHECK (nationality_zone IN ('FR', 'EU', 'NON_EU')),
    relationship_start_date TEXT NOT NULL,
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- 3. APPLICATION
-- ---------------------------------------------------------------------

CREATE TABLE application (
    id                     INTEGER PRIMARY KEY,
    reference              TEXT NOT NULL UNIQUE,          -- APP-2026-000123
    customer_id            INTEGER NOT NULL REFERENCES customer(id),
    co_borrower_id         INTEGER REFERENCES customer(id),
    application_date       TEXT NOT NULL,

    channel                TEXT NOT NULL CHECK (channel IN
                             ('branch', 'online', 'broker', 'point_of_sale')),
    loan_type_code         TEXT NOT NULL REFERENCES loan_type(code),
    purpose                TEXT,

    requested_amount       NUMERIC NOT NULL CHECK (requested_amount > 0),
    term_months            INTEGER NOT NULL CHECK (term_months BETWEEN 1 AND 120),
    nominal_rate           NUMERIC NOT NULL CHECK (nominal_rate >= 0),
    apr                    NUMERIC NOT NULL CHECK (apr >= 0),          -- TAEG
    usury_rate_cap         NUMERIC NOT NULL CHECK (usury_rate_cap > 0),

    payment_excl_insurance NUMERIC NOT NULL CHECK (payment_excl_insurance > 0),
    insurance_taken        INTEGER NOT NULL CHECK (insurance_taken IN (0, 1)),
    monthly_insurance_cost NUMERIC NOT NULL DEFAULT 0 CHECK (monthly_insurance_cost >= 0),
    monthly_payment        NUMERIC NOT NULL CHECK (monthly_payment > 0),
    down_payment           NUMERIC NOT NULL DEFAULT 0 CHECK (down_payment >= 0),

    -- Assigned at creation and NEVER redrawn at export time: without this,
    -- no two training runs are comparable.
    split                  TEXT NOT NULL CHECK (split IN ('train', 'val', 'test')),
    source                 TEXT NOT NULL CHECK (source IN ('manual', 'generated')),

    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at             TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (co_borrower_id IS NULL OR co_borrower_id <> customer_id),
    -- Regulatory: the APR may not exceed the legal usury ceiling.
    CHECK (apr <= usury_rate_cap),
    CHECK (insurance_taken = 1 OR monthly_insurance_cost = 0)
);

CREATE INDEX idx_application_customer ON application(customer_id);
CREATE INDEX idx_application_split    ON application(split);
CREATE INDEX idx_application_date     ON application(application_date);

-- ---------------------------------------------------------------------
-- 4. SITUATION SNAPSHOT (as of the application date)
-- ---------------------------------------------------------------------

CREATE TABLE household (
    application_id      INTEGER PRIMARY KEY REFERENCES application(id) ON DELETE CASCADE,
    marital_status      TEXT NOT NULL CHECK (marital_status IN
                          ('single', 'married', 'civil_union', 'cohabiting',
                           'divorced', 'widowed')),                 -- protected
    household_size      INTEGER NOT NULL CHECK (household_size BETWEEN 1 AND 15),
    dependent_children  INTEGER NOT NULL DEFAULT 0 CHECK (dependent_children >= 0),
    children_under_14   INTEGER NOT NULL DEFAULT 0 CHECK (children_under_14 >= 0),
    housing_status_code TEXT NOT NULL REFERENCES housing_status(code),
    months_at_address   INTEGER NOT NULL CHECK (months_at_address >= 0),
    department          TEXT NOT NULL,                              -- French département
    area_type           TEXT NOT NULL CHECK (area_type IN ('urban', 'suburban', 'rural')),

    CHECK (children_under_14 <= dependent_children),
    CHECK (dependent_children < household_size)
);

-- One row per borrower: the co-borrower carries exactly the same attributes
-- as the main applicant, hence a table rather than duplicated _co columns.
CREATE TABLE employment (
    application_id       INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    role                 TEXT NOT NULL CHECK (role IN ('primary', 'co_borrower')),
    occupation_code      TEXT NOT NULL REFERENCES occupation(code),
    contract_code        TEXT NOT NULL REFERENCES employment_contract(code),
    months_in_job        INTEGER NOT NULL CHECK (months_in_job >= 0),
    in_probation_period  INTEGER NOT NULL DEFAULT 0 CHECK (in_probation_period IN (0, 1)),
    industry             TEXT,
    employer_type        TEXT CHECK (employer_type IN ('private', 'public', 'self_employed')),

    PRIMARY KEY (application_id, role)
);

-- ---------------------------------------------------------------------
-- 5. INCOME, EXPENSES, EXISTING LOANS
-- ---------------------------------------------------------------------

-- The weighting is explicit per line because it is the heart of French
-- underwriting: variable or rental income is rarely counted at 100%.
CREATE TABLE income (
    id               INTEGER PRIMARY KEY,
    application_id   INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('primary', 'co_borrower', 'household')),
    income_type_code TEXT NOT NULL REFERENCES income_type(code),
    monthly_amount   NUMERIC NOT NULL CHECK (monthly_amount > 0),
    variability      TEXT NOT NULL CHECK (variability IN ('fixed', 'variable')),
    weighting        NUMERIC NOT NULL CHECK (weighting BETWEEN 0 AND 1),
    documented       INTEGER NOT NULL DEFAULT 1 CHECK (documented IN (0, 1))
);

CREATE INDEX idx_income_application ON income(application_id);

CREATE TABLE expense (
    id                INTEGER PRIMARY KEY,
    application_id    INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    expense_type_code TEXT NOT NULL REFERENCES expense_type(code),
    monthly_amount    NUMERIC NOT NULL CHECK (monthly_amount > 0),
    -- An expense ending within a few months is declared but left out of the
    -- debt-to-income ratio.
    counted_in_dti    INTEGER NOT NULL DEFAULT 1 CHECK (counted_in_dti IN (0, 1))
);

CREATE INDEX idx_expense_application ON expense(application_id);

-- repaid_by_this_loan flags a balance that this operation refinances: its
-- payment then disappears from the post-loan ratio. Without it, debt
-- consolidation always looks unaffordable.
CREATE TABLE existing_loan (
    id                  INTEGER PRIMARY KEY,
    application_id      INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    loan_kind           TEXT NOT NULL CHECK (loan_kind IN
                          ('mortgage', 'amortising_consumer', 'revolving',
                           'lease', 'overdraft')),
    lender              TEXT NOT NULL CHECK (lender IN ('internal', 'external')),
    outstanding_balance NUMERIC NOT NULL CHECK (outstanding_balance >= 0),
    monthly_payment     NUMERIC NOT NULL CHECK (monthly_payment >= 0),
    remaining_months    INTEGER NOT NULL CHECK (remaining_months >= 0),
    repaid_by_this_loan INTEGER NOT NULL DEFAULT 0 CHECK (repaid_by_this_loan IN (0, 1)),
    incidents_12m       INTEGER NOT NULL DEFAULT 0 CHECK (incidents_12m >= 0)
);

CREATE INDEX idx_existing_loan_application ON existing_loan(application_id);

-- ---------------------------------------------------------------------
-- 6. ACCOUNT BEHAVIOUR
-- ---------------------------------------------------------------------
-- In practice the strongest single predictor of default, ahead of income.

CREATE TABLE account_behaviour (
    application_id       INTEGER PRIMARY KEY REFERENCES application(id) ON DELETE CASCADE,
    average_balance      NUMERIC NOT NULL,
    days_overdrawn_12m   INTEGER NOT NULL DEFAULT 0 CHECK (days_overdrawn_12m BETWEEN 0 AND 366),
    rejected_debits_12m  INTEGER NOT NULL DEFAULT 0 CHECK (rejected_debits_12m >= 0),
    overdraft_fees_12m   INTEGER NOT NULL DEFAULT 0 CHECK (overdraft_fees_12m >= 0),
    overdraft_limit      NUMERIC NOT NULL DEFAULT 0 CHECK (overdraft_limit >= 0),
    max_overdraft_used   NUMERIC NOT NULL DEFAULT 0 CHECK (max_overdraft_used >= 0),
    liquid_savings       NUMERIC NOT NULL DEFAULT 0 CHECK (liquid_savings >= 0),
    total_savings        NUMERIC NOT NULL DEFAULT 0 CHECK (total_savings >= 0),
    products_held        INTEGER NOT NULL DEFAULT 0 CHECK (products_held >= 0),
    salary_domiciled     INTEGER NOT NULL DEFAULT 0 CHECK (salary_domiciled IN (0, 1)),
    ficp_flagged         INTEGER NOT NULL DEFAULT 0 CHECK (ficp_flagged IN (0, 1)),
    fcc_flagged          INTEGER NOT NULL DEFAULT 0 CHECK (fcc_flagged IN (0, 1)),
    loans_repaid_clean   INTEGER NOT NULL DEFAULT 0 CHECK (loans_repaid_clean >= 0),

    CHECK (liquid_savings <= total_savings)
);

-- ---------------------------------------------------------------------
-- 7. INDICATORS (computed, never captured)
-- ---------------------------------------------------------------------
-- Frozen for reproducibility, but income / expense / existing_loan remain
-- the source of truth. formula_version lets a formula change without making
-- earlier rows uninterpretable.

CREATE TABLE indicators (
    application_id             INTEGER PRIMARY KEY REFERENCES application(id) ON DELETE CASCADE,
    gross_income               NUMERIC NOT NULL CHECK (gross_income >= 0),
    weighted_income            NUMERIC NOT NULL CHECK (weighted_income >= 0),
    variable_income_share      NUMERIC NOT NULL CHECK (variable_income_share BETWEEN 0 AND 1),
    counted_expenses           NUMERIC NOT NULL CHECK (counted_expenses >= 0),
    existing_payments          NUMERIC NOT NULL CHECK (existing_payments >= 0),
    retained_payments          NUMERIC NOT NULL CHECK (retained_payments >= 0),
    dti_before_pct             NUMERIC NOT NULL CHECK (dti_before_pct BETWEEN 0 AND 200),
    dti_after_pct              NUMERIC NOT NULL CHECK (dti_after_pct BETWEEN 0 AND 200),
    above_hcsf_threshold       INTEGER NOT NULL CHECK (above_hcsf_threshold IN (0, 1)),
    consumption_units          NUMERIC NOT NULL CHECK (consumption_units >= 1),
    residual_income            NUMERIC NOT NULL,
    residual_income_per_cu     NUMERIC NOT NULL,
    payment_shock              NUMERIC NOT NULL,
    savings_months_of_expenses NUMERIC NOT NULL CHECK (savings_months_of_expenses >= 0),
    formula_version            TEXT NOT NULL,
    computed_at                TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (retained_payments <= existing_payments),
    CHECK (weighted_income <= gross_income)
);

-- ---------------------------------------------------------------------
-- 8. TARGETS
-- ---------------------------------------------------------------------

CREATE TABLE decision (
    application_id      INTEGER PRIMARY KEY REFERENCES application(id) ON DELETE CASCADE,
    result              TEXT NOT NULL CHECK (result IN
                          ('approved', 'approved_with_conditions', 'declined', 'deferred')),
    approved_amount     NUMERIC CHECK (approved_amount IS NULL OR approved_amount > 0),
    approved_term_months INTEGER CHECK (approved_term_months IS NULL OR approved_term_months > 0),
    risk_score          INTEGER NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    risk_grade          TEXT NOT NULL CHECK (risk_grade IN ('A', 'B', 'C', 'D', 'E')),
    conditions          TEXT,
    -- Free-text explanation, in French: this is the chatbot's training signal.
    rationale           TEXT NOT NULL,
    -- 'llm' means the text was written by a language model. A training set
    -- where you no longer know who wrote what cannot be audited.
    decided_by          TEXT NOT NULL CHECK (decided_by IN ('human', 'rule_engine', 'llm')),
    decision_date       TEXT NOT NULL,

    -- An amount is granted if and only if the application was approved.
    CHECK ((result IN ('approved', 'approved_with_conditions')) = (approved_amount IS NOT NULL)),
    CHECK ((result IN ('approved', 'approved_with_conditions')) = (approved_term_months IS NOT NULL)),
    CHECK (result <> 'approved_with_conditions'
           OR (conditions IS NOT NULL AND length(trim(conditions)) > 0))
);

-- The foreign key points at application, not decision: trg_declined_needs_reason
-- requires the reasons to exist when the decision row is written, so they must
-- be insertable first. Insert order: decision_reason, then decision.
CREATE TABLE decision_reason (
    application_id INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    reason_code    TEXT NOT NULL REFERENCES reason(code),
    PRIMARY KEY (application_id, reason_code)
);

-- Recorded after the fact, on approved applications only. Lets a model learn
-- from realised risk rather than from the underwriter's judgement alone, and
-- therefore avoid mechanically reproducing its biases.
CREATE TABLE outcome (
    application_id            INTEGER PRIMARY KEY REFERENCES decision(application_id) ON DELETE CASCADE,
    status                    TEXT NOT NULL CHECK (status IN
                                ('ongoing', 'repaid_clean', 'minor_incidents',
                                 'default', 'early_repayment')),
    observation_months        INTEGER NOT NULL CHECK (observation_months >= 0),
    payments_made             INTEGER NOT NULL DEFAULT 0 CHECK (payments_made >= 0),
    missed_payments           INTEGER NOT NULL DEFAULT 0 CHECK (missed_payments >= 0),
    first_missed_payment_date TEXT,
    balance_at_default        NUMERIC CHECK (balance_at_default IS NULL OR balance_at_default >= 0),
    sent_to_collections       INTEGER NOT NULL DEFAULT 0 CHECK (sent_to_collections IN (0, 1)),
    closed_date               TEXT,

    CHECK (missed_payments = 0 OR first_missed_payment_date IS NOT NULL),
    CHECK (status <> 'default' OR balance_at_default IS NOT NULL),
    CHECK (status <> 'repaid_clean' OR missed_payments = 0)
);

-- The COUNTERFACTUAL outcome: what would have happened had a NON-approved
-- application been granted, at the requested amount and term.
--
-- This table has no production equivalent. It exists only because the data is
-- synthetic: the generator knows the latent risk of declined applications, a
-- lender never will. It serves two purposes, and only two:
--   1. measure what selection bias actually costs the model;
--   2. act as ground truth when testing reject inference.
-- It must NEVER be mixed into `outcome` in a training run presented as
-- reproducible in production.
CREATE TABLE counterfactual_outcome (
    application_id     INTEGER PRIMARY KEY REFERENCES application(id) ON DELETE CASCADE,
    status             TEXT NOT NULL CHECK (status IN
                         ('ongoing', 'repaid_clean', 'minor_incidents',
                          'default', 'early_repayment')),
    observation_months INTEGER NOT NULL CHECK (observation_months >= 0),
    missed_payments    INTEGER NOT NULL DEFAULT 0 CHECK (missed_payments >= 0)
);

-- Mirror of the outcome trigger: a counterfactual only makes sense on an
-- application that was NOT approved. On an approval, the real outcome exists.
CREATE TRIGGER trg_counterfactual_not_approved
BEFORE INSERT ON counterfactual_outcome
FOR EACH ROW
WHEN (SELECT result FROM decision WHERE application_id = NEW.application_id)
     IN ('approved', 'approved_with_conditions')
BEGIN
    SELECT RAISE(ABORT, 'counterfactual not allowed: the application was approved');
END;

-- An outcome may only exist on an approval. The foreign key already points at
-- decision; this trigger closes the declined/deferred case.
CREATE TRIGGER trg_outcome_approved_only
BEFORE INSERT ON outcome
FOR EACH ROW
WHEN (SELECT result FROM decision WHERE application_id = NEW.application_id)
     NOT IN ('approved', 'approved_with_conditions')
BEGIN
    SELECT RAISE(ABORT, 'outcome not allowed: the application was not approved');
END;

-- Every decline must be motivated: without coded reasons the dataset supports
-- no analysis of why applications are turned down.
CREATE TRIGGER trg_declined_needs_reason
AFTER INSERT ON decision
FOR EACH ROW
WHEN NEW.result = 'declined'
     AND NOT EXISTS (SELECT 1 FROM decision_reason WHERE application_id = NEW.application_id)
BEGIN
    SELECT RAISE(ABORT, 'declined without a reason: insert reasons before the decision');
END;

-- ---------------------------------------------------------------------
-- 9. VARIABLE DICTIONARY
-- ---------------------------------------------------------------------
-- Drives the export: the ML script never runs SELECT *, it asks the
-- dictionary for columns whose role is 'feature'. Any v_dataset column
-- missing from here fails the export rather than silently entering X.
-- The descriptions double as context for the chatbot's explanations.

CREATE TABLE variable_dictionary (
    column_name TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    data_type   TEXT NOT NULL CHECK (data_type IN
                  ('numeric', 'integer', 'boolean', 'categorical', 'text', 'date')),
    -- feature   : allowed model input
    -- target    : to predict, never an input
    -- meta      : identifiers, dates, traceability
    -- protected : protected attribute (discrimination is unlawful in French
    --             lending): kept for bias auditing, excluded from features
    role        TEXT NOT NULL CHECK (role IN ('feature', 'target', 'meta', 'protected')),
    categories  TEXT,
    unit        TEXT,
    description TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- 9b. DATASET PROVENANCE
-- ---------------------------------------------------------------------
-- A training set whose build parameters are unknown is not reproducible.
-- default_intensity is the shift applied to the latent-risk intercept: any
-- non-zero value over-samples defaults and forces you to recalibrate the
-- predicted probabilities against the real target rate.

CREATE TABLE generation_metadata (
    id                INTEGER PRIMARY KEY,
    generated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    n_applications    INTEGER NOT NULL CHECK (n_applications > 0),
    seed              INTEGER NOT NULL,
    default_intensity NUMERIC NOT NULL DEFAULT 0,
    reference_date    TEXT NOT NULL,          -- the generator's "today"
    formula_version   TEXT NOT NULL,
    comment           TEXT
);

-- ---------------------------------------------------------------------
-- 10. EXPORT VIEW
-- ---------------------------------------------------------------------
-- One row per application, ready for pandas:
--     pd.read_sql("SELECT * FROM v_dataset", conn)

CREATE VIEW v_dataset AS
WITH inc AS (
    SELECT i.application_id,
           SUM(CASE WHEN t.family = 'salary'   THEN i.monthly_amount ELSE 0 END) AS income_salary,
           SUM(CASE WHEN t.family = 'bonus'    THEN i.monthly_amount ELSE 0 END) AS income_bonus,
           SUM(CASE WHEN t.family = 'benefits' THEN i.monthly_amount ELSE 0 END) AS income_benefits,
           SUM(CASE WHEN t.family = 'pension'  THEN i.monthly_amount ELSE 0 END) AS income_pension,
           SUM(CASE WHEN t.family = 'rental'   THEN i.monthly_amount ELSE 0 END) AS income_rental,
           SUM(CASE WHEN t.family = 'other'    THEN i.monthly_amount ELSE 0 END) AS income_other,
           SUM(CASE WHEN i.role = 'co_borrower' THEN i.monthly_amount ELSE 0 END) AS income_co_borrower,
           SUM(CASE WHEN i.documented = 0       THEN 1 ELSE 0 END)                AS undocumented_income_lines
    FROM income i
    JOIN income_type t ON t.code = i.income_type_code
    GROUP BY i.application_id
),
exp AS (
    SELECT e.application_id,
           SUM(CASE WHEN t.family = 'rent'    THEN e.monthly_amount ELSE 0 END) AS expense_rent,
           SUM(CASE WHEN t.family = 'alimony' THEN e.monthly_amount ELSE 0 END) AS expense_alimony,
           SUM(CASE WHEN t.family = 'tax'     THEN e.monthly_amount ELSE 0 END) AS expense_tax,
           SUM(CASE WHEN t.family = 'other'   THEN e.monthly_amount ELSE 0 END) AS expense_other
    FROM expense e
    JOIN expense_type t ON t.code = e.expense_type_code
    WHERE e.counted_in_dti = 1
    GROUP BY e.application_id
),
loans AS (
    SELECT application_id,
           COUNT(*)                                                    AS existing_loans,
           SUM(monthly_payment)                                        AS existing_loan_payments,
           SUM(outstanding_balance)                                    AS outstanding_balance_total,
           SUM(CASE WHEN loan_kind = 'revolving' THEN 1 ELSE 0 END)    AS revolving_loans,
           SUM(CASE WHEN repaid_by_this_loan = 1 THEN 1 ELSE 0 END)    AS loans_refinanced,
           SUM(incidents_12m)                                          AS loan_incidents_12m,
           MAX(remaining_months)                                       AS longest_remaining_months
    FROM existing_loan
    GROUP BY application_id
),
rsn AS (
    SELECT dr.application_id,
           group_concat(dr.reason_code, '|') AS reasons,
           SUM(CASE WHEN r.polarity = 'adverse'    THEN 1 ELSE 0 END) AS adverse_reasons,
           SUM(CASE WHEN r.polarity = 'favourable' THEN 1 ELSE 0 END) AS favourable_reasons
    FROM decision_reason dr
    JOIN reason r ON r.code = dr.reason_code
    GROUP BY dr.application_id
)
SELECT
    -- ---- meta -------------------------------------------------------
    a.id                        AS application_id,
    a.reference                 AS application_reference,
    c.reference                 AS customer_reference,
    a.application_date          AS application_date,
    a.split                     AS split,
    a.source                    AS source,

    -- ---- protected attributes ---------------------------------------
    CAST((julianday(a.application_date) - julianday(c.birth_date)) / 365.25 AS INTEGER)
                                AS age,
    c.sex                       AS sex,
    c.nationality_zone          AS nationality_zone,
    h.marital_status            AS marital_status,

    -- ---- the operation ----------------------------------------------
    a.channel                   AS channel,
    a.loan_type_code            AS loan_type,
    a.requested_amount          AS requested_amount,
    a.term_months               AS term_months,
    a.nominal_rate              AS nominal_rate,
    a.apr                       AS apr,
    a.payment_excl_insurance    AS payment_excl_insurance,
    a.insurance_taken           AS insurance_taken,
    a.monthly_insurance_cost    AS monthly_insurance_cost,
    a.monthly_payment           AS monthly_payment,
    a.down_payment              AS down_payment,
    CASE WHEN a.down_payment > 0 THEN a.down_payment / a.requested_amount ELSE 0 END
                                AS down_payment_ratio,
    CASE WHEN a.co_borrower_id IS NOT NULL THEN 1 ELSE 0 END
                                AS has_co_borrower,

    -- ---- household and housing --------------------------------------
    h.household_size            AS household_size,
    h.dependent_children        AS dependent_children,
    h.housing_status_code       AS housing_status,
    h.months_at_address         AS months_at_address,
    h.department                AS department,
    h.area_type                 AS area_type,

    -- ---- employment ---------------------------------------------------
    e.occupation_code           AS occupation,
    e.contract_code             AS contract_type,
    ec.stability                AS contract_stability,
    e.months_in_job             AS months_in_job,
    e.in_probation_period       AS in_probation_period,
    e.industry                  AS industry,
    e.employer_type             AS employer_type,
    eco.contract_code           AS co_borrower_contract,
    eco.months_in_job           AS co_borrower_months_in_job,

    -- ---- banking relationship -----------------------------------------
    CAST((julianday(a.application_date) - julianday(c.relationship_start_date)) / 30.4375 AS INTEGER)
                                AS relationship_months,

    -- ---- income --------------------------------------------------------
    COALESCE(inc.income_salary, 0)             AS income_salary,
    COALESCE(inc.income_bonus, 0)              AS income_bonus,
    COALESCE(inc.income_benefits, 0)           AS income_benefits,
    COALESCE(inc.income_pension, 0)            AS income_pension,
    COALESCE(inc.income_rental, 0)             AS income_rental,
    COALESCE(inc.income_other, 0)              AS income_other,
    COALESCE(inc.income_co_borrower, 0)        AS income_co_borrower,
    COALESCE(inc.undocumented_income_lines, 0) AS undocumented_income_lines,
    ind.gross_income                           AS gross_income,
    ind.weighted_income                        AS weighted_income,
    ind.variable_income_share                  AS variable_income_share,

    -- ---- expenses -------------------------------------------------------
    COALESCE(exp.expense_rent, 0)    AS expense_rent,
    COALESCE(exp.expense_alimony, 0) AS expense_alimony,
    COALESCE(exp.expense_tax, 0)     AS expense_tax,
    COALESCE(exp.expense_other, 0)   AS expense_other,
    ind.counted_expenses             AS counted_expenses,

    -- ---- existing loans --------------------------------------------------
    COALESCE(loans.existing_loans, 0)            AS existing_loans,
    COALESCE(loans.existing_loan_payments, 0)    AS existing_loan_payments,
    COALESCE(loans.outstanding_balance_total, 0) AS outstanding_balance_total,
    COALESCE(loans.revolving_loans, 0)           AS revolving_loans,
    COALESCE(loans.loans_refinanced, 0)          AS loans_refinanced,
    COALESCE(loans.loan_incidents_12m, 0)        AS loan_incidents_12m,
    COALESCE(loans.longest_remaining_months, 0)  AS longest_remaining_months,
    ind.retained_payments                        AS retained_payments,

    -- ---- account behaviour -----------------------------------------------
    ab.average_balance      AS average_balance,
    ab.days_overdrawn_12m   AS days_overdrawn_12m,
    ab.rejected_debits_12m  AS rejected_debits_12m,
    ab.overdraft_fees_12m   AS overdraft_fees_12m,
    ab.overdraft_limit      AS overdraft_limit,
    ab.max_overdraft_used   AS max_overdraft_used,
    ab.liquid_savings       AS liquid_savings,
    ab.total_savings        AS total_savings,
    ab.products_held        AS products_held,
    ab.salary_domiciled     AS salary_domiciled,
    ab.ficp_flagged         AS ficp_flagged,
    ab.fcc_flagged          AS fcc_flagged,
    ab.loans_repaid_clean   AS loans_repaid_clean,

    -- ---- computed indicators ----------------------------------------------
    ind.dti_before_pct             AS dti_before_pct,
    ind.dti_after_pct              AS dti_after_pct,
    ind.above_hcsf_threshold       AS above_hcsf_threshold,
    ind.consumption_units          AS consumption_units,
    ind.residual_income            AS residual_income,
    ind.residual_income_per_cu     AS residual_income_per_cu,
    ind.payment_shock              AS payment_shock,
    ind.savings_months_of_expenses AS savings_months_of_expenses,
    ind.formula_version            AS formula_version,

    -- ---- targets ------------------------------------------------------------
    d.result               AS decision_result,
    d.risk_score           AS risk_score,
    d.risk_grade           AS risk_grade,
    d.approved_amount      AS approved_amount,
    d.approved_term_months AS approved_term_months,
    d.conditions           AS conditions,
    d.rationale            AS rationale,
    rsn.reasons            AS reasons,
    COALESCE(rsn.adverse_reasons, 0)    AS adverse_reasons,
    COALESCE(rsn.favourable_reasons, 0) AS favourable_reasons,
    o.status              AS outcome_status,
    o.missed_payments     AS outcome_missed_payments,
    o.sent_to_collections AS outcome_sent_to_collections,
    o.balance_at_default  AS outcome_balance_at_default,

    -- NULL on a non-approved application (we cannot know what would have
    -- happened) AND on a loan still running (right censoring: it may still
    -- default). Labelling 'ongoing' as 0 would teach the model that a young
    -- loan is a healthy loan.
    CASE WHEN o.status = 'default'  THEN 1
         WHEN o.status IS NULL      THEN NULL
         WHEN o.status = 'ongoing'  THEN NULL
         ELSE 0 END       AS default_flag,

    -- Ground truth that is unobtainable in production: what would have happened
    -- had the declined application been granted. For measuring selection bias
    -- and testing reject inference, never for training a model you would claim
    -- is reproducible.
    CASE WHEN cf.status = 'default' THEN 1
         WHEN cf.status IS NULL     THEN NULL
         WHEN cf.status = 'ongoing' THEN NULL
         ELSE 0 END       AS counterfactual_default_flag,

    -- ---- decision traceability ------------------------------------------------
    d.decided_by          AS decided_by,
    d.decision_date       AS decision_date,
    o.observation_months  AS observation_months

FROM application a
JOIN  customer            c   ON c.id = a.customer_id
JOIN  household           h   ON h.application_id = a.id
JOIN  employment          e   ON e.application_id = a.id AND e.role = 'primary'
LEFT JOIN employment      eco ON eco.application_id = a.id AND eco.role = 'co_borrower'
JOIN  employment_contract ec  ON ec.code = e.contract_code
JOIN  account_behaviour   ab  ON ab.application_id = a.id
JOIN  indicators          ind ON ind.application_id = a.id
LEFT JOIN decision        d   ON d.application_id = a.id
LEFT JOIN outcome         o   ON o.application_id = a.id
LEFT JOIN counterfactual_outcome cf ON cf.application_id = a.id
LEFT JOIN inc   ON inc.application_id   = a.id
LEFT JOIN exp   ON exp.application_id   = a.id
LEFT JOIN loans ON loans.application_id = a.id
LEFT JOIN rsn   ON rsn.application_id   = a.id;

-- The dictionary-completeness check lives in checks.sql: SQLite forbids
-- pragma_* functions inside a view.

-- Class-balance monitor: declines and defaults are minority classes by
-- nature, and you need to be able to watch them.
CREATE VIEW v_class_balance AS
SELECT split,
       COUNT(*)                                                             AS applications,
       SUM(CASE WHEN decision_result = 'approved' THEN 1 ELSE 0 END)        AS approved,
       SUM(CASE WHEN decision_result = 'approved_with_conditions' THEN 1 ELSE 0 END)
                                                                            AS approved_with_conditions,
       SUM(CASE WHEN decision_result = 'declined' THEN 1 ELSE 0 END)        AS declined,
       SUM(CASE WHEN default_flag = 1 THEN 1 ELSE 0 END)                    AS defaults,
       ROUND(AVG(dti_after_pct), 2)                                         AS mean_dti_after,
       SUM(CASE WHEN above_hcsf_threshold = 1 THEN 1 ELSE 0 END)            AS above_hcsf
FROM v_dataset
GROUP BY split;
