-- DuckDB Staging Tables

DROP TABLE IF EXISTS oca_index_staging;
CREATE TABLE IF NOT EXISTS oca_index_staging (
    indexnumberid VARCHAR PRIMARY KEY,
    court VARCHAR,
    fileddate DATE,
    propertytype VARCHAR,
    classification VARCHAR,
    specialtydesignationtypes VARCHAR[],
    status VARCHAR,
    disposeddate DATE,
    disposedreason VARCHAR,
    firstpaper VARCHAR,
    primaryclaimtotal DECIMAL,
    dateofjurydemand DATE
);

DROP TABLE IF EXISTS oca_causes_staging;
CREATE TABLE IF NOT EXISTS oca_causes_staging (
    indexnumberid VARCHAR,
    causeofactiontype VARCHAR,
    interestfromdate DATE,
    amount DECIMAL
);

DROP TABLE IF EXISTS oca_addresses_staging;
CREATE TABLE IF NOT EXISTS oca_addresses_staging (
    indexnumberid VARCHAR,
    street1 VARCHAR,
    street2 VARCHAR,
    city VARCHAR,
    state VARCHAR,
    postalcode VARCHAR,
    status VARCHAR,
    house_number VARCHAR,
    street_name VARCHAR,
    borough_code VARCHAR,
    place_name VARCHAR,
    sname VARCHAR,
    hnum VARCHAR,
    boro VARCHAR,
    lat REAL,
    bin VARCHAR,
    bbl VARCHAR,
    cd VARCHAR,
    ct VARCHAR,
    council VARCHAR,
    grc VARCHAR,
    grc2 VARCHAR,
    msg VARCHAR,
    msg2 VARCHAR,
    lon REAL,
    zip_code VARCHAR
);

DROP TABLE IF EXISTS oca_parties_staging;
CREATE TABLE IF NOT EXISTS oca_parties_staging (
    indexnumberid VARCHAR,
    role VARCHAR,
    partytype VARCHAR,
    representationtype VARCHAR,
    undertenant VARCHAR
);

DROP TABLE IF EXISTS oca_events_staging;
CREATE TABLE IF NOT EXISTS oca_events_staging (
    indexnumberid VARCHAR,
    eventname VARCHAR,
    fileddate DATE,
    feetype VARCHAR,
    filingpartiesroles VARCHAR[],
    answertype VARCHAR
);

DROP TABLE IF EXISTS oca_appearances_staging;
CREATE TABLE IF NOT EXISTS oca_appearances_staging (
    indexnumberid VARCHAR,
    appearanceid BIGINT,
    appearancedatetime TIMESTAMP,
    appearancepurpose VARCHAR,
    appearancereason VARCHAR,
    appearancepart VARCHAR,
    motionsequence INTEGER
);

-- This column is used only in the staging process to collect data
-- in json form then expand it out to populate the "appearance_outcomes"
-- table via "update_appearance_outcomes.sql", and is deleted afterwards.
ALTER TABLE oca_appearances_staging ADD COLUMN appearanceoutcomes JSON;

DROP TABLE IF EXISTS oca_appearance_outcomes_staging;
CREATE TABLE IF NOT EXISTS oca_appearance_outcomes_staging (
    indexnumberid VARCHAR,
    appearanceid BIGINT,
    appearanceoutcometype VARCHAR,
    outcomebasedontype VARCHAR
);

DROP TABLE IF EXISTS oca_motions_staging;
CREATE TABLE IF NOT EXISTS oca_motions_staging (
    indexnumberid VARCHAR,
    sequence INTEGER,
    motiontype VARCHAR,
    primaryrelief VARCHAR,
    fileddate DATE,
    filingpartiesroles VARCHAR[],
    motiondecision VARCHAR,
    motiondecisiondate DATE
);

DROP TABLE IF EXISTS oca_decisions_staging;
CREATE TABLE IF NOT EXISTS oca_decisions_staging (
    indexnumberid VARCHAR,
    sequence INTEGER,
    resultof VARCHAR,
    highlight VARCHAR
);

DROP TABLE IF EXISTS oca_judgments_staging;
CREATE TABLE IF NOT EXISTS oca_judgments_staging (
    indexnumberid VARCHAR,
    sequence INTEGER,
    amendedfromjudgmentsequence INTEGER,
    judgmenttype VARCHAR,
    fileddate DATE,
    entereddatetime TIMESTAMP,
    withpossession BOOLEAN,
    latestjudgmentstatus VARCHAR,
    latestjudgmentstatusdate DATE,
    totaljudgmentamount DECIMAL,
    creditorsroles VARCHAR[],
    debtorsroles VARCHAR[]
);

DROP TABLE IF EXISTS oca_warrants_staging;
CREATE TABLE IF NOT EXISTS oca_warrants_staging (
    indexnumberid VARCHAR,
    judgmentsequence INTEGER,
    sequence VARCHAR,
    createdreason VARCHAR,
    ordereddate DATE,
    issuancetype VARCHAR,
    issuancestayeddate DATE,
    issuancestayeddays INTEGER,
    issueddate DATE,
    executiontype VARCHAR,
    executionstayeddate DATE,
    executionstayeddays INTEGER,
    marshalrequestdate DATE,
    marshalrequestrevieweddate DATE,
    enforcementagency VARCHAR,
    enforcementofficerdocketnumber VARCHAR,
    propertiesonwarrantcities VARCHAR[],
    propertiesonwarrantstates VARCHAR[],
    propertiesonwarrantpostalcodes VARCHAR[],
    amendeddate DATE,
    vacateddate DATE,
    adultprotectiveservicesnumber VARCHAR,
    returneddate DATE,
    returnedreason VARCHAR,
    executiondate DATE
);

DROP TABLE IF EXISTS oca_metadata_staging;
CREATE TABLE IF NOT EXISTS oca_metadata_staging (
    indexnumberid VARCHAR PRIMARY KEY,
    initialdate DATE,
    updatedate DATE,
    deletedate DATE
);

-- indexes
CREATE INDEX IF NOT EXISTS idx_oca_causes_staging_indexnumberid ON oca_causes_staging (indexnumberid);
CREATE INDEX IF NOT EXISTS idx_oca_addresses_staging_indexnumberid ON oca_addresses_staging (indexnumberid);
CREATE INDEX IF NOT EXISTS idx_oca_addresses_staging_bbl ON oca_addresses_staging (bbl);
CREATE INDEX IF NOT EXISTS idx_oca_parties_staging_indexnumberid ON oca_parties_staging (indexnumberid);
CREATE INDEX IF NOT EXISTS idx_oca_events_staging_indexnumberid ON oca_events_staging (indexnumberid);
CREATE INDEX IF NOT EXISTS idx_oca_appearances_staging_indexnumberid ON oca_appearances_staging (indexnumberid);
CREATE INDEX IF NOT EXISTS idx_oca_appearance_outcomes_staging_indexnumberid ON oca_appearance_outcomes_staging (indexnumberid);
CREATE INDEX IF NOT EXISTS idx_oca_motions_staging_indexnumberid ON oca_motions_staging (indexnumberid);
CREATE INDEX IF NOT EXISTS idx_oca_decisions_staging_indexnumberid ON oca_decisions_staging (indexnumberid);
CREATE INDEX IF NOT EXISTS idx_oca_judgments_staging_indexnumberid ON oca_judgments_staging (indexnumberid);
CREATE INDEX IF NOT EXISTS idx_oca_warrants_staging_indexnumberid ON oca_warrants_staging (indexnumberid);
CREATE INDEX IF NOT EXISTS idx_oca_metadata_staging_indexnumberid ON oca_metadata_staging (indexnumberid);