DROP TABLE IF EXISTS oca_addresses CASCADE;
CREATE TABLE IF NOT EXISTS oca_addresses (
  indexnumberid text REFERENCES oca_index ON DELETE CASCADE,
  street1 text,
  street2 text,
  city text,
  state text,
  postalcode text,
  status text,
  house_number text,
  street_name text,
  borough_code text,
  place_name text,
  sname text,
  hnum text,
  boro text,
  lat real,
  bin text,
  bbl text,
  cd text,
  ct text,
  council text,
  grc text,
  grc2 text,
  msg text,
  msg2 text,
  lon real,
  zip_code text
);
