-- =============================================================================
-- One-time cutover: replace production OCA/ETL tables in `public` with validated
-- copies from `refactor`.
--
-- OPERATIONAL CHECKLIST (run in order):
--
--   1. Pause ETL — suspend the oca-etl CronJob before running:
--        kubectl patch cronjob oca-etl -p '{"spec":{"suspend":true}}'
--
--   2. Backup — pg_dump full database (or at minimum public + refactor schemas):
--        pg_dump "$DATABASE_URL" -Fc -f oca_pre_cutover_$(date +%Y%m%d).dump
--
--   3. Run this script:
--        psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f lib/sql/cutover_refactor_to_public.sql
--
--   4. Verify — compare row counts and spot-check views:
--        SELECT COUNT(*) FROM public.oca_index;
--        SELECT COUNT(*) FROM public.oca_addresses_with_bbl LIMIT 5;
--        SELECT COUNT(*) FROM public.oca_addresses_with_ct LIMIT 5;
--
--   5. Publish (optional) — re-export S3 public CSVs if downstream consumers need
--      fresh files. Run oca_update.py publish with DB_SCHEMA empty, or a full ETL
--      with production settings (DB_SCHEMA and S3_PREFIX empty).
--
--   6. Cleanup (after confidence window) — drop archived and empty schemas:
--        DROP SCHEMA public_pre_cutover CASCADE;
--        DROP SCHEMA refactor CASCADE;
--
--   7. Re-enable ETL — ensure DB_SCHEMA and S3_PREFIX are empty in production:
--        kubectl patch cronjob oca-etl -p '{"spec":{"suspend":false}}'
--
-- ROLLBACK (before cleanup, if cutover data is bad):
--
--   BEGIN;
--   DROP VIEW IF EXISTS public.oca_addresses_with_bbl;
--   DROP VIEW IF EXISTS public.oca_addresses_with_ct;
--   DROP VIEW IF EXISTS public.oca_addresses_public;
--   -- Move cutover tables out of public (drop or move to a scratch schema)
--   -- Move public_pre_cutover.* back to public (ETL children first, then etl_runs;
--   -- OCA children first, then oca_index)
--   -- Re-run create_addresses_views.sql
--   COMMIT;
--
-- Preserves in public: pluto, tracts (reference tables for address views).
-- Does not move: *_staging tables (warns if any remain in refactor).
-- =============================================================================

BEGIN;

SET LOCAL lock_timeout = '30s';
SET LOCAL statement_timeout = '0';

-- ---------------------------------------------------------------------------
-- 1. Pre-flight checks
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.schemata WHERE schema_name = 'refactor'
    ) THEN
        RAISE EXCEPTION 'refactor schema does not exist';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'refactor'
          AND table_name = 'oca_index'
    ) THEN
        RAISE EXCEPTION 'refactor.oca_index does not exist';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM refactor.oca_index LIMIT 1) THEN
        RAISE EXCEPTION 'refactor.oca_index is empty';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public_pre_cutover'
        LIMIT 1
    ) THEN
        RAISE EXCEPTION
            'public_pre_cutover schema already contains tables; resolve or drop before re-running';
    END IF;
END $$;

DO $$
DECLARE
    staging_count integer;
BEGIN
    SELECT COUNT(*) INTO staging_count
    FROM pg_tables
    WHERE schemaname = 'refactor'
      AND tablename LIKE '%\_staging' ESCAPE '\';

    IF staging_count > 0 THEN
        RAISE WARNING
            'refactor contains % staging table(s); they will not be promoted to public',
            staging_count;
    END IF;
END $$;

-- Log row-count sanity check (refactor vs public)
DO $$
DECLARE
    refactor_count bigint;
    public_count bigint;
BEGIN
    SELECT COUNT(*) INTO refactor_count FROM refactor.oca_index;
    SELECT COUNT(*) INTO public_count FROM public.oca_index;
    RAISE NOTICE 'oca_index row counts — refactor: %, public (pre-cutover): %',
        refactor_count, public_count;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Drop dependent views in public
-- ---------------------------------------------------------------------------

DROP VIEW IF EXISTS public.oca_addresses_with_bbl;
DROP VIEW IF EXISTS public.oca_addresses_with_ct;
DROP VIEW IF EXISTS public.oca_addresses_public;

-- ---------------------------------------------------------------------------
-- 3. Archive old public OCA/ETL tables to public_pre_cutover
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS public_pre_cutover;

DO $$
DECLARE
    tbl text;
    etl_children text[] := ARRAY['etl_files', 'etl_steps'];
    oca_children text[] := ARRAY[
        'oca_causes',
        'oca_addresses',
        'oca_parties',
        'oca_events',
        'oca_appearances',
        'oca_appearance_outcomes',
        'oca_motions',
        'oca_decisions',
        'oca_judgments',
        'oca_warrants',
        'oca_metadata'
    ];
    optional_tables text[] := ARRAY['oca_addresses_geocode_staging'];
BEGIN
    FOREACH tbl IN ARRAY etl_children LOOP
        IF EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = 'public' AND tablename = tbl
        ) THEN
            EXECUTE format(
                'ALTER TABLE public.%I SET SCHEMA public_pre_cutover',
                tbl
            );
            RAISE NOTICE 'Archived public.% to public_pre_cutover', tbl;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_tables
        WHERE schemaname = 'public' AND tablename = 'etl_runs'
    ) THEN
        ALTER TABLE public.etl_runs SET SCHEMA public_pre_cutover;
        RAISE NOTICE 'Archived public.etl_runs to public_pre_cutover';
    END IF;

    FOREACH tbl IN ARRAY oca_children LOOP
        IF EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = 'public' AND tablename = tbl
        ) THEN
            EXECUTE format(
                'ALTER TABLE public.%I SET SCHEMA public_pre_cutover',
                tbl
            );
            RAISE NOTICE 'Archived public.% to public_pre_cutover', tbl;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_tables
        WHERE schemaname = 'public' AND tablename = 'oca_index'
    ) THEN
        ALTER TABLE public.oca_index SET SCHEMA public_pre_cutover;
        RAISE NOTICE 'Archived public.oca_index to public_pre_cutover';
    END IF;

    FOREACH tbl IN ARRAY optional_tables LOOP
        IF EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = 'public' AND tablename = tbl
        ) THEN
            EXECUTE format(
                'ALTER TABLE public.%I SET SCHEMA public_pre_cutover',
                tbl
            );
            RAISE NOTICE 'Archived public.% to public_pre_cutover', tbl;
        END IF;
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 4. Promote refactor tables to public
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    tbl text;
    etl_parent text := 'etl_runs';
    etl_children text[] := ARRAY['etl_files', 'etl_steps'];
    oca_parent text := 'oca_index';
    oca_children text[] := ARRAY[
        'oca_causes',
        'oca_addresses',
        'oca_parties',
        'oca_events',
        'oca_appearances',
        'oca_appearance_outcomes',
        'oca_motions',
        'oca_decisions',
        'oca_judgments',
        'oca_warrants',
        'oca_metadata'
    ];
    optional_tables text[] := ARRAY['oca_addresses_geocode_staging'];
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables
        WHERE schemaname = 'refactor' AND tablename = oca_parent
    ) THEN
        EXECUTE format(
            'ALTER TABLE refactor.%I SET SCHEMA public',
            oca_parent
        );
        RAISE NOTICE 'Promoted refactor.% to public', oca_parent;
    ELSE
        RAISE EXCEPTION 'refactor.% does not exist', oca_parent;
    END IF;

    FOREACH tbl IN ARRAY oca_children LOOP
        IF EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = 'refactor' AND tablename = tbl
        ) THEN
            EXECUTE format(
                'ALTER TABLE refactor.%I SET SCHEMA public',
                tbl
            );
            RAISE NOTICE 'Promoted refactor.% to public', tbl;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_tables
        WHERE schemaname = 'refactor' AND tablename = etl_parent
    ) THEN
        EXECUTE format(
            'ALTER TABLE refactor.%I SET SCHEMA public',
            etl_parent
        );
        RAISE NOTICE 'Promoted refactor.% to public', etl_parent;
    END IF;

    FOREACH tbl IN ARRAY etl_children LOOP
        IF EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = 'refactor' AND tablename = tbl
        ) THEN
            EXECUTE format(
                'ALTER TABLE refactor.%I SET SCHEMA public',
                tbl
            );
            RAISE NOTICE 'Promoted refactor.% to public', tbl;
        END IF;
    END LOOP;

    FOREACH tbl IN ARRAY optional_tables LOOP
        IF EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = 'refactor' AND tablename = tbl
        ) THEN
            EXECUTE format(
                'ALTER TABLE refactor.%I SET SCHEMA public',
                tbl
            );
            RAISE NOTICE 'Promoted refactor.% to public', tbl;
        END IF;
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 5. Sync sequences
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    seq_name text;
    max_val bigint;
BEGIN
    seq_name := pg_get_serial_sequence('public.oca_appearances', 'appearanceid');
    IF seq_name IS NOT NULL THEN
        SELECT COALESCE(MAX(appearanceid), 1) INTO max_val FROM public.oca_appearances;
        PERFORM setval(seq_name, max_val);
        RAISE NOTICE 'Synced % to %', seq_name, max_val;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'etl_runs') THEN
        seq_name := pg_get_serial_sequence('public.etl_runs', 'id');
        IF seq_name IS NOT NULL THEN
            SELECT COALESCE(MAX(id), 1) INTO max_val FROM public.etl_runs;
            PERFORM setval(seq_name, max_val);
            RAISE NOTICE 'Synced % to %', seq_name, max_val;
        END IF;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'etl_files') THEN
        seq_name := pg_get_serial_sequence('public.etl_files', 'id');
        IF seq_name IS NOT NULL THEN
            SELECT COALESCE(MAX(id), 1) INTO max_val FROM public.etl_files;
            PERFORM setval(seq_name, max_val);
            RAISE NOTICE 'Synced % to %', seq_name, max_val;
        END IF;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'etl_steps') THEN
        seq_name := pg_get_serial_sequence('public.etl_steps', 'id');
        IF seq_name IS NOT NULL THEN
            SELECT COALESCE(MAX(id), 1) INTO max_val FROM public.etl_steps;
            PERFORM setval(seq_name, max_val);
            RAISE NOTICE 'Synced % to %', seq_name, max_val;
        END IF;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 6. Recreate views and grants (from create_addresses_views.sql)
-- ---------------------------------------------------------------------------

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
        round(ct2010, 2) AS ct,
        bct2020,
        bctcb2020,
        round(ct2010, 2) AS ct2010,
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

CREATE OR REPLACE VIEW public.oca_addresses_with_ct AS
    SELECT
        o.indexnumberid,
        t.geoid,
        t.countyfp,
        o.city,
        o.state,
        o.postalcode
    FROM oca_addresses o
    LEFT JOIN tracts t ON st_intersects(o.geom, t.geom);

CREATE OR REPLACE VIEW public.oca_addresses_public AS
    SELECT
        indexnumberid,
        city,
        state,
        postalcode
    FROM oca_addresses;

GRANT ALL ON ALL TABLES IN SCHEMA public TO jacob;
GRANT ALL ON ALL TABLES IN SCHEMA public TO lucy;
GRANT ALL ON ALL TABLES IN SCHEMA public TO maxwell;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO select_only;

COMMIT;

-- ---------------------------------------------------------------------------
-- Post-commit maintenance (run manually after verification; not transactional)
-- ---------------------------------------------------------------------------
--
-- VACUUM ANALYZE core tables, or run lib/sql/vacuum.sql:
--
--   VACUUM ANALYZE public.oca_index;
--   VACUUM ANALYZE public.oca_causes;
--   ... (remaining OCA tables)
--
-- After confidence window:
--
--   DROP SCHEMA public_pre_cutover CASCADE;
--   DROP SCHEMA refactor CASCADE;
