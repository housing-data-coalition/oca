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