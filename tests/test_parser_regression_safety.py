"""Regression and failure-safety tests for Option A parser batching and export parity."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from lib.benchmark_fixtures import build_extract_xml, write_benchmark_zip
from lib.duckdb_database import DuckDB, fetch_staging_row_counts
from lib.etl_benchmark import run_parse_export_preprocess
from lib.etl_constants import DATA_FILENAME
from lib.etl_metrics import EtlStageMetrics
from lib.etl_stages import export_staging_to_csv
from lib.parse_write_buffer import ParseWriteConfig, attach_write_buffer, flush_write_buffer
from lib.parsers import parse_case, parse_file


def _init_staging_db(path: str, metrics: EtlStageMetrics | None = None) -> DuckDB:
    db = DuckDB(path, metrics=metrics or EtlStageMetrics.disabled())
    db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
    attach_write_buffer(db, metrics=metrics)
    return db


def _parse_zip_bytes(
    xml_bytes: bytes,
    db: DuckDB,
    extract_date: str = '2024-03-08',
    *,
    metrics: EtlStageMetrics | None = None,
) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(DATA_FILENAME, xml_bytes)
    buf.seek(0)
    with zipfile.ZipFile(buf, 'r') as zf:
        with zf.open(DATA_FILENAME) as xml_file:
            parse_file(
                xml_file,
                db,
                extract_date,
                num_threads=1,
                metrics=metrics,
            )


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
            write_benchmark_zip(
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
                from lib.etl_benchmark import _checksum_pub_dir

                checksums_first = _checksum_pub_dir(pub)

                with zipfile.ZipFile(
                    os.path.join(priv, 'LandlordTenant.Incr.2024-03-08.zip'), 'r'
                ) as zf:
                    with zf.open(DATA_FILENAME) as xml_file:
                        parse_file(xml_file, db, '2024-03-08', num_threads=1)
                flush_write_buffer(db)
                export_staging_to_csv(db, pub, upload=False)
                checksums_second = _checksum_pub_dir(pub)
            finally:
                db.close()

        self.assertEqual(checksums_first, checksums_second)


class BenchmarkRerunIdempotencyTests(unittest.TestCase):
    def test_cold_rerun_parity_via_harness(self):
        """Two cold benchmark iterations must match row counts and export checksums."""
        with tempfile.TemporaryDirectory() as tmp:
            priv1 = os.path.join(tmp, 'run1')
            priv2 = os.path.join(tmp, 'run2')
            os.makedirs(priv1)
            os.makedirs(priv2)
            write_benchmark_zip(
                os.path.join(priv1, 'LandlordTenant.Incr.2024-03-08.zip'),
                30,
                child_profile='weekly',
            )
            write_benchmark_zip(
                os.path.join(priv2, 'LandlordTenant.Incr.2024-03-08.zip'),
                30,
                child_profile='weekly',
            )

            _, checksums1, rows1 = run_parse_export_preprocess(
                priv1, metrics=EtlStageMetrics(), parse_num_threads=1
            )
            _, checksums2, rows2 = run_parse_export_preprocess(
                priv2, metrics=EtlStageMetrics(), parse_num_threads=1
            )

        self.assertEqual(checksums1, checksums2)
        self.assertEqual(rows1, rows2)


class ParserFailureRerunTests(unittest.TestCase):
    def test_mid_file_failure_flush_then_rerun_matches_clean_parse(self):
        xml_bytes = build_extract_xml(20, child_profile='weekly')
        metrics = EtlStageMetrics()
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
            dirty_db = _init_staging_db(dirty_path, metrics=metrics)
            try:
                _parse_zip_bytes(xml_bytes, clean_db)
                flush_write_buffer(clean_db)
                clean_counts = fetch_staging_row_counts(clean_db)

                with patch('lib.parsers.parse_case', parse_case_maybe_fail):
                    _parse_zip_bytes(xml_bytes, dirty_db, metrics=metrics)
                flush_write_buffer(dirty_db)
                self.assertGreaterEqual(
                    metrics.counters.get('parse_write_flush_on_error', 0), 1
                )

                _parse_zip_bytes(xml_bytes, dirty_db)
                flush_write_buffer(dirty_db)
                recovery_counts = fetch_staging_row_counts(dirty_db)
            finally:
                clean_db.close()
                dirty_db.close()

        self.assertEqual(clean_counts, recovery_counts)


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
            metrics = EtlStageMetrics()

            try:
                os.environ['PARSE_WRITE_BATCH_ENABLED'] = '0'
                _parse_zip_bytes(xml_bytes, legacy_db)
                for key, value in env.items():
                    os.environ[key] = value
                _parse_zip_bytes(xml_bytes, batched_db, metrics=metrics)
                legacy_counts = fetch_staging_row_counts(legacy_db)
                batched_counts = fetch_staging_row_counts(batched_db)
                flushes = metrics.counters.get('parse_write_flushes', 0)
            finally:
                for key in env:
                    os.environ.pop(key, None)
                os.environ.pop('PARSE_WRITE_BATCH_ENABLED', None)
                legacy_db.close()
                batched_db.close()

        self.assertEqual(legacy_counts, batched_counts)
        self.assertGreater(flushes, 5)

    def test_no_duplicate_child_rows_across_flush_windows(self):
        from lib.benchmark_fixtures import build_case_xml
        from lib.parse_write_buffer import StagingWriteBuffer
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


class FlushDiagnosticsTests(unittest.TestCase):
    def test_flush_debug_records_history(self):
        from lib.parse_write_buffer import StagingWriteBuffer

        os.environ['PARSE_WRITE_FLUSH_DEBUG'] = '1'
        with tempfile.TemporaryDirectory() as tmp:
            db = DuckDB(os.path.join(tmp, 'd.duckdb'))
            db.execute('CREATE TABLE t (id INTEGER)')
            buffer = StagingWriteBuffer(
                db, ParseWriteConfig(enabled=True, batch_size=2, flush_every_n_cases=1)
            )
            buffer.queue_insert('INSERT INTO t VALUES (?)', (1,))
            buffer.on_case_complete()
            buffer.queue_insert('INSERT INTO t VALUES (?)', (2,))
            buffer.flush(reason='explicit')
            history_len = len(buffer.flush_history)
            db.close()
        os.environ.pop('PARSE_WRITE_FLUSH_DEBUG', None)

        self.assertGreaterEqual(history_len, 1)
        self.assertIsNotNone(buffer.last_flush)


if __name__ == '__main__':
    unittest.main()
