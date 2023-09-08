drop view if exists oca_addresses_with_bbl cascade;
drop view if exists oca_addresses_with_ct cascade;

create view oca_addresses_with_bbl as
	select 
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
		case 
			when unitsres > 10 then o.bbl
			else null
		end as bbl
	from oca_addresses o
	left join 
		pluto using(bbl);

-- update oca_addresses with geom field
ALTER TABLE oca_addresses 
  ADD COLUMN geom Geometry(Point, 4326);

UPDATE oca_addresses 
 SET geom = ST_SetSRID(ST_Point( lon, lat),4326);
DROP INDEX IF EXISTS oca_addresses_geom_idx;

CREATE INDEX oca_addresses_geom_idx
  ON oca_addresses
  USING GIST (geom);

CREATE OR REPLACE VIEW public.oca_addresses_with_ct
AS SELECT o.indexnumberid,
    t.geoid,
    t.countyfp,
    o.city,
    o.state,
    o.postalcode,
    o.grc,
    o.grc2,
    o.msg,
    o.msg2
   FROM oca_addresses o
     JOIN tracts t ON st_intersects(o.geom, t.geom);

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