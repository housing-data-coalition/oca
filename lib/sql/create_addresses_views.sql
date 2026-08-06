-- CREATE EXTENSION IF NOT EXISTS postgis;
-- CREATE EXTENSION IF NOT EXISTS aws_s3 CASCADE;

-- Drop all related views
DROP VIEW IF EXISTS public.oca_addresses_with_bbl;
DROP VIEW IF EXISTS public.oca_addresses_with_ct;
DROP VIEW IF EXISTS public.oca_addresses_public;

CREATE OR REPLACE VIEW public.oca_addresses_with_bbl AS
	SELECT 
		indexnumberid,
		city,
		state,
		postalcode,
		borough_code,
		place_name,
		boro,
		o.cd,
		round(ct2010,2) as ct, -- legacy: ct is for census 2010 geographies
		bct2020,
		bctcb2020,
		round(ct2010,2) as ct2010,
		cb2010,
		o.council,
		grc,
		grc2,
		msg,
		msg2,
		unitsres,
		CASE 
			WHEN unitsres > 10 THEN o.bbl
			ELSE NULL
		END AS bbl
	FROM oca_addresses o
	LEFT JOIN pluto p ON LEFT(p.bbl, 10) = o.bbl;

CREATE OR REPLACE VIEW public.oca_addresses_with_ct
AS SELECT o.indexnumberid,
    t.geoid,
    t.countyfp,
    o.city,
    o.state,
    o.postalcode
   FROM oca_addresses o
   LEFT JOIN tracts t ON st_intersects(o.geom, t.geom);

-- create a view equivalent to the level-1 version of "oca_addresses" table from
-- the level-2 table, which can be made public (used for NYCDB) 
CREATE OR REPLACE VIEW public.oca_addresses_public
AS SELECT 
	indexnumberid,
    city,
	state,
	postalcode
   FROM oca_addresses;

-- Re grant access
GRANT ALL ON ALL TABLES IN SCHEMA public TO jacob;
GRANT ALL ON ALL TABLES IN SCHEMA public TO lucy;
GRANT ALL ON ALL TABLES IN SCHEMA public TO maxwell;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO select_only;