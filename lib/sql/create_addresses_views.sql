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

create view oca_addresses_with_ct as
	select 
		indexnumberid,
		geoid,
		-- namelsad,
		countyfp,
		city,
		state,
		postalcode,
		grc,
		grc2,
		msg,
		msg2
	from oca_addresses o 
	join tracts t 
	on st_intersects(o.geom, t.geom);

-- -- Re grant access
-- GRANT ALL ON ALL TABLES IN SCHEMA public TO jacob;
-- GRANT ALL ON ALL TABLES IN SCHEMA public TO  lucy;
-- GRANT ALL ON ALL TABLES IN SCHEMA public TO  maxwell;

-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO jweisberg;
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO select_only;