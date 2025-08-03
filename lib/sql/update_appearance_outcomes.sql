-- update appearanceid so that the serial resumes from the latest number in the main table
DO $$
DECLARE
    max_id bigint;
    offset_val bigint;
BEGIN
    SELECT COALESCE(MAX(appearanceid), 0) INTO max_id FROM oca_appearances;
    
    -- Update all existing rows to continue from max_id
    UPDATE oca_appearances_staging 
    SET appearanceid = appearanceid + max_id;
    
    -- Set sequence for any future inserts
    PERFORM setval(
        pg_get_serial_sequence('oca_appearances_staging', 'appearanceid'),
        max_id + (SELECT COUNT(*) FROM oca_appearances_staging)
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