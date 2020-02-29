DROP TABLE IF EXISTS oca_index_staging;
CREATE TABLE IF NOT EXISTS oca_index_staging (
	LIKE oca_index 
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);

DROP TABLE IF EXISTS oca_causes_staging;
CREATE TABLE IF NOT EXISTS oca_causes_staging (
	LIKE oca_causes 
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);

DROP TABLE IF EXISTS oca_addresses_staging;
CREATE TABLE IF NOT EXISTS oca_addresses_staging (
	LIKE oca_addresses 
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);

DROP TABLE IF EXISTS oca_parties_staging;
CREATE TABLE IF NOT EXISTS oca_parties_staging (
	LIKE oca_parties 
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);

DROP TABLE IF EXISTS oca_events_staging;
CREATE TABLE IF NOT EXISTS oca_events_staging (
	LIKE oca_events 
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);

DROP TABLE IF EXISTS oca_appearances_staging;
CREATE TABLE IF NOT EXISTS oca_appearances_staging (
	LIKE oca_appearances 
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);
-- This column is used only in the staging process to collect data
-- in json form then expand it out to populate the "appearance_outcomes" 
-- table via "update_apperance_outcomes.sql", and is delete afterwards.
ALTER TABLE oca_appearances_staging ADD COLUMN appearanceoutcomes json;

DROP TABLE IF EXISTS oca_appearance_outcomes_staging;
CREATE TABLE IF NOT EXISTS oca_appearance_outcomes_staging (
	LIKE oca_appearance_outcomes 
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);

DROP TABLE IF EXISTS oca_motions_staging;
CREATE TABLE IF NOT EXISTS oca_motions_staging (
	LIKE oca_motions 
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);

DROP TABLE IF EXISTS oca_decisions_staging;
CREATE TABLE IF NOT EXISTS oca_decisions_staging (
	LIKE oca_decisions 
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);

DROP TABLE IF EXISTS oca_judgments_staging;
CREATE TABLE IF NOT EXISTS oca_judgments_staging (
	LIKE oca_judgments 
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);

DROP TABLE IF EXISTS oca_warrants_staging;
CREATE TABLE IF NOT EXISTS oca_warrants_staging (
	LIKE oca_warrants 
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);
