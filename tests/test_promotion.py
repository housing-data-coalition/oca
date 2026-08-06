import unittest
from pathlib import Path
from unittest import mock

from lib.database import Database
from lib.etl_constants import OCA_TABLES
from lib.etl_promotion import (
    ADDRESS_NATURAL_KEY_COLUMNS,
    PROMOTION_SQL_FILE,
    PURGE_TOMBSTONED_CASES_SQL_FILE,
    promote_staging_to_main,
    promotion_counts_checksum,
    promotion_table_counts,
)


SQL_DIR = Path(__file__).resolve().parents[1] / 'lib' / 'sql'


class FakeConn:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def cursor(self):
        raise NotImplementedError


class PromoteStagingTests(unittest.TestCase):
    def test_promote_uses_single_transaction(self):
        db = mock.Mock()
        db.transaction.return_value.__enter__ = mock.Mock(return_value=db)
        db.transaction.return_value.__exit__ = mock.Mock(return_value=False)

        promote_staging_to_main(db)

        db.transaction.assert_called_once()
        db.execute_sql_file.assert_any_call('ensure_promotion_indexes.sql', commit=False)
        db.execute_sql_file.assert_any_call('promote_staging_to_main.sql', commit=False)

    def test_promotion_failure_rolls_back(self):
        conn = FakeConn()
        db = mock.Mock()
        db.conn = conn
        db.execute_sql_file.side_effect = RuntimeError('simulated promotion failure')

        def transaction():
            class _Txn:
                def __enter__(self_inner):
                    return db

                def __exit__(self_inner, exc_type, exc, tb):
                    if exc_type:
                        conn.rollback()
                        return False
                    conn.commit()
                    return False

            return _Txn()

        db.transaction.side_effect = transaction

        with self.assertRaises(RuntimeError):
            promote_staging_to_main(db)

        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)

    def test_promotion_success_commits_once(self):
        conn = FakeConn()
        db = mock.Mock()
        db.conn = conn

        def transaction():
            class _Txn:
                def __enter__(self_inner):
                    return db

                def __exit__(self_inner, exc_type, exc, tb):
                    if exc_type:
                        conn.rollback()
                        return False
                    conn.commit()
                    return False

            return _Txn()

        db.transaction.side_effect = transaction
        promote_staging_to_main(db)

        self.assertTrue(conn.committed)
        self.assertFalse(conn.rolled_back)

    def test_counts_checksum_stable(self):
        counts_a = {'oca_index': 1, 'oca_addresses': 2}
        counts_b = {'oca_addresses': 2, 'oca_index': 1}
        self.assertEqual(
            promotion_counts_checksum(counts_a),
            promotion_counts_checksum(counts_b),
        )


class PromoteStagingSqlContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = (SQL_DIR / PROMOTION_SQL_FILE).read_text(encoding='utf-8')

    def test_single_transaction_session_role_reset(self):
        self.assertIn('SET session_replication_role = replica', self.sql)
        self.assertIn('SET session_replication_role = default', self.sql)

    def test_oca_index_upsert_with_tombstone_purge(self):
        self.assertIn('ON CONFLICT (indexnumberid) DO UPDATE', self.sql)
        self.assertRegex(self.sql, r'DELETE FROM oca_index\b')
        self.assertGreaterEqual(self.sql.count('DELETE FROM oca_index'), 2)

    def test_tombstone_temp_tables_and_filtered_staging(self):
        self.assertIn('CREATE TEMP TABLE tombstoned_ids', self.sql)
        self.assertIn('CREATE TEMP TABLE promotion_active_staging_ids', self.sql)
        self.assertIn('oca_metadata_staging WHERE deletedate IS NOT NULL', self.sql)
        self.assertIn(
            'FROM oca_index_staging\nWHERE indexnumberid IN '
            '(SELECT indexnumberid FROM promotion_active_staging_ids)',
            self.sql,
        )

    def test_child_inserts_exclude_tombstones(self):
        self.assertIn(
            'FROM oca_causes_staging\n'
            'WHERE indexnumberid IN (SELECT indexnumberid FROM promotion_active_staging_ids)',
            self.sql,
        )

    def test_addresses_use_natural_key_delete(self):
        for col in ADDRESS_NATURAL_KEY_COLUMNS:
            if col == 'indexnumberid':
                continue
            self.assertIn(f'm.{col} IS NOT DISTINCT FROM s.{col}', self.sql)

    def test_metadata_merged_before_staging_drop(self):
        metadata_pos = self.sql.index('CREATE TABLE oca_metadata_temp')
        drop_index_pos = self.sql.index('DROP TABLE IF EXISTS oca_index_staging')
        self.assertLess(metadata_pos, drop_index_pos)

    def test_all_staging_tables_dropped(self):
        for table in OCA_TABLES:
            self.assertIn(f'DROP TABLE IF EXISTS {table}_staging', self.sql)


class PurgeTombstonedCasesSqlContractTests(unittest.TestCase):
    def test_purge_deletes_index_not_metadata(self):
        sql = (SQL_DIR / PURGE_TOMBSTONED_CASES_SQL_FILE).read_text(encoding='utf-8')
        self.assertRegex(sql, r'DELETE FROM oca_index\b')
        self.assertIn('oca_metadata', sql)
        self.assertNotRegex(sql, r'DELETE FROM oca_metadata\b')


class DatabaseTransactionTests(unittest.TestCase):
    @staticmethod
    def _mock_connection():
        conn = mock.Mock()
        cursor = mock.MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        conn.cursor.return_value = cursor
        return conn

    @mock.patch('lib.database.psycopg2.connect')
    def test_transaction_commits_on_success(self, connect_mock):
        conn = self._mock_connection()
        connect_mock.return_value = conn
        db = Database(db_url='postgres://example')
        with db.transaction():
            db.execute('SELECT 1')
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    @mock.patch('lib.database.psycopg2.connect')
    def test_transaction_rolls_back_on_error(self, connect_mock):
        conn = self._mock_connection()
        connect_mock.return_value = conn
        db = Database(db_url='postgres://example')
        with self.assertRaises(RuntimeError):
            with db.transaction():
                raise RuntimeError('fail')
        conn.rollback.assert_called_once()


class PromotionTableCountsTests(unittest.TestCase):
    def test_promotion_table_counts_queries_each_table(self):
        db = mock.Mock()
        db.sql_fetch_one.return_value = (42,)
        counts = promotion_table_counts(db, tables=['oca_index', 'oca_causes'])
        self.assertEqual(counts, {'oca_index': 42, 'oca_causes': 42})
        self.assertEqual(db.sql_fetch_one.call_count, 2)


class FakeManifest:
    def __init__(self):
        self.step_upserts = []
        self.file_details_by_name = {}

    def upsert_file(self, file_name, source, status, stage=None, details=None, error=None):
        if details is not None:
            self.file_details_by_name[file_name] = dict(details)

    def upsert_step(self, step_name, status, details=None, error=None):
        self.step_upserts.append({
            'step_name': step_name,
            'status': status,
            'details': details or {},
            'error': error,
        })


class ImportAndPromoteStagingObservabilityTests(unittest.TestCase):
    @mock.patch('lib.etl_stages.upsert_promoted_etl_file')
    @mock.patch('lib.etl_stages.promote_staging_to_main')
    @mock.patch('lib.etl_stages.ensure_core_tables_exist')
    @mock.patch('lib.etl_stages.staging_tables_with_rows', return_value=[])
    @mock.patch('lib.etl_stages.promotion_table_counts')
    @mock.patch('geosupport.Geosupport')
    def test_promote_step_records_before_after_checksums(
        self,
        _geosupport_mock,
        counts_mock,
        _staging_rows_mock,
        _ensure_tables_mock,
        _promote_mock,
        _upsert_file_mock,
    ):
        from lib.etl_stages import FileSelection, import_and_promote_staging

        counts_before = {'oca_index': 100, 'oca_metadata': 100}
        counts_after = {'oca_index': 150, 'oca_metadata': 150}
        counts_mock.side_effect = [counts_before, counts_after]

        manifest = FakeManifest()
        db = mock.Mock()
        selection = FileSelection(
            selected_zip_files=['test.zip'],
            skipped_reprocess_files=[],
            new_file_set={'test.zip'},
            reprocess_file_set=set(),
            sftp_download_files=['test.zip'],
            s3_download_files=[],
        )

        with mock.patch('lib.etl_stages.csv_has_rows', return_value=False):
            import_and_promote_staging(
                manifest,
                db,
                '/tmp/pub',
                {'aws_bucket_name': 'b', 'aws_id': 'i', 'aws_key': 'k'},
                '',
                selection,
                'public',
            )

        completed = [s for s in manifest.step_upserts if s['status'] == 'completed'][-1]
        self.assertEqual(completed['step_name'], 'promote_staging')
        details = completed['details']
        self.assertEqual(details['counts_before'], counts_before)
        self.assertEqual(details['counts_after'], counts_after)
        self.assertEqual(
            details['checksum_before'],
            promotion_counts_checksum(counts_before),
        )
        self.assertEqual(
            details['checksum_after'],
            promotion_counts_checksum(counts_after),
        )
        self.assertEqual(counts_mock.call_count, 2)
