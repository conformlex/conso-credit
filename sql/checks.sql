-- =====================================================================
-- Database coherence checks
--   sqlite3 credit.db < checks.sql
-- Any section returning rows flags a problem.
-- =====================================================================

.headers on
.mode column

.print '--- 1. v_dataset columns missing from the dictionary ---'
-- Must be empty: an undeclared column has no role, so no defined place in the
-- export. It would silently land in X, or nowhere at all.
SELECT p.name AS orphan_column
FROM pragma_table_info('v_dataset') p
LEFT JOIN variable_dictionary d ON d.column_name = p.name
WHERE d.column_name IS NULL;

.print ''
.print '--- 2. Dictionary entries with no matching column ---'
-- Must be empty: the trace of a column renamed or dropped from the view.
SELECT d.column_name AS stale_entry
FROM variable_dictionary d
LEFT JOIN pragma_table_info('v_dataset') p ON p.name = d.column_name
WHERE p.name IS NULL;

.print ''
.print '--- 3. Roles ---'
SELECT role, COUNT(*) AS columns
FROM variable_dictionary
GROUP BY role
ORDER BY role;

.print ''
.print '--- 4. Incomplete applications ---'
-- An application without a household, a primary employment record, account
-- behaviour, indicators or income is not usable.
SELECT a.reference,
       CASE WHEN h.application_id  IS NULL THEN 'household ' ELSE '' END ||
       CASE WHEN e.application_id  IS NULL THEN 'employment(primary) ' ELSE '' END ||
       CASE WHEN ab.application_id IS NULL THEN 'account_behaviour ' ELSE '' END ||
       CASE WHEN i.application_id  IS NULL THEN 'indicators ' ELSE '' END ||
       CASE WHEN NOT EXISTS (SELECT 1 FROM income inc WHERE inc.application_id = a.id)
            THEN 'income ' ELSE '' END AS missing_blocks
FROM application a
LEFT JOIN household h  ON h.application_id = a.id
LEFT JOIN employment e ON e.application_id = a.id AND e.role = 'primary'
LEFT JOIN account_behaviour ab ON ab.application_id = a.id
LEFT JOIN indicators i ON i.application_id = a.id
WHERE h.application_id IS NULL
   OR e.application_id IS NULL
   OR ab.application_id IS NULL
   OR i.application_id IS NULL
   OR NOT EXISTS (SELECT 1 FROM income inc WHERE inc.application_id = a.id);

.print ''
.print '--- 5. Co-borrower declared without employment record (and the reverse) ---'
SELECT a.reference,
       CASE WHEN a.co_borrower_id IS NOT NULL THEN 'co-borrower without employment record'
            ELSE 'co-borrower employment record without co-borrower' END AS problem
FROM application a
LEFT JOIN employment eco ON eco.application_id = a.id AND eco.role = 'co_borrower'
WHERE (a.co_borrower_id IS NOT NULL) <> (eco.application_id IS NOT NULL);

.print ''
.print '--- 6. Declines with no reason ---'
SELECT a.reference
FROM decision d
JOIN application a ON a.id = d.application_id
WHERE d.result = 'declined'
  AND NOT EXISTS (SELECT 1 FROM decision_reason r WHERE r.application_id = d.application_id);

.print ''
.print '--- 7. Business warnings (atypical files, non-blocking) ---'
-- These files must be allowed to exist: a dataset with no override at all
-- teaches arithmetic, not a trade. We watch them rather than forbid them.
SELECT a.reference, w.warning
FROM application a
JOIN (
    SELECT application_id, 'DTI above 35% approved without an override reason' AS warning
    FROM v_dataset v
    WHERE v.above_hcsf_threshold = 1
      AND v.decision_result IN ('approved', 'approved_with_conditions')
      AND NOT EXISTS (SELECT 1 FROM decision_reason dr
                      JOIN reason r ON r.code = dr.reason_code
                      WHERE dr.application_id = v.application_id AND r.category = 'override')
    UNION ALL
    SELECT application_id, 'approved despite an FICP flag'
    FROM v_dataset WHERE ficp_flagged = 1
      AND decision_result IN ('approved', 'approved_with_conditions')
    UNION ALL
    SELECT application_id, 'rationale shorter than 100 characters'
    FROM v_dataset WHERE rationale IS NOT NULL AND length(rationale) < 100
    UNION ALL
    SELECT application_id, 'approved application with no outcome recorded'
    FROM v_dataset WHERE decision_result IN ('approved', 'approved_with_conditions')
      AND outcome_status IS NULL
) w ON w.application_id = a.id;

.print ''
.print '--- 8. Class balance ---'
SELECT * FROM v_class_balance;
