import os
import unittest
from unittest.mock import MagicMock, patch

import oca_update
from lib.database import Database


class RuntimeControlTests(unittest.TestCase):
    @patch('oca_update.oca_etl')
    def test_main_passes_defaults_when_unset(self, oca_etl_mock):
        with patch.dict(os.environ, {
            'DATABASE_URL': 'postgres://example',
            'AWS_ACCESS_KEY_ID': 'id',
            'AWS_SECRET_ACCESS_KEY': 'key',
            'AWS_S3_BUCKET_NAME': 'bucket',
            'SFTP_HOST': 'host',
            'SFTP_USER': 'user',
            'SFTP_PSWD': 'pswd',
            'SFTP_DIR': '/incoming',
            'MODE': '2',
        }, clear=True), patch('sys.argv', ['oca_update.py']):
            oca_update.main()

        call_args = oca_etl_mock.call_args[0]
        db_args = call_args[0]
        runtime_args = call_args[5]
        self.assertEqual(db_args['schema'], '')
        self.assertEqual(runtime_args['db_schema'], '')
        self.assertEqual(runtime_args['s3_prefix'], '')
        self.assertEqual(runtime_args['reprocess_glob'], '')
        self.assertFalse(runtime_args['force_reprocess'])
        self.assertFalse(runtime_args['parse_fail_fast'])

    @patch('oca_update.oca_etl')
    def test_main_non_default_schema_smoke_path(self, oca_etl_mock):
        with patch.dict(os.environ, {
            'DATABASE_URL': 'postgres://example',
            'AWS_ACCESS_KEY_ID': 'id',
            'AWS_SECRET_ACCESS_KEY': 'key',
            'AWS_S3_BUCKET_NAME': 'bucket',
            'SFTP_HOST': 'host',
            'SFTP_USER': 'user',
            'SFTP_PSWD': 'pswd',
            'SFTP_DIR': '/incoming',
            'MODE': '2',
            'DB_SCHEMA': 'oca_refactor',
            'S3_PREFIX': 'refactor/dev',
            'REPROCESS_GLOB': 'LandlordTenant.Incr.2024-*.zip',
            'FORCE_REPROCESS': 'true',
            'PARSE_FAIL_FAST': 'true',
            'GEOCODE_WORKERS': '3',
            'CENSUS_BATCH_CHUNK_SIZE': '2000',
            'CSV_ROW_CHECK_CHUNK_SIZE': '500',
        }, clear=True), patch('sys.argv', ['oca_update.py']):
            oca_update.main()

        db_args = oca_etl_mock.call_args[0][0]
        runtime_args = oca_etl_mock.call_args[0][5]
        self.assertEqual(db_args['schema'], 'oca_refactor')
        self.assertEqual(runtime_args['s3_prefix'], 'refactor/dev')
        self.assertEqual(runtime_args['reprocess_glob'], 'LandlordTenant.Incr.2024-*.zip')
        self.assertTrue(runtime_args['force_reprocess'])
        self.assertEqual(runtime_args['geocode_workers'], 3)
        self.assertTrue(runtime_args['parse_fail_fast'])

    @patch('lib.database.psycopg2.connect')
    def test_database_sets_search_path_for_schema(self, connect_mock):
        conn = MagicMock()
        connect_mock.return_value = conn

        Database(db_url='postgres://example', schema='oca_refactor')

        conn.cursor.return_value.__enter__.return_value.execute.assert_called_once()
        execute_arg = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        self.assertIn('search_path', str(execute_arg))
        self.assertEqual(conn.commit.call_count, 1)


if __name__ == '__main__':
    unittest.main()
