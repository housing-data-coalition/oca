-- Post-import staging normalization (deterministic casts / null coercion).
-- Array bracket formatting is handled in lib/etl_csv.py before S3 import.

UPDATE oca_appearances_staging
SET motionsequence = NULL
WHERE motionsequence IS NOT NULL AND motionsequence::text = '';

UPDATE oca_judgments_staging
SET amendedfromjudgmentsequence = NULL
WHERE amendedfromjudgmentsequence IS NOT NULL AND amendedfromjudgmentsequence::text = '';

UPDATE oca_warrants_staging
SET executionstayeddays = NULL
WHERE executionstayeddays IS NOT NULL AND executionstayeddays::text = '';

UPDATE oca_warrants_staging
SET issuancestayeddays = NULL
WHERE issuancestayeddays IS NOT NULL AND issuancestayeddays::text = '';
