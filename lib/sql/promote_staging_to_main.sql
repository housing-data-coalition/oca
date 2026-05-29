-- Atomic staging -> main promotion for one import batch.
-- Case scope: all indexnumberid values present in oca_index_staging.
-- oca_index uses UPSERT; child tables use scoped DELETE + INSERT; metadata merged last.

SET session_replication_role = replica;

-- Child tables keyed by indexnumberid (full per-case row replace for the batch).
DELETE FROM oca_appearance_outcomes
WHERE indexnumberid IN (SELECT indexnumberid FROM oca_index_staging);

DELETE FROM oca_appearances
WHERE indexnumberid IN (SELECT indexnumberid FROM oca_index_staging);

DELETE FROM oca_warrants
WHERE indexnumberid IN (SELECT indexnumberid FROM oca_index_staging);

DELETE FROM oca_judgments
WHERE indexnumberid IN (SELECT indexnumberid FROM oca_index_staging);

DELETE FROM oca_decisions
WHERE indexnumberid IN (SELECT indexnumberid FROM oca_index_staging);

DELETE FROM oca_motions
WHERE indexnumberid IN (SELECT indexnumberid FROM oca_index_staging);

DELETE FROM oca_events
WHERE indexnumberid IN (SELECT indexnumberid FROM oca_index_staging);

DELETE FROM oca_parties
WHERE indexnumberid IN (SELECT indexnumberid FROM oca_index_staging);

DELETE FROM oca_causes
WHERE indexnumberid IN (SELECT indexnumberid FROM oca_index_staging);

-- Addresses: natural-line key aligned with incremental geocode.
DELETE FROM oca_addresses m
WHERE m.indexnumberid IN (SELECT indexnumberid FROM oca_index_staging)
AND NOT EXISTS (
    SELECT 1
    FROM oca_addresses_staging s
    WHERE s.indexnumberid = m.indexnumberid
      AND m.street1 IS NOT DISTINCT FROM s.street1
      AND m.street2 IS NOT DISTINCT FROM s.street2
      AND m.city IS NOT DISTINCT FROM s.city
      AND m.state IS NOT DISTINCT FROM s.state
      AND m.postalcode IS NOT DISTINCT FROM s.postalcode
);

DELETE FROM oca_addresses m
USING oca_addresses_staging s
WHERE m.indexnumberid = s.indexnumberid
  AND m.street1 IS NOT DISTINCT FROM s.street1
  AND m.street2 IS NOT DISTINCT FROM s.street2
  AND m.city IS NOT DISTINCT FROM s.city
  AND m.state IS NOT DISTINCT FROM s.state
  AND m.postalcode IS NOT DISTINCT FROM s.postalcode;

INSERT INTO oca_index (
    indexnumberid, court, fileddate, propertytype, classification,
    specialtydesignationtypes, status, disposeddate, disposedreason,
    firstpaper, primaryclaimtotal, dateofjurydemand
)
SELECT
    indexnumberid, court, fileddate, propertytype, classification,
    specialtydesignationtypes, status, disposeddate, disposedreason,
    firstpaper, primaryclaimtotal, dateofjurydemand
FROM oca_index_staging
ON CONFLICT (indexnumberid) DO UPDATE SET
    court = EXCLUDED.court,
    fileddate = EXCLUDED.fileddate,
    propertytype = EXCLUDED.propertytype,
    classification = EXCLUDED.classification,
    specialtydesignationtypes = EXCLUDED.specialtydesignationtypes,
    status = EXCLUDED.status,
    disposeddate = EXCLUDED.disposeddate,
    disposedreason = EXCLUDED.disposedreason,
    firstpaper = EXCLUDED.firstpaper,
    primaryclaimtotal = EXCLUDED.primaryclaimtotal,
    dateofjurydemand = EXCLUDED.dateofjurydemand;

INSERT INTO oca_causes SELECT * FROM oca_causes_staging;
INSERT INTO oca_addresses (
    indexnumberid, street1, street2, city, state, postalcode, status,
    house_number, street_name, borough_code, place_name, sname, hnum, boro,
    lat, bin, bbl, cd, ct, council, grc, grc2, msg, msg2, lon, zip_code
)
SELECT
    indexnumberid, street1, street2, city, state, postalcode, status,
    house_number, street_name, borough_code, place_name, sname, hnum, boro,
    lat, bin, bbl, cd, ct, council, grc, grc2, msg, msg2, lon, zip_code
FROM oca_addresses_staging;

UPDATE oca_addresses AS o
SET geom = ST_SetSRID(ST_Point(o.lon, o.lat), 4326)
WHERE o.indexnumberid IN (SELECT indexnumberid FROM oca_index_staging)
  AND o.lat IS NOT NULL
  AND o.lon IS NOT NULL;

INSERT INTO oca_parties SELECT * FROM oca_parties_staging;
INSERT INTO oca_events SELECT * FROM oca_events_staging;
INSERT INTO oca_appearances SELECT * FROM oca_appearances_staging;
INSERT INTO oca_appearance_outcomes SELECT * FROM oca_appearance_outcomes_staging;
INSERT INTO oca_motions SELECT * FROM oca_motions_staging;
INSERT INTO oca_decisions SELECT * FROM oca_decisions_staging;
INSERT INTO oca_judgments SELECT * FROM oca_judgments_staging;
INSERT INTO oca_warrants SELECT * FROM oca_warrants_staging;

-- Metadata merge (no nested transaction; must run before staging drops).
CREATE TABLE oca_metadata_temp AS
SELECT
    COALESCE(om.indexnumberid, oms.indexnumberid) AS indexnumberid,
    COALESCE(om.initialdate, oms.initialdate) AS initialdate,
    COALESCE(oms.updatedate, om.updatedate) AS updatedate,
    COALESCE(oms.deletedate, om.deletedate) AS deletedate
FROM oca_metadata om
FULL OUTER JOIN oca_metadata_staging oms ON om.indexnumberid = oms.indexnumberid;

DROP TABLE oca_metadata;
ALTER TABLE oca_metadata_temp RENAME TO oca_metadata;

DROP TABLE IF EXISTS oca_index_staging CASCADE;
DROP TABLE IF EXISTS oca_causes_staging CASCADE;
DROP TABLE IF EXISTS oca_addresses_staging CASCADE;
DROP TABLE IF EXISTS oca_parties_staging CASCADE;
DROP TABLE IF EXISTS oca_events_staging CASCADE;
DROP TABLE IF EXISTS oca_appearances_staging CASCADE;
DROP TABLE IF EXISTS oca_appearance_outcomes_staging CASCADE;
DROP TABLE IF EXISTS oca_motions_staging CASCADE;
DROP TABLE IF EXISTS oca_decisions_staging CASCADE;
DROP TABLE IF EXISTS oca_judgments_staging CASCADE;
DROP TABLE IF EXISTS oca_warrants_staging CASCADE;
DROP TABLE IF EXISTS oca_metadata_staging CASCADE;

SET session_replication_role = default;
