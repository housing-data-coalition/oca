import importlib
import os
import unittest
from unittest.mock import MagicMock, patch

import oca_geocode_backfill


class GeocodeBackfillCliTests(unittest.TestCase):
    @patch('oca_geocode_backfill.run_geocode_backfill')
    def test_main_passes_db_and_runtime_args(self, run_mock):
        with patch.dict(os.environ, {
            'DATABASE_URL': 'postgres://example',
            'DB_SCHEMA': 'oca_refactor',
            'GEOCODE_WORKERS': '3',
            'CENSUS_BATCH_CHUNK_SIZE': '2000',
        }, clear=True), patch('sys.argv', ['oca_geocode_backfill.py']):
            oca_geocode_backfill.main()

        run_mock.assert_called_once_with(
            {'db_url': 'postgres://example', 'schema': 'oca_refactor'},
            {
                'db_schema': 'oca_refactor',
                'geocode_workers': 3,
                'census_batch_chunk_size': 2000,
            },
        )

    @patch('oca_geocode_backfill.geocode_addresses', return_value=5)
    @patch('oca_geocode_backfill.make_dir', return_value='/tmp/data-public')
    @patch('oca_geocode_backfill.EtlRunManifest')
    @patch('oca_geocode_backfill.Database')
    def test_run_geocode_backfill_uses_rds_geocode_path(
        self,
        db_cls,
        manifest_cls,
        make_dir_mock,
        geocode_mock,
    ):
        fake_db = MagicMock()
        db_cls.return_value = fake_db
        fake_manifest = MagicMock()
        manifest_cls.return_value = fake_manifest

        count = oca_geocode_backfill.run_geocode_backfill(
            {'db_url': 'postgres://example', 'schema': 'oca_refactor'},
            {
                'db_schema': 'oca_refactor',
                'geocode_workers': 2,
                'census_batch_chunk_size': 1000,
            },
        )

        self.assertEqual(count, 5)
        manifest_cls.assert_called_once_with(
            db=fake_db,
            schema_name='oca_refactor',
            s3_prefix='',
            mode='geocode_backfill',
            reprocess_glob='',
            force_reprocess=False,
        )
        fake_manifest.setup_tables.assert_called_once()
        fake_manifest.create_run.assert_called_once()
        fake_db.ensure_connection.assert_called_once()
        geocode_mock.assert_called_once_with(
            fake_manifest,
            fake_db,
            '/tmp/data-public',
            2,
            1000,
        )
        fake_manifest.mark_run_completed.assert_called_once_with(0, 0, 0)

    @patch('oca_geocode_backfill.geocode_addresses', side_effect=RuntimeError('boom'))
    @patch('oca_geocode_backfill.make_dir', return_value='/tmp/data-public')
    @patch('oca_geocode_backfill.EtlRunManifest')
    @patch('oca_geocode_backfill.Database')
    def test_run_geocode_backfill_marks_manifest_failed_on_error(
        self,
        db_cls,
        manifest_cls,
        make_dir_mock,
        geocode_mock,
    ):
        fake_db = MagicMock()
        db_cls.return_value = fake_db
        fake_manifest = MagicMock()
        manifest_cls.return_value = fake_manifest

        with self.assertRaises(RuntimeError):
            oca_geocode_backfill.run_geocode_backfill(
                {'db_url': 'postgres://example', 'schema': 'public'},
                {'geocode_workers': 1, 'census_batch_chunk_size': 2500},
            )

        fake_manifest.mark_run_failed.assert_called_once()
        fake_manifest.mark_run_completed.assert_not_called()

    def test_not_wired_into_weekly_etl_entrypoints(self):
        etl = importlib.import_module('lib.etl')
        oca_update = importlib.import_module('oca_update')

        self.assertNotIn('oca_geocode_backfill', etl.__dict__)
        self.assertNotIn('geocode_backfill', etl.__dict__)
        self.assertNotIn('oca_geocode_backfill', oca_update.__dict__)
        self.assertNotIn('run_geocode_backfill', oca_update.__dict__)


if __name__ == '__main__':
    unittest.main()
