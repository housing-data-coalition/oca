
alter table pluto alter column bbl TYPE TEXT USING (round(bbl::numeric,0));

create index on pluto (bbl);
