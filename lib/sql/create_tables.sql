CREATE TABLE IF NOT EXISTS oca_index (
	indexnumberid text PRIMARY KEY,
	court text,
	fileddate date,
	propertytype text,
	classification text,
	specialtydesignationtypes text[],
	status text,
	disposeddate date,
	disposedreason text,
	firstpaper text,
	primaryclaimtotal numeric,
	dateofjurydemand date
);

CREATE TABLE IF NOT EXISTS oca_causes (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  causeofactiontype text,
  interestfromdate date,
  amount numeric
);

CREATE TABLE IF NOT EXISTS oca_addresses (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
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

CREATE TABLE IF NOT EXISTS oca_parties (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  role text,
  partytype text,
  representationtype text,
  undertenant text
);

CREATE TABLE IF NOT EXISTS oca_events (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  eventname text,
  fileddate date,
  feetype text,
  filingpartiesroles text[],
  answertype text
);

CREATE TABLE IF NOT EXISTS oca_appearances (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  appearanceid bigserial,
  appearancedatetime timestamp,
  appearancepurpose text,
  appearancereason text,
  appearancepart text,
  motionsequence int
);

CREATE TABLE IF NOT EXISTS oca_appearance_outcomes (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  appearanceid bigint,
  appearanceoutcometype text,
  outcomebasedontype text
);

CREATE TABLE IF NOT EXISTS oca_motions (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  sequence int,
  motiontype text,
  primaryrelief text,
  fileddate date,
  filingpartiesroles text[],
  motiondecision text,
  motiondecisiondate date
);


CREATE TABLE IF NOT EXISTS oca_decisions (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  sequence int,
  resultof text,
  highlight text
);


CREATE TABLE IF NOT EXISTS oca_judgments (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  sequence int,
  amendedfromjudgmentsequence int,
  judgmenttype text,
  fileddate date,
  entereddatetime timestamp,
  withpossession boolean,
  latestjudgmentstatus text,
  latestjudgmentstatusdate date,
  totaljudgmentamount numeric,
  creditorsroles text[],
  debtorsroles text[]
);

CREATE TABLE IF NOT EXISTS oca_warrants (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  judgmentsequence int,
  sequence text,
  createdreason text,
  ordereddate date,
  issuancetype text,
  issuancestayeddate date,
  issuancestayeddays int,
  issueddate date,
  executiontype text,
  executionstayeddate date,
  executionstayeddays int,
  marshalrequestdate date,
  marshalrequestrevieweddate date,
  enforcementagency text,
  enforcementofficerdocketnumber text,
  propertiesonwarrantcities text[],
  propertiesonwarrantstates text[],
  propertiesonwarrantpostalcodes text[],
  amendeddate date,
  vacateddate date,
  adultprotectiveservicesnumber text,
  returneddate date,
  returnedreason text,
  executiondate date
);

CREATE TABLE IF NOT EXISTS oca_metadata (
  -- we don't want to delete records here when deleted from others
	indexnumberid text PRIMARY KEY,
  initialdate date,
  updatedate date,
  deletedate date
);


CREATE INDEX IF NOT EXISTS oca_causes_indexnumberid_idx ON oca_causes (indexnumberid);
CREATE INDEX IF NOT EXISTS oca_addresses_indexnumberid_idx ON oca_addresses (indexnumberid);
CREATE INDEX IF NOT EXISTS oca_addresses_bbl_idx ON oca_addresses (bbl);
CREATE INDEX IF NOT EXISTS oca_parties_indexnumberid_idx ON oca_parties (indexnumberid);
CREATE INDEX IF NOT EXISTS oca_events_indexnumberid_idx ON oca_events (indexnumberid);
CREATE INDEX IF NOT EXISTS oca_appearances_indexnumberid_idx ON oca_appearances (indexnumberid);
CREATE INDEX IF NOT EXISTS oca_appearance_outcomes_indexnumberid_idx ON oca_appearance_outcomes (indexnumberid);
CREATE INDEX IF NOT EXISTS oca_motions_indexnumberid_idx ON oca_motions (indexnumberid);
CREATE INDEX IF NOT EXISTS oca_decisions_indexnumberid_idx ON oca_decisions (indexnumberid);
CREATE INDEX IF NOT EXISTS oca_judgments_indexnumberid_idx ON oca_judgments (indexnumberid);
CREATE INDEX IF NOT EXISTS oca_warrants_indexnumberid_idx ON oca_warrants (indexnumberid);
CREATE INDEX IF NOT EXISTS oca_metadata_indexnumberid_idx ON oca_metadata (indexnumberid);
