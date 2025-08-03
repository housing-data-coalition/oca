DROP TABLE IF EXISTS oca_index_staging CASCADE;
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

-- hardcode oca_addresses since some versions of this table can have geom
DROP TABLE IF EXISTS oca_addresses_staging;
CREATE TABLE IF NOT EXISTS oca_addresses_staging (
  indexnumberid text,
  street1 text,
  street2 text,
  city text,
  state text,
  postalcode text,
  status text,
  house_number text,
  street_name text,
  borough_code text,
  place_name text,
  sname text,
  hnum text,
  boro text,
  lat real,
  bin text,
  bbl text,
  cd text,
  ct text,
  council text,
  grc text,
  grc2 text,
  msg text,
  msg2 text,
  lon real,
  zip_code text
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

-- Avoid adding an appearanceid, have postgresql generate one when it is inserted into the main table
ALTER TABLE oca_appearances_staging DROP COLUMN appearanceid;

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

DROP TABLE IF EXISTS oca_metadata_staging;
CREATE TABLE IF NOT EXISTS oca_metadata_staging (
	LIKE oca_metadata
	INCLUDING DEFAULTS
	INCLUDING INDEXES
);