"""Parse failure counters and manifest details (Task 1 observability)."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from lib.duckdb_database import DuckDB
from lib.etl_constants import DATA_FILENAME
from lib.parse_manifest import (
    ParseFailFastError,
    build_parse_xml_step_details,
    cases_failed_from_details,
    finalize_parse_xml_step,
    upsert_parsed_etl_file,
    upsert_promoted_etl_file,
)
from lib.parse_write_buffer import attach_write_buffer, flush_write_buffer
from lib.parsers import (
    MAX_PARSE_ERROR_SAMPLES,
    MAX_PARSE_ERROR_SAMPLE_LEN,
    ParseFileResult,
    parse_case,
    parse_file,
)

from parser_xml_fixtures import build_extract_xml, write_test_zip


class FakeManifest:
    def __init__(self):
        self.file_upserts = []
        self.step_upserts = []
        self.file_details_by_name = {}

    def upsert_file(self, file_name, source, status, stage=None, details=None, error=None):
        if details is not None:
            self.file_details_by_name[file_name] = dict(details)
        self.file_upserts.append({
            'file_name': file_name,
            'source': source,
            'status': status,
            'stage': stage,
            'details': details or {},
            'error': error,
        })

    def upsert_step(self, step_name, status, details=None, error=None):
        self.step_upserts.append({
            'step_name': step_name,
            'status': status,
            'details': details or {},
            'error': error,
        })


def _init_staging_db(path: str) -> DuckDB:
    db = DuckDB(path)
    db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
    attach_write_buffer(db)
    return db


def _parse_zip_bytes(xml_bytes: bytes, db: DuckDB, extract_date: str = '2024-03-08') -> ParseFileResult:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(DATA_FILENAME, xml_bytes)
    buf.seek(0)
    with zipfile.ZipFile(buf, 'r') as zf:
        with zf.open(DATA_FILENAME) as xml_file:
            return parse_file(xml_file, db, extract_date, num_threads=1)


class ParseFileResultTests(unittest.TestCase):
    def test_cases_seen_matches_index_count(self):
        xml_bytes = build_extract_xml(12, child_profile='weekly')
        with tempfile.TemporaryDirectory() as tmp:
            db = _init_staging_db(os.path.join(tmp, 'staging.duckdb'))
            try:
                result = _parse_zip_bytes(xml_bytes, db)
                flush_write_buffer(db)
            finally:
                db.close()

        self.assertEqual(result.cases_seen, 12)
        self.assertEqual(result.cases_parsed_ok, 12)
        self.assertEqual(result.cases_failed, 0)
        self.assertEqual(result.error_samples, [])

    def test_injected_failures_increment_counters_and_samples(self):
        xml_bytes = build_extract_xml(5, child_profile='weekly')
        fail_ids = {2, 4}
        seen = {'n': 0}

        def parse_case_maybe_fail(case, db, extract_date):
            seen['n'] += 1
            if seen['n'] in fail_ids:
                raise RuntimeError(f'injected failure case {seen["n"]}')
            parse_case(case, db, extract_date)

        with tempfile.TemporaryDirectory() as tmp:
            db = _init_staging_db(os.path.join(tmp, 'staging.duckdb'))
            try:
                with patch('lib.parsers.parse_case', parse_case_maybe_fail):
                    result = _parse_zip_bytes(xml_bytes, db)
                flush_write_buffer(db)
            finally:
                db.close()

        self.assertEqual(result.cases_seen, 5)
        self.assertEqual(result.cases_parsed_ok, 3)
        self.assertEqual(result.cases_failed, 2)
        self.assertEqual(len(result.error_samples), 2)
        self.assertTrue(all('injected failure' in s for s in result.error_samples))

    def test_error_samples_capped_at_ten(self):
        xml_bytes = build_extract_xml(15, child_profile='weekly')
        seen = {'n': 0}

        def parse_case_always_fail(case, db, extract_date):
            seen['n'] += 1
            raise RuntimeError('always fail')

        with tempfile.TemporaryDirectory() as tmp:
            db = _init_staging_db(os.path.join(tmp, 'staging.duckdb'))
            try:
                with patch('lib.parsers.parse_case', parse_case_always_fail):
                    result = _parse_zip_bytes(xml_bytes, db)
            finally:
                db.close()

        self.assertEqual(result.cases_failed, 15)
        self.assertEqual(len(result.error_samples), MAX_PARSE_ERROR_SAMPLES)

    def test_error_sample_truncation(self):
        long_msg = 'x' * (MAX_PARSE_ERROR_SAMPLE_LEN + 50)
        stats = ParseFileResult()
        stats.record_failed(long_msg)
        self.assertEqual(len(stats.error_samples[0]), MAX_PARSE_ERROR_SAMPLE_LEN)
        self.assertTrue(stats.error_samples[0].endswith('...'))

    def test_parse_logs_indexnumberid_on_failure(self):
        xml_bytes = build_extract_xml(1, child_profile='weekly')
        case_id = 'LT-BENCH-000000'

        def parse_case_fail(case, db, extract_date):
            raise RuntimeError('log test failure')

        with tempfile.TemporaryDirectory() as tmp:
            db = _init_staging_db(os.path.join(tmp, 'staging.duckdb'))
            try:
                with patch('lib.parsers.parse_case', parse_case_fail):
                    with self.assertLogs('lib.parsers', level='WARNING') as logs:
                        _parse_zip_bytes(xml_bytes, db)
            finally:
                db.close()

        combined = '\n'.join(logs.output)
        self.assertIn('indexnumberid=', combined)
        self.assertIn(case_id, combined)


class ParseManifestUpsertTests(unittest.TestCase):
    def test_upsert_parsed_etl_file_and_step_aggregate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _init_staging_db(os.path.join(tmp, 'staging.duckdb'))
            manifest = FakeManifest()
            fail_on = {3}

            def parse_case_maybe_fail(case, db, extract_date):
                index_elem = case.find(
                    '{http://www.example.org/LandlordTenantExtractSchema}IndexNumberId'
                )
                case_num = int(index_elem.text.rsplit('-', 1)[-1]) if index_elem is not None else 0
                if case_num in fail_on:
                    raise RuntimeError('manifest test failure')
                parse_case(case, db, extract_date)

            xml_bytes = build_extract_xml(6, child_profile='weekly')
            try:
                with patch('lib.parsers.parse_case', parse_case_maybe_fail):
                    result = _parse_zip_bytes(xml_bytes, db)
                flush_write_buffer(db)
            finally:
                db.close()

        upsert_parsed_etl_file(
            manifest,
            'LandlordTenant.Incr.2024-03-08.zip',
            result,
            '2024-03-08',
        )
        manifest.upsert_step(
            'parse_xml',
            'completed',
            details=build_parse_xml_step_details(result.cases_failed, 1),
        )

        self.assertEqual(len(manifest.file_upserts), 1)
        upsert = manifest.file_upserts[0]
        details = upsert['details']
        self.assertEqual(upsert['status'], 'parsed')
        self.assertEqual(details['cases_seen'], 6)
        self.assertEqual(details['cases_parsed_ok'], 5)
        self.assertEqual(details['cases_failed'], 1)
        self.assertEqual(len(details['error_samples']), 1)
        self.assertEqual(details['extract_date'], '2024-03-08')
        self.assertIn('1 of 6 cases failed', upsert['error'])

        step_details = manifest.step_upserts[0]['details']
        self.assertEqual(step_details['total_cases_failed'], 1)
        self.assertEqual(step_details['files_with_failures'], 1)


class PromoteCompletedGateTests(unittest.TestCase):
    def test_upsert_promoted_marks_completed_only_when_no_failures(self):
        manifest = FakeManifest()
        clean_details = {
            'extract_date': '2024-03-08',
            'cases_seen': 10,
            'cases_parsed_ok': 10,
            'cases_failed': 0,
            'error_samples': [],
        }
        dirty_details = dict(clean_details)
        dirty_details['cases_failed'] = 3
        dirty_details['cases_parsed_ok'] = 7
        dirty_details['error_samples'] = ['err']

        self.assertTrue(upsert_promoted_etl_file(manifest, 'clean.zip', 'sftp', clean_details))
        self.assertFalse(upsert_promoted_etl_file(manifest, 'dirty.zip', 's3_private', dirty_details))

        clean_upsert = manifest.file_upserts[-2]
        dirty_upsert = manifest.file_upserts[-1]
        self.assertEqual(clean_upsert['status'], 'completed')
        self.assertEqual(clean_upsert['stage'], 'promote')
        self.assertNotIn('parse_complete', clean_upsert['details'])

        self.assertEqual(dirty_upsert['status'], 'parsed')
        self.assertEqual(dirty_upsert['stage'], 'parse')
        self.assertFalse(dirty_upsert['details']['parse_complete'])
        self.assertEqual(dirty_upsert['details']['cases_failed'], 3)

    def test_cases_failed_from_details_coerces_missing(self):
        self.assertEqual(cases_failed_from_details({}), 0)
        self.assertEqual(cases_failed_from_details({'cases_failed': '2'}), 2)


class ParseFailFastTests(unittest.TestCase):
    def test_finalize_parse_fail_fast_marks_step_and_files_failed(self):
        manifest = FakeManifest()
        manifest.file_details_by_name = {
            'bad.zip': {
                'cases_seen': 5,
                'cases_parsed_ok': 3,
                'cases_failed': 2,
                'error_samples': ['err'],
            },
            'good.zip': {
                'cases_seen': 1,
                'cases_parsed_ok': 1,
                'cases_failed': 0,
                'error_samples': [],
            },
        }

        with self.assertRaises(ParseFailFastError):
            finalize_parse_xml_step(manifest, 2, 1, parse_fail_fast=True)

        self.assertEqual(manifest.step_upserts[-1]['status'], 'failed')
        self.assertEqual(manifest.step_upserts[-1]['step_name'], 'parse_xml')
        failed_names = {u['file_name'] for u in manifest.file_upserts if u['status'] == 'failed'}
        self.assertEqual(failed_names, {'bad.zip'})

    def test_lenient_finalize_completes_step_with_failures(self):
        manifest = FakeManifest()
        finalize_parse_xml_step(manifest, 3, 1, parse_fail_fast=False)
        self.assertEqual(manifest.step_upserts[-1]['status'], 'completed')
        self.assertEqual(manifest.step_upserts[-1]['details']['total_cases_failed'], 3)


if __name__ == '__main__':
    unittest.main()
