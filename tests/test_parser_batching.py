import io
import os
import tempfile
import unittest
import zipfile

from lxml import etree

from parser_xml_fixtures import build_case_xml, build_extract_xml, write_test_zip
from lib.duckdb_database import DuckDB, fetch_staging_row_counts
from lib.etl_constants import DATA_FILENAME
from lib.parse_write_buffer import ParseWriteConfig, attach_write_buffer, flush_write_buffer
from lib.parsers import parse_file, parse_case


def _init_staging_db(path: str) -> DuckDB:
    db = DuckDB(path)
    db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
    attach_write_buffer(db)
    return db


def _case_from_xml(case_xml: str):
    return etree.fromstring(case_xml.encode('utf-8'))


class ParserBatchingSemanticsTests(unittest.TestCase):
    def test_repeated_case_update_replaces_child_rows(self):
        case_id = 'LT-REPEAT-001'
        first = build_case_xml(case_id, num_parties=2, num_events=1)
        second = build_case_xml(case_id, num_parties=4, num_events=3)

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'staging.duckdb')
            db = _init_staging_db(db_path)
            try:
                parse_case(_case_from_xml(first), db, '2024-03-01')
                flush_write_buffer(db)
                parse_case(_case_from_xml(second), db, '2024-03-02')
                flush_write_buffer(db)
                counts = fetch_staging_row_counts(db)
            finally:
                db.close()

        self.assertEqual(counts['oca_index_staging'], 1)
        self.assertEqual(counts['oca_parties_staging'], 4)
        self.assertEqual(counts['oca_events_staging'], 3)

    def test_delete_short_circuit_keeps_metadata_only(self):
        case_id = 'LT-DELETE-001'
        live = build_case_xml(case_id, num_parties=2)
        deleted = build_case_xml(case_id, with_delete=True, num_parties=2)

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'staging.duckdb')
            db = _init_staging_db(db_path)
            try:
                parse_case(_case_from_xml(live), db, '2024-03-01')
                flush_write_buffer(db)
                parse_case(_case_from_xml(deleted), db, '2024-03-02')
                flush_write_buffer(db)
                meta = db.execute(
                    'SELECT updatedate, deletedate FROM oca_metadata_staging WHERE indexnumberid = ?',
                    (case_id,),
                ).fetchone()
                counts = fetch_staging_row_counts(db)
            finally:
                db.close()

        self.assertIsNone(meta[0])
        self.assertEqual(str(meta[1]), '2024-03-02')
        self.assertEqual(counts['oca_index_staging'], 1)
        self.assertEqual(counts['oca_parties_staging'], 2)

    def test_batched_path_matches_legacy_row_counts(self):
        xml_bytes = build_extract_xml(25, child_profile='weekly')
        with tempfile.TemporaryDirectory() as tmp:
            legacy_path = os.path.join(tmp, 'legacy.duckdb')
            batched_path = os.path.join(tmp, 'batched.duckdb')

            legacy_db = DuckDB(legacy_path)
            legacy_db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
            batched_db = DuckDB(batched_path)
            batched_db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
            attach_write_buffer(batched_db)

            xml_io = io.BytesIO(xml_bytes)
            try:
                os.environ['PARSE_WRITE_BATCH_ENABLED'] = '0'
                parse_file(xml_io, legacy_db, '2024-03-08', num_threads=1)
                xml_io.seek(0)
                parse_file(xml_io, batched_db, '2024-03-08', num_threads=1)
                flush_write_buffer(batched_db)
                legacy_counts = fetch_staging_row_counts(legacy_db)
                batched_counts = fetch_staging_row_counts(batched_db)
            finally:
                os.environ.pop('PARSE_WRITE_BATCH_ENABLED', None)
                legacy_db.close()
                batched_db.close()

        self.assertEqual(legacy_counts, batched_counts)

    def test_parse_file_end_to_end_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, 'incr.zip')
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr(DATA_FILENAME, build_extract_xml(10, child_profile='weekly'))

            db_path = os.path.join(tmp, 'staging.duckdb')
            db = _init_staging_db(db_path)
            try:
                with zipfile.ZipFile(zip_path, 'r').open(DATA_FILENAME) as xml_file:
                    parse_file(xml_file, db, '2024-03-08', num_threads=1)
                flush_write_buffer(db)
                counts = fetch_staging_row_counts(db)
            finally:
                db.close()

        self.assertEqual(counts['oca_index_staging'], 10)
        self.assertGreater(counts['oca_parties_staging'], 10)


class ParseWriteBufferTests(unittest.TestCase):
    def test_discard_case_drops_in_window_writes(self):
        from lib.parse_write_buffer import StagingWriteBuffer

        with tempfile.TemporaryDirectory() as tmp:
            db = DuckDB(os.path.join(tmp, 'buf.duckdb'))
            db.execute('CREATE TABLE t (id INTEGER, v VARCHAR)')
            buffer = StagingWriteBuffer(
                db,
                ParseWriteConfig(enabled=True, batch_size=100, flush_every_n_cases=10),
            )
            buffer.begin_case()
            buffer.queue_insert('INSERT INTO t VALUES (?, ?)', (1, 'orphan'))
            buffer.discard_case()
            buffer.flush()
            count = db.execute('SELECT COUNT(*) FROM t').fetchone()[0]
            db.close()
        self.assertEqual(count, 0)

    def test_flush_order_deletes_before_inserts(self):
        from lib.parse_write_buffer import StagingWriteBuffer

        with tempfile.TemporaryDirectory() as tmp:
            db = DuckDB(os.path.join(tmp, 'buf.duckdb'))
            db.execute('CREATE TABLE t (id INTEGER, v VARCHAR)')
            db.execute('INSERT INTO t VALUES (1, ?)', ('old',))
            buffer = StagingWriteBuffer(
                db,
                ParseWriteConfig(enabled=True, batch_size=100, flush_every_n_cases=10),
            )
            buffer.queue_delete('DELETE FROM t WHERE id = ?', (1,))
            buffer.queue_insert('INSERT INTO t VALUES (?, ?)', (1, 'new'))
            buffer.flush()
            row = db.execute('SELECT v FROM t WHERE id = 1').fetchone()
            db.close()
        self.assertEqual(row[0], 'new')

    def test_config_from_env(self):
        os.environ['PARSE_WRITE_BATCH_SIZE'] = '128'
        os.environ['PARSE_WRITE_FLUSH_EVERY_N_CASES'] = '8'
        try:
            cfg = ParseWriteConfig.from_env()
            self.assertEqual(cfg.batch_size, 128)
            self.assertEqual(cfg.flush_every_n_cases, 8)
        finally:
            os.environ.pop('PARSE_WRITE_BATCH_SIZE', None)
            os.environ.pop('PARSE_WRITE_FLUSH_EVERY_N_CASES', None)


class ParserBatchingParityExportTests(unittest.TestCase):
    def test_checksum_stable_with_batching_enabled(self):
        from parse_pipeline_helpers import run_parse_export_in_dir

        with tempfile.TemporaryDirectory() as tmp:
            priv = os.path.join(tmp, 'private')
            os.makedirs(priv)
            write_test_zip(
                os.path.join(priv, 'LandlordTenant.Incr.2024-03-08.zip'),
                20,
                child_profile='weekly',
            )

            os.environ['PARSE_WRITE_BATCH_ENABLED'] = '1'
            try:
                rows_on, checksums_on = run_parse_export_in_dir(priv, parse_num_threads=1)
            finally:
                os.environ.pop('PARSE_WRITE_BATCH_ENABLED', None)

            priv2 = os.path.join(tmp, 'private2')
            os.makedirs(priv2)
            write_test_zip(
                os.path.join(priv2, 'LandlordTenant.Incr.2024-03-08.zip'),
                20,
                child_profile='weekly',
            )
            os.environ['PARSE_WRITE_BATCH_ENABLED'] = '0'
            try:
                rows_off, checksums_off = run_parse_export_in_dir(priv2, parse_num_threads=1)
            finally:
                os.environ.pop('PARSE_WRITE_BATCH_ENABLED', None)

        self.assertEqual(checksums_on, checksums_off)
        self.assertEqual(rows_on, rows_off)


if __name__ == '__main__':
    unittest.main()
