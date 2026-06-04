"""Regression and failure-safety tests for Option A parser batching and export parity."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from lib.duckdb_database import STAGING_TABLE_FAMILIES, DuckDB, fetch_staging_row_counts
from lib.etl_constants import DATA_FILENAME
from lib.etl_stages import export_staging_to_csv
from lib.parse_write_buffer import ParseWriteConfig, StagingWriteBuffer, attach_write_buffer, flush_write_buffer
from lib import parsers
from lib.parsers import parse_case, parse_file

from csv_checksums import md5_dir_csvs
from parse_pipeline_helpers import run_parse_export_in_dir
from parser_xml_fixtures import build_case_xml, build_extract_xml, write_test_zip


def _init_staging_db(path: str) -> DuckDB:
    db = DuckDB(path)
    db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
    attach_write_buffer(db)
    return db


def _staging_counts_for_index(db: DuckDB, index_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name in STAGING_TABLE_FAMILIES:
        try:
            row = db.execute(
                f'SELECT COUNT(*) FROM {table_name} WHERE indexnumberid = ?',
                (index_id,),
            ).fetchone()
            counts[table_name] = int(row[0]) if row else 0
        except Exception:
            counts[table_name] = 0
    return counts


def _parse_zip_bytes(
    xml_bytes: bytes,
    db: DuckDB,
    extract_date: str = '2024-03-08',
) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(DATA_FILENAME, xml_bytes)
    buf.seek(0)
    with zipfile.ZipFile(buf, 'r') as zf:
        with zf.open(DATA_FILENAME) as xml_file:
            parse_file(xml_file, db, extract_date, num_threads=1)


class WarmParseIdempotencyTests(unittest.TestCase):
    def test_double_parse_same_staging_db_stable_row_counts(self):
        xml_bytes = build_extract_xml(40, child_profile='weekly')
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'staging.duckdb')
            db = _init_staging_db(db_path)
            try:
                _parse_zip_bytes(xml_bytes, db)
                flush_write_buffer(db)
                first_counts = fetch_staging_row_counts(db)

                _parse_zip_bytes(xml_bytes, db)
                flush_write_buffer(db)
                second_counts = fetch_staging_row_counts(db)
            finally:
                db.close()

        self.assertEqual(first_counts, second_counts)
        self.assertEqual(first_counts['oca_index_staging'], 40)

    def test_double_parse_export_checksums_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            priv = os.path.join(tmp, 'private')
            pub = os.path.join(priv, 'public')
            os.makedirs(pub)
            write_test_zip(
                os.path.join(priv, 'LandlordTenant.Incr.2024-03-08.zip'),
                25,
                child_profile='weekly',
            )

            staging_path = os.path.join(priv, 'staging.duckdb')
            db = _init_staging_db(staging_path)
            try:
                with zipfile.ZipFile(
                    os.path.join(priv, 'LandlordTenant.Incr.2024-03-08.zip'), 'r'
                ) as zf:
                    with zf.open(DATA_FILENAME) as xml_file:
                        parse_file(xml_file, db, '2024-03-08', num_threads=1)
                flush_write_buffer(db)
                export_staging_to_csv(db, pub, upload=False)
                checksums_first = md5_dir_csvs(pub)

                with zipfile.ZipFile(
                    os.path.join(priv, 'LandlordTenant.Incr.2024-03-08.zip'), 'r'
                ) as zf:
                    with zf.open(DATA_FILENAME) as xml_file:
                        parse_file(xml_file, db, '2024-03-08', num_threads=1)
                flush_write_buffer(db)
                export_staging_to_csv(db, pub, upload=False)
                checksums_second = md5_dir_csvs(pub)
            finally:
                db.close()

        self.assertEqual(checksums_first, checksums_second)


class ColdRerunIdempotencyTests(unittest.TestCase):
    def test_cold_rerun_parity(self):
        """Two cold parse+export runs must match row counts and export checksums."""
        with tempfile.TemporaryDirectory() as tmp:
            priv1 = os.path.join(tmp, 'run1')
            priv2 = os.path.join(tmp, 'run2')
            os.makedirs(priv1)
            os.makedirs(priv2)
            write_test_zip(
                os.path.join(priv1, 'LandlordTenant.Incr.2024-03-08.zip'),
                30,
                child_profile='weekly',
            )
            write_test_zip(
                os.path.join(priv2, 'LandlordTenant.Incr.2024-03-08.zip'),
                30,
                child_profile='weekly',
            )

            rows1, checksums1 = run_parse_export_in_dir(priv1, parse_num_threads=1)
            rows2, checksums2 = run_parse_export_in_dir(priv2, parse_num_threads=1)

        self.assertEqual(checksums1, checksums2)
        self.assertEqual(rows1, rows2)


class ParserFailureRerunTests(unittest.TestCase):
    def test_mid_file_failure_discard_then_rerun_matches_clean_parse(self):
        xml_bytes = build_extract_xml(20, child_profile='weekly')
        fail_on_case = 8
        seen = {'n': 0}

        def parse_case_maybe_fail(case, db, extract_date):
            seen['n'] += 1
            if seen['n'] == fail_on_case:
                raise RuntimeError('injected parse failure')
            parse_case(case, db, extract_date)

        with tempfile.TemporaryDirectory() as tmp:
            clean_path = os.path.join(tmp, 'clean.duckdb')
            dirty_path = os.path.join(tmp, 'dirty.duckdb')

            clean_db = _init_staging_db(clean_path)
            dirty_db = _init_staging_db(dirty_path)
            try:
                _parse_zip_bytes(xml_bytes, clean_db)
                flush_write_buffer(clean_db)
                clean_counts = fetch_staging_row_counts(clean_db)

                with patch('lib.parsers.parse_case', parse_case_maybe_fail):
                    _parse_zip_bytes(xml_bytes, dirty_db)
                flush_write_buffer(dirty_db)

                _parse_zip_bytes(xml_bytes, dirty_db)
                flush_write_buffer(dirty_db)
                recovery_counts = fetch_staging_row_counts(dirty_db)
            finally:
                clean_db.close()
                dirty_db.close()

        self.assertEqual(clean_counts, recovery_counts)

    def test_failed_mid_case_leaves_no_staging_footprint(self):
        """Failure after metadata + partial children leaves no rows for that case."""
        xml_bytes = build_extract_xml(12, child_profile='weekly')
        fail_id = 'LT-BENCH-000005'
        real_parse_index = parsers.parse_index

        def parse_index_maybe_fail(case, db):
            real_parse_index(case, db)
            index_el = case.find(parsers.INDEX_NUMBER_ID_TAG)
            if index_el is not None and index_el.text == fail_id:
                raise RuntimeError('injected after metadata and index')

        with tempfile.TemporaryDirectory() as tmp:
            db = _init_staging_db(os.path.join(tmp, 'dirty.duckdb'))
            try:
                baseline = _staging_counts_for_index(db, fail_id)
                with patch('lib.parsers.parse_index', parse_index_maybe_fail):
                    _parse_zip_bytes(xml_bytes, db)
                flush_write_buffer(db)
                after_failure = _staging_counts_for_index(db, fail_id)
                counts = fetch_staging_row_counts(db)
            finally:
                db.close()

        self.assertEqual(baseline, {table: 0 for table in STAGING_TABLE_FAMILIES})
        self.assertEqual(after_failure, baseline)
        self.assertEqual(counts['oca_index_staging'], 11)


class BatchBoundaryCorrectnessTests(unittest.TestCase):
    def test_aggressive_batching_matches_legacy_counts(self):
        xml_bytes = build_extract_xml(48, child_profile='weekly')
        env = {
            'PARSE_WRITE_BATCH_ENABLED': '1',
            'PARSE_WRITE_BATCH_SIZE': '4',
            'PARSE_WRITE_FLUSH_EVERY_N_CASES': '3',
        }
        with tempfile.TemporaryDirectory() as tmp:
            legacy_path = os.path.join(tmp, 'legacy.duckdb')
            batched_path = os.path.join(tmp, 'batched.duckdb')
            legacy_db = DuckDB(legacy_path)
            legacy_db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
            batched_db = DuckDB(batched_path)
            batched_db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
            attach_write_buffer(batched_db)

            try:
                os.environ['PARSE_WRITE_BATCH_ENABLED'] = '0'
                _parse_zip_bytes(xml_bytes, legacy_db)
                for key, value in env.items():
                    os.environ[key] = value
                _parse_zip_bytes(xml_bytes, batched_db)
                flush_write_buffer(batched_db)
                legacy_counts = fetch_staging_row_counts(legacy_db)
                batched_counts = fetch_staging_row_counts(batched_db)
            finally:
                for key in env:
                    os.environ.pop(key, None)
                os.environ.pop('PARSE_WRITE_BATCH_ENABLED', None)
                legacy_db.close()
                batched_db.close()

        self.assertEqual(legacy_counts, batched_counts)

    def test_no_duplicate_child_rows_across_flush_windows(self):
        from lxml import etree

        case_id = 'LT-BOUNDARY-001'
        cases = [
            build_case_xml(case_id, num_parties=2, num_events=1),
            build_case_xml(case_id, num_parties=4, num_events=2),
            build_case_xml(case_id, num_parties=3, num_events=3),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db = DuckDB(os.path.join(tmp, 'b.duckdb'))
            db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
            db.write_buffer = StagingWriteBuffer(
                db,
                ParseWriteConfig(enabled=True, batch_size=2, flush_every_n_cases=1),
            )
            try:
                for case_xml in cases:
                    case = etree.fromstring(case_xml.encode('utf-8'))
                    parse_case(case, db, '2024-03-01')
                flush_write_buffer(db)
                parties = db.execute(
                    'SELECT COUNT(*) FROM oca_parties_staging WHERE indexnumberid = ?',
                    (case_id,),
                ).fetchone()[0]
                events = db.execute(
                    'SELECT COUNT(*) FROM oca_events_staging WHERE indexnumberid = ?',
                    (case_id,),
                ).fetchone()[0]
                self.assertGreater(db.write_buffer._flush_count, 2)
            finally:
                db.close()

        self.assertEqual(parties, 3)
        self.assertEqual(events, 3)


if __name__ == '__main__':
    unittest.main()
