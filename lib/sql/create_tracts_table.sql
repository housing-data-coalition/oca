-- CREATE EXTENSION postgis;

DROP TABLE IF EXISTS tracts CASCADE;
CREATE TABLE IF NOT EXISTS tracts (
  wkt text,
  statefp text,
  countyfp text,
  tractce text,
  geoid text,
  nam text,
  namelsad text,
  mtfcc text,
  funcstat text,
  aland bigint,
  awater bigint,
  intptlat double precision,
  intptlon double precision
--   geom Geometry(MultiPolygon, 4326)
);

ALTER TABLE tracts
  ADD COLUMN geom Geometry(MultiPolygon, 4326);

UPDATE tracts 
 SET geom = ST_GeomFromText(wkt,4326);

DROP INDEX IF EXISTS tracts_geom_idx;
CREATE INDEX tracts_geom_idx
  ON tracts
  USING GIST (geom);

-- update oca_addresses
ALTER TABLE oca_addresses 
  ADD COLUMN geom Geometry(Point, 4326);

UPDATE oca_addresses 
 SET geom = ST_SetSRID(ST_Point( lon, lat),4326)

DROP INDEX IF EXISTS oca_addresses_geom_idx;
CREATE INDEX oca_addresses_geom_idx
  ON oca_addresses
  USING GIST (geom);