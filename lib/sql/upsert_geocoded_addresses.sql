UPDATE oca_addresses AS o
SET
  street1 = s.street1,
  street2 = s.street2,
  city = s.city,
  state = s.state,
  postalcode = s.postalcode,
  status = s.status,
  house_number = s.house_number,
  street_name = s.street_name,
  borough_code = s.borough_code,
  place_name = s.place_name,
  sname = s.sname,
  hnum = s.hnum,
  boro = s.boro,
  lat = s.lat,
  bin = s.bin,
  bbl = s.bbl,
  cd = s.cd,
  ct = s.ct,
  council = s.council,
  grc = s.grc,
  grc2 = s.grc2,
  msg = s.msg,
  msg2 = s.msg2,
  lon = s.lon,
  zip_code = s.zip_code
FROM oca_addresses_geocode_staging AS s
WHERE o.indexnumberid IS NOT DISTINCT FROM s.indexnumberid
  AND o.street1 IS NOT DISTINCT FROM s.street1
  AND o.street2 IS NOT DISTINCT FROM s.street2
  AND o.city IS NOT DISTINCT FROM s.city
  AND o.state IS NOT DISTINCT FROM s.state
  AND o.postalcode IS NOT DISTINCT FROM s.postalcode;
