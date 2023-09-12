ALTER TABLE pluto ALTER COLUMN bbl TYPE TEXT USING (round(bbl::numeric,0));

CREATE INDEX ON pluto (bbl);