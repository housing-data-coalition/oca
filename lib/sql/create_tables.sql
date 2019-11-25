
DROP TABLE IF EXISTS oca_index CASCADE;
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

DROP TABLE IF EXISTS oca_causes;
CREATE TABLE IF NOT EXISTS oca_causes (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  causeofactiontype text,
  interestfromdate date,
  amount numeric
);

DROP TABLE IF EXISTS oca_addresses;
CREATE TABLE IF NOT EXISTS oca_addresses (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  city text,
  state text,
  postalcode text
);

DROP TABLE IF EXISTS oca_parties;
CREATE TABLE IF NOT EXISTS oca_parties (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  role text,
  partytype text,
  representationtype text,
  undertenant text
);

DROP TABLE IF EXISTS oca_events;
CREATE TABLE IF NOT EXISTS oca_events (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  eventname text,
  fileddate date,
  feetype text,
  filingpartiesroles text[],
  answertype text
);

DROP TABLE IF EXISTS oca_appearances;
CREATE TABLE IF NOT EXISTS oca_appearances (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  appearanceid bigserial,
  appearancedatetime timestamp,
  appearancepurpose text,
  appearancereason text,
  appearancepart text,
  motionsequence int,
  appearanceoutcomes json -- will be dropped later
);

-- Created from "appearanceoutcomes" column in "oca_appearances" table 
-- by "update_apperance_outcomes.sql" after initial loading
DROP TABLE IF EXISTS oca_appearance_outcomes;
CREATE TABLE IF NOT EXISTS oca_appearance_outcomes (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  appearanceid bigint,
  appearanceoutcometype text,
  outcomebasedontype text
);

DROP TABLE IF EXISTS oca_motions;
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


DROP TABLE IF EXISTS oca_decisions;
CREATE TABLE IF NOT EXISTS oca_decisions (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  sequence int,
  resultof text,
  highlight text
);


DROP TABLE IF EXISTS oca_judgments;
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

DROP TABLE IF EXISTS oca_warrants;
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
