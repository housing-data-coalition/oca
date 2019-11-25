-- In the "appearances" nodes they have further nested info aobut the outcomes
-- of those appearances. There are no unique identifers to be able to link
-- these elements in the original data, so we parse the outcomes as a json
-- column in the appearances column and use postgres to generate an ID column
-- with serial, then extract the outcomes json data into a separate table and
-- use the new ID column to link the records.

INSERT INTO oca_appearance_outcomes 
	SELECT 
		a.indexnumberid, 
		a.appearanceid, 
		x.appearanceoutcometype,
		x.outcomebasedontype
	FROM 
		oca_appearances AS a, 
		json_to_recordset(a.appearanceoutcomes) 
			AS x(appearanceoutcometype text, outcomebasedontype text);

ALTER TABLE oca_appearances DROP COLUMN appearanceoutcomes;
