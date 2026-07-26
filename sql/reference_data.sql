-- =====================================================================
-- Reference data + variable dictionary
-- Load after schema.sql
-- =====================================================================

-- ---------------------------------------------------------------------
-- Consumer loan products
-- ---------------------------------------------------------------------
INSERT INTO loan_type (code, label) VALUES
    ('PERSONAL_LOAN',       'Unsecured personal loan'),
    ('AUTO',                'Car or motorcycle loan'),
    ('HOME_IMPROVEMENT',    'Home improvement loan'),
    ('REVOLVING',           'Revolving credit'),
    ('DEBT_CONSOLIDATION',  'Debt consolidation'),
    ('LEASE_TO_OWN',        'Lease with purchase option');

-- ---------------------------------------------------------------------
-- Employment contracts (French labour law, translated)
-- ---------------------------------------------------------------------
INSERT INTO employment_contract (code, label, stability) VALUES
    ('PERMANENT',     'Permanent contract, probation passed (CDI)', 'stable'),
    ('CIVIL_SERVANT', 'Tenured civil servant',                      'stable'),
    ('RETIRED',       'Retired',                                    'stable'),
    ('FIXED_TERM',    'Fixed-term contract (CDD)',                  'intermediate'),
    ('SELF_EMPLOYED', 'Self-employed / liberal profession',         'intermediate'),
    ('TEMP_AGENCY',   'Temporary agency work (interim)',            'precarious'),
    ('APPRENTICE',    'Apprentice or work-study',                   'precarious'),
    ('UNEMPLOYED',    'Not in employment',                          'precarious');

-- ---------------------------------------------------------------------
-- Housing status
-- ---------------------------------------------------------------------
INSERT INTO housing_status (code, label, rent_expected) VALUES
    ('OWNER_OUTRIGHT',      'Owner, no mortgage outstanding', 0),
    ('OWNER_WITH_MORTGAGE', 'Owner with an outstanding mortgage', 0),
    ('TENANT',              'Tenant', 1),
    ('HOUSED_FREE',         'Housed free of charge', 0),
    ('EMPLOYER_HOUSING',    'Employer-provided housing', 0);

-- ---------------------------------------------------------------------
-- Occupation categories (simplified French CSP nomenclature)
-- ---------------------------------------------------------------------
INSERT INTO occupation (code, label) VALUES
    ('FARMER',                'Farmer'),
    ('SELF_EMPLOYED_TRADE',   'Craftsman, shopkeeper, business owner'),
    ('MANAGER_PROFESSIONAL',  'Manager or higher professional'),
    ('INTERMEDIATE',          'Intermediate profession'),
    ('CLERICAL',              'Clerical or service employee'),
    ('MANUAL_WORKER',         'Manual worker'),
    ('RETIRED',               'Retired'),
    ('STUDENT',               'Student'),
    ('INACTIVE',              'Not economically active');

-- ---------------------------------------------------------------------
-- Income types and their usual weighting
-- ---------------------------------------------------------------------
-- The default weight reflects French underwriting practice: variable or
-- rental income is rarely counted at 100%.
INSERT INTO income_type (code, label, default_weight, family) VALUES
    ('SALARY',               'Net monthly salary',                     1.00, 'salary'),
    ('CIVIL_SERVICE_PAY',    'Civil service pay',                      1.00, 'salary'),
    ('GUARANTEED_BONUS',     'Contractual guaranteed bonus',           1.00, 'bonus'),
    ('VARIABLE_BONUS',       'Variable bonus or commission',           0.70, 'bonus'),
    ('OVERTIME',             'Recurring overtime',                     0.70, 'bonus'),
    ('FAMILY_BENEFITS',      'Family allowances',                      1.00, 'benefits'),
    ('HOUSING_BENEFIT',      'Housing benefit (APL)',                  0.00, 'benefits'),
    ('UNEMPLOYMENT_BENEFIT', 'Unemployment benefit',                   0.00, 'benefits'),
    ('PENSION',              'Retirement pension',                     1.00, 'pension'),
    ('DISABILITY_PENSION',   'Disability pension',                     1.00, 'pension'),
    ('ALIMONY_RECEIVED',     'Alimony received',                       0.80, 'pension'),
    ('RENTAL_INCOME',        'Rental income',                          0.70, 'rental'),
    ('SELF_EMPLOYED_PROFIT', 'Self-employment profit (BNC/BIC)',       0.90, 'other'),
    ('OTHER_INCOME',         'Other income',                           0.50, 'other');

-- ---------------------------------------------------------------------
-- Expense types
-- ---------------------------------------------------------------------
INSERT INTO expense_type (code, label, family) VALUES
    ('RENT',          'Rent excluding service charges', 'rent'),
    ('ALIMONY_PAID',  'Alimony paid',                   'alimony'),
    ('MONTHLY_TAX',   'Income tax paid monthly',        'tax'),
    ('OTHER_EXPENSE', 'Other recurring expense',        'other');

-- ---------------------------------------------------------------------
-- Decision reasons
-- ---------------------------------------------------------------------
INSERT INTO reason (code, label, polarity, category) VALUES
    -- affordability
    ('EXCESSIVE_DTI',           'Debt-to-income ratio above the threshold',     'adverse',    'affordability'),
    ('LOW_RESIDUAL_INCOME',     'Residual income per consumption unit too low', 'adverse',    'affordability'),
    ('HIGH_PAYMENT_SHOCK',      'Payment shock too large',                      'adverse',    'affordability'),
    ('COMFORTABLE_DTI',         'Comfortable debt-to-income ratio',             'favourable', 'affordability'),
    ('AMPLE_RESIDUAL_INCOME',   'Ample residual income',                        'favourable', 'affordability'),
    -- income
    ('INSUFFICIENT_INCOME',     'Income insufficient for the amount requested', 'adverse',    'income'),
    ('TOO_MUCH_VARIABLE_PAY',   'Variable share of income too high',            'adverse',    'income'),
    ('UNDOCUMENTED_INCOME',     'Declared income not evidenced',                'adverse',    'income'),
    ('SOLID_INCOME',            'Stable and fully evidenced income',            'favourable', 'income'),
    -- stability
    ('PRECARIOUS_CONTRACT',     'Precarious employment contract',               'adverse',    'stability'),
    ('PROBATION_PERIOD',        'Borrower still in probation period',           'adverse',    'stability'),
    ('SHORT_JOB_TENURE',        'Insufficient time in current job',             'adverse',    'stability'),
    ('RECENT_MOVE',             'Very recent move to current address',          'adverse',    'stability'),
    ('STABLE_EMPLOYMENT',       'Stable employment situation',                  'favourable', 'stability'),
    -- behaviour
    ('PAYMENT_INCIDENTS',       'Payment incidents in the last 12 months',      'adverse',    'behaviour'),
    ('HEAVY_OVERDRAFT_USE',     'Recurring use of the overdraft',               'adverse',    'behaviour'),
    ('LOAN_INCIDENTS',          'Incidents on existing loans',                  'adverse',    'behaviour'),
    ('MULTIPLE_REVOLVING',      'Several revolving credit lines held',          'adverse',    'behaviour'),
    ('SOLID_SAVINGS',           'Sufficient precautionary savings',             'favourable', 'behaviour'),
    ('CLEAN_HISTORY',           'No incident over the observed period',         'favourable', 'behaviour'),
    ('LONG_RELATIONSHIP',       'Long-standing banking relationship',           'favourable', 'behaviour'),
    ('SALARY_DOMICILED',        'Salary paid into an account with the lender',  'favourable', 'behaviour'),
    ('LOANS_REPAID_CLEAN',      'Previous loans repaid without incident',       'favourable', 'behaviour'),
    -- collateral
    ('SOLID_CO_BORROWER',       'Co-borrower provides real support',            'favourable', 'collateral'),
    ('MEANINGFUL_DOWN_PAYMENT', 'Meaningful down payment',                      'favourable', 'collateral'),
    ('NO_SECURITY',             'Neither down payment nor security',            'adverse',    'collateral'),
    -- regulatory
    ('FICP_FLAG',               'Registered on the FICP incident file',         'adverse',    'regulatory'),
    ('FCC_FLAG',                'Registered on the FCC cheque incident file',   'adverse',    'regulatory'),
    ('ABOVE_USURY_RATE',        'APR above the applicable usury ceiling',       'adverse',    'regulatory'),
    -- override: justifies approving despite an out-of-policy indicator
    ('OVERRIDE_WEALTH',         'Override justified by assets held',            'favourable', 'override'),
    ('OVERRIDE_RELATIONSHIP',   'Override justified by customer history',       'favourable', 'override'),
    ('OVERRIDE_COMMERCIAL',     'Commercial override granted',                  'favourable', 'override');

-- =====================================================================
-- VARIABLE DICTIONARY
-- One row per v_dataset column. Drives the export:
--   feature -> X      target -> y      protected -> bias audit
--   meta    -> neither (traceability)
-- The orphan-column check in checks.sql must stay empty.
-- =====================================================================

INSERT INTO variable_dictionary (column_name, label, data_type, role, categories, unit, description) VALUES

-- ---- meta -----------------------------------------------------------
('application_id',        'Technical application id',   'integer',     'meta', NULL, NULL, 'Primary key of the application.'),
('application_reference', 'Application reference',      'text',        'meta', NULL, NULL, 'Business reference APP-YYYY-NNNNNN.'),
('customer_reference',    'Customer reference',         'text',        'meta', NULL, NULL, 'Lets several applications from the same customer be grouped.'),
('application_date',      'Application date',           'date',        'meta', NULL, NULL, 'Reference date for every snapshot on the file.'),
('split',                 'Dataset partition',          'categorical', 'meta', 'train|val|test', NULL, 'Assigned at creation, never redrawn at export: this is what makes runs comparable.'),
('source',                'Record origin',              'categorical', 'meta', 'manual|generated', NULL, 'Separates hand-written reference cases from generated volume.'),
('formula_version',       'Indicator formula version',  'text',        'meta', NULL, NULL, 'Lets a formula evolve without invalidating earlier rows.'),
('decided_by',            'Decision origin',            'categorical', 'meta', 'human|rule_engine|llm', NULL, 'Useful to measure the gap between human and automated decisions, and to audit LLM-written text.'),
('decision_date',         'Decision date',              'date',        'meta', NULL, NULL, 'Always on or after the application date.'),
('observation_months',    'Outcome observation window', 'integer',     'meta', NULL, 'months', 'How much hindsight exists on an approved loan: an outcome seen over 3 months is not an outcome seen over 36.'),

-- ---- protected attributes: kept for bias auditing, excluded from features ----
('age',              'Age at application', 'integer',     'protected', NULL, 'years', 'Protected attribute. Kept to measure model bias, excluded from inputs.'),
('sex',              'Sex',                'categorical', 'protected', 'M|F|NR', NULL, 'Protected attribute; using it in credit scoring is unlawful in France.'),
('nationality_zone', 'Nationality zone',   'categorical', 'protected', 'FR|EU|NON_EU', NULL, 'Protected attribute; using it in credit scoring is unlawful in France.'),
('marital_status',   'Marital status',     'categorical', 'protected', 'single|married|civil_union|cohabiting|divorced|widowed', NULL, 'Protected attribute. Household size carries the useful economic signal instead.'),

-- ---- the operation -----------------------------------------------------
('channel',                'Origination channel',        'categorical', 'feature', 'branch|online|broker|point_of_sale', NULL, 'Channel correlates with risk: point-of-sale lending concentrates impulse applications.'),
('loan_type',              'Loan product',               'categorical', 'feature', NULL, NULL, 'References the loan_type table.'),
('requested_amount',       'Requested amount',           'numeric',     'feature', NULL, 'EUR', 'Principal requested, excluding insurance.'),
('term_months',            'Requested term',             'integer',     'feature', NULL, 'months', 'A long term lowers the payment but raises total cost and exposure.'),
('nominal_rate',           'Nominal rate',               'numeric',     'feature', NULL, '%', 'Annual borrowing rate excluding fees.'),
('apr',                    'Annual percentage rate',     'numeric',     'feature', NULL, '%', 'French TAEG: all-in annual rate including fees.'),
('payment_excl_insurance', 'Payment excluding insurance','numeric',     'feature', NULL, 'EUR', 'Monthly principal and interest instalment.'),
('insurance_taken',        'Borrower insurance taken',   'boolean',     'feature', '0|1', NULL, 'Optional on consumer credit; reduces loss given a claim.'),
('monthly_insurance_cost', 'Monthly insurance cost',     'numeric',     'feature', NULL, 'EUR', 'Zero when no insurance is taken.'),
('monthly_payment',        'Total monthly payment',      'numeric',     'feature', NULL, 'EUR', 'Instalment plus insurance. Enters the debt-to-income ratio.'),
('down_payment',           'Down payment',               'numeric',     'feature', NULL, 'EUR', 'Amount funded by the borrower from own resources.'),
('down_payment_ratio',     'Down payment ratio',         'numeric',     'feature', NULL, 'ratio', 'Down payment over requested amount.'),
('has_co_borrower',        'Co-borrower present',        'boolean',     'feature', '0|1', NULL, 'A co-borrower pools the risk and raises household income.'),

-- ---- household and housing ------------------------------------------------
('household_size',      'Household size',              'integer',     'feature', NULL, 'people', 'Carries the household economics without using marital status.'),
('dependent_children',  'Dependent children',          'integer',     'feature', NULL, 'children', 'Feeds the consumption-unit calculation.'),
('housing_status',      'Housing status',              'categorical', 'feature', NULL, NULL, 'An outright owner has neither rent nor a mortgage payment.'),
('months_at_address',   'Months at current address',   'integer',     'feature', NULL, 'months', 'Residential stability indicator.'),
('department',          'Department of residence',     'categorical', 'feature', NULL, NULL, 'Geographic indicator. Watch it: it can proxy for protected attributes.'),
('area_type',           'Area type',                   'categorical', 'feature', 'urban|suburban|rural', NULL, 'Correlates with rent levels and mobility needs.'),

-- ---- employment -------------------------------------------------------------
('occupation',                'Occupation category',        'categorical', 'feature', NULL, NULL, 'Simplified nomenclature, primary applicant.'),
('contract_type',             'Employment contract',        'categorical', 'feature', NULL, NULL, 'Primary applicant.'),
('contract_stability',        'Contract stability tier',    'categorical', 'feature', 'stable|intermediate|precarious', NULL, 'Derived from the reference table: groups contracts into three security tiers.'),
('months_in_job',             'Months in current job',      'integer',     'feature', NULL, 'months', 'Primary applicant.'),
('in_probation_period',       'In probation period',        'boolean',     'feature', '0|1', NULL, 'A permanent contract still in probation does not offer the security of a confirmed one.'),
('industry',                  'Industry',                   'categorical', 'feature', NULL, NULL, 'Free text; normalise before modelling.'),
('employer_type',             'Employer type',              'categorical', 'feature', 'private|public|self_employed', NULL, 'Primary applicant.'),
('co_borrower_contract',      'Co-borrower contract',       'categorical', 'feature', NULL, NULL, 'Null when there is no co-borrower.'),
('co_borrower_months_in_job', 'Co-borrower months in job',  'integer',     'feature', NULL, 'months', 'Null when there is no co-borrower.'),
('relationship_months',       'Banking relationship length','integer',     'feature', NULL, 'months', 'Computed at application date. A long history gives visibility on behaviour.'),

-- ---- income ------------------------------------------------------------------
('income_salary',             'Salary income',              'numeric','feature', NULL, 'EUR/month', 'Household salaries and civil service pay, before weighting.'),
('income_bonus',              'Bonuses and variable pay',   'numeric','feature', NULL, 'EUR/month', 'Bonuses, commissions and overtime, before weighting.'),
('income_benefits',           'Benefits',                   'numeric','feature', NULL, 'EUR/month', 'Family allowances, housing benefit, unemployment benefit, before weighting.'),
('income_pension',            'Pensions',                   'numeric','feature', NULL, 'EUR/month', 'Retirement, disability, alimony received.'),
('income_rental',             'Rental income',              'numeric','feature', NULL, 'EUR/month', 'Rental income, counted at 70% by default.'),
('income_other',              'Other income',               'numeric','feature', NULL, 'EUR/month', 'Self-employment profit and miscellaneous income.'),
('income_co_borrower',        'Co-borrower income',         'numeric','feature', NULL, 'EUR/month', 'Share of income contributed by the co-borrower.'),
('undocumented_income_lines', 'Undocumented income lines',  'integer','feature', NULL, 'lines', 'Income declared without evidence weakens the file.'),
('gross_income',              'Total declared income',      'numeric','feature', NULL, 'EUR/month', 'Gross sum, before weightings are applied.'),
('weighted_income',           'Total weighted income',      'numeric','feature', NULL, 'EUR/month', 'Basis for the debt-to-income ratio. Each line is counted at its own weight.'),
('variable_income_share',     'Variable income share',      'numeric','feature', NULL, 'ratio', 'A high share weakens repayment capacity.'),

-- ---- expenses -------------------------------------------------------------------
('expense_rent',     'Rent',                  'numeric','feature', NULL, 'EUR/month', 'Rent excluding service charges, counted in the ratio.'),
('expense_alimony',  'Alimony paid',          'numeric','feature', NULL, 'EUR/month', 'Deducted from disposable income.'),
('expense_tax',      'Income tax paid monthly','numeric','feature', NULL, 'EUR/month', 'Counted when paid on a monthly schedule.'),
('expense_other',    'Other expenses',        'numeric','feature', NULL, 'EUR/month', 'Miscellaneous recurring expenses.'),
('counted_expenses', 'Total counted expenses','numeric','feature', NULL, 'EUR/month', 'Only lines flagged as counted enter the ratio.'),

-- ---- existing loans ----------------------------------------------------------------
('existing_loans',            'Existing loans',              'integer','feature', NULL, 'loans', 'All kinds, before this operation.'),
('existing_loan_payments',    'Existing loan payments',      'numeric','feature', NULL, 'EUR/month', 'Sum of instalments on existing loans.'),
('outstanding_balance_total', 'Total outstanding balance',   'numeric','feature', NULL, 'EUR', 'Overall exposure before this operation.'),
('revolving_loans',           'Revolving credit lines',      'integer','feature', NULL, 'loans', 'Holding several revolving lines signals cash-flow strain.'),
('loans_refinanced',          'Loans repaid by this operation','integer','feature', NULL, 'loans', 'Their instalments drop out of the post-loan ratio.'),
('loan_incidents_12m',        'Loan incidents (12 months)',  'integer','feature', NULL, 'incidents', 'Total incidents recorded on existing loans.'),
('longest_remaining_months',  'Longest remaining term',      'integer','feature', NULL, 'months', 'Furthest commitment horizon before this operation.'),
('retained_payments',         'Payments retained after loan','numeric','feature', NULL, 'EUR/month', 'Instalments on loans not refinanced. Basis of the post-loan ratio.'),

-- ---- account behaviour ---------------------------------------------------------------
('average_balance',      'Average account balance',   'numeric','feature', NULL, 'EUR', 'May be negative. A structurally negative balance is a strong signal.'),
('days_overdrawn_12m',   'Days overdrawn',            'integer','feature', NULL, 'days', 'Over the last 12 months.'),
('rejected_debits_12m',  'Rejected direct debits',    'integer','feature', NULL, 'rejections', 'Over the last 12 months.'),
('overdraft_fees_12m',   'Overdraft intervention fees','integer','feature', NULL, 'events', 'Direct marker of cash-flow strain.'),
('overdraft_limit',      'Authorised overdraft',      'numeric','feature', NULL, 'EUR', 'Limit granted by the lender.'),
('max_overdraft_used',   'Peak overdraft used',       'numeric','feature', NULL, 'EUR', 'Highest usage over the last 12 months.'),
('liquid_savings',       'Liquid savings',            'numeric','feature', NULL, 'EUR', 'Immediately available savings accounts.'),
('total_savings',        'Total savings',             'numeric','feature', NULL, 'EUR', 'Liquid and locked savings combined.'),
('products_held',        'Products held',             'integer','feature', NULL, 'products', 'Depth of the commercial relationship.'),
('salary_domiciled',     'Salary domiciled',          'boolean','feature', '0|1', NULL, 'Domiciliation gives the lender real visibility on cash flows.'),
('ficp_flagged',         'FICP registration',         'boolean','feature', '0|1', NULL, 'Banque de France register of consumer credit repayment incidents.'),
('fcc_flagged',          'FCC registration',          'boolean','feature', '0|1', NULL, 'Banque de France central cheque incident register.'),
('loans_repaid_clean',   'Previous loans repaid clean','integer','feature', NULL, 'loans', 'Positive history, rarely captured by models fed only on incidents.'),

-- ---- computed indicators ---------------------------------------------------------------
('dti_before_pct',             'Debt-to-income before',      'numeric','feature', NULL, '%', 'Existing expenses and instalments over weighted income.'),
('dti_after_pct',              'Debt-to-income after',       'numeric','feature', NULL, '%', 'Includes the new instalment and drops loans refinanced by the operation.'),
('above_hcsf_threshold',       'Above the 35% threshold',    'boolean','feature', '0|1', NULL, 'True when the post-loan ratio exceeds the 35% HCSF cap.'),
('consumption_units',          'Household consumption units','numeric','feature', NULL, 'CU', 'Modified OECD scale: 1 for the first adult, 0.5 per further person aged 14+, 0.3 per child under 14.'),
('residual_income',            'Residual income',            'numeric','feature', NULL, 'EUR/month', 'Weighted income less expenses and post-loan instalments.'),
('residual_income_per_cu',     'Residual income per CU',     'numeric','feature', NULL, 'EUR/month', 'The only measure comparable between a single person and a family of five.'),
('payment_shock',              'Payment shock',              'numeric','feature', NULL, 'EUR/month', 'Net increase in credit burden: new instalment less instalments refinanced. Negative on a consolidation that relieves the household.'),
('savings_months_of_expenses', 'Savings in months of expenses','numeric','feature', NULL, 'months', 'Capacity to absorb an income shock.'),

-- ---- targets ----------------------------------------------------------------------------
('decision_result',             'Decision',                    'categorical','target', 'approved|approved_with_conditions|declined|deferred', NULL, 'Primary classification target.'),
('risk_score',                  'Risk score',                  'integer',    'target', '0-100', 'points', 'Score assigned to the file. Regression target.'),
('risk_grade',                  'Risk grade',                  'categorical','target', 'A|B|C|D|E', NULL, 'Discretised score.'),
('approved_amount',             'Approved amount',             'numeric',    'target', NULL, 'EUR', 'May differ from the amount requested (counter-offer). Null when declined.'),
('approved_term_months',        'Approved term',               'integer',    'target', NULL, 'months', 'May differ from the term requested. Null when declined.'),
('conditions',                  'Conditions attached',         'text',       'target', NULL, NULL, 'Populated only on a conditional approval.'),
('rationale',                   'Written rationale',           'text',       'target', NULL, NULL, 'Free-text explanation of the decision, in French: supervision signal for an explanation layer.'),
('reasons',                     'Coded reasons',               'text',       'target', NULL, NULL, 'Reason codes joined by |. Structured counterpart of the rationale.'),
('adverse_reasons',             'Adverse reason count',        'integer',    'target', NULL, 'reasons', 'Number of reasons with adverse polarity.'),
('favourable_reasons',          'Favourable reason count',     'integer',    'target', NULL, 'reasons', 'Number of reasons with favourable polarity.'),
('outcome_status',              'Observed outcome',            'categorical','target', 'ongoing|repaid_clean|minor_incidents|default|early_repayment', NULL, 'What actually happened after disbursement. Null when the loan was not granted.'),
('default_flag',                'Default observed',            'boolean',    'target', '0|1', NULL, 'Binary realised-risk target. NULL when the loan was not granted AND while it is still running (right censoring): never impute 0.'),
('counterfactual_default_flag', 'Counterfactual default',      'boolean',    'target', '0|1', NULL, 'What would have happened had the declined application been granted. Exists ONLY because the data is synthetic; unobtainable in production. For measuring selection bias and testing reject inference, never for training a model claimed to be reproducible.'),
('outcome_missed_payments',     'Missed payments',             'integer',    'target', NULL, 'payments', 'Instalments missed over the observation window.'),
('outcome_sent_to_collections', 'Sent to collections',         'boolean',    'target', '0|1', NULL, 'Terminal stage of default.'),
('outcome_balance_at_default',  'Balance at default',          'numeric',    'target', NULL, 'EUR', 'Loss base. Populated only on a default.');
