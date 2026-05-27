-- update appearanceid so that the serial resumes from the latest number in the main table
DO $$
DECLARE
    max_id bigint;
    staging_count bigint;
BEGIN
    -- Get max ID from main table
    SELECT COALESCE(MAX(appearanceid), 0) INTO max_id FROM oca_appearances;
    
    -- Get count of staging records
    SELECT COUNT(*) INTO staging_count FROM oca_appearances_staging;
    
    -- Update NULL appearanceid values with sequential numbers starting from max_id + 1
    WITH numbered_rows AS (
        SELECT ctid, ROW_NUMBER() OVER (ORDER BY ctid) as rn
        FROM oca_appearances_staging 
        WHERE appearanceid IS NULL
    )
    UPDATE oca_appearances_staging 
    SET appearanceid = max_id + nr.rn
    FROM numbered_rows nr
    WHERE oca_appearances_staging.ctid = nr.ctid;
    
    -- Set sequence for future inserts
    PERFORM setval(
        pg_get_serial_sequence('oca_appearances_staging', 'appearanceid'),
        max_id + staging_count
    );
END $$;

-- In the "appearances" nodes they have further nested info about the outcomes
-- of those appearances. There are no unique identifers to be able to link
-- these elements in the original data, so we parse the outcomes as a json
-- column in the appearances column and use postgres to generate an ID column
-- with serial, then extract the outcomes json data into a separate table and
-- use the new ID column to link the records. After populating the "outcomes"
-- table we can drop the temporary "appearanceoutcomes" column from the 
-- "appearances" table so that all the staging tables mirror the main tables

INSERT INTO oca_appearance_outcomes_staging 
	SELECT 
		a.indexnumberid,
		a.appearanceid,
		x.appearanceoutcometype,
		x.outcomebasedontype
	FROM 
		oca_appearances_staging AS a
	CROSS JOIN LATERAL json_to_recordset(
		CASE 
			WHEN json_typeof(a.appearanceoutcomes) = 'array' 
			THEN a.appearanceoutcomes -- deal with empty objects {}
			ELSE json_build_array(a.appearanceoutcomes)
		END
	) AS x(appearanceoutcometype text, outcomebasedontype text);

ALTER TABLE oca_appearances_staging DROP COLUMN appearanceoutcomes;