BEGIN TRANSACTION;

-- Create temporary table with new data
CREATE TABLE oca_metadata_temp AS
SELECT
    COALESCE(om.indexnumberid, oms.indexnumberid) AS indexnumberid,
    COALESCE(om.initialdate, oms.initialdate) AS initialdate,
    CASE
        WHEN om.indexnumberid IS NULL THEN oms.updatedate
        ELSE oms.updatedate
    END AS updatedate,
    CASE
        WHEN om.indexnumberid IS NULL THEN oms.deletedate
        ELSE oms.deletedate
    END AS deletedate
FROM oca_metadata om
FULL OUTER JOIN oca_metadata_staging oms ON om.indexnumberid = oms.indexnumberid;

-- Replace the original table
DROP TABLE oca_metadata;
ALTER TABLE oca_metadata_temp RENAME TO oca_metadata;

COMMIT;