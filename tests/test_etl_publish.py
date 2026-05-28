import os
import tempfile
import unittest
from unittest import mock

from lib.etl_publish import (
    should_publish_address_exports,
    staging_tables_with_rows,
)
from lib.etl_stages import geocode_and_publish_addresses


class StagingTablesWithRowsTests(unittest.TestCase):
    def test_detects_non_empty_staging_csv(self):
        with tempfile.TemporaryDirectory() as pub_dir:
            path = os.path.join(pub_dir, 'oca_addresses_staging.csv')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('indexnumberid\n')
                handle.write('case-1\n')
            found = staging_tables_with_rows(pub_dir)
        self.assertEqual(found, {'oca_addresses'})

    def test_empty_staging_csv_excluded(self):
        with tempfile.TemporaryDirectory() as pub_dir:
            path = os.path.join(pub_dir, 'oca_index_staging.csv')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('indexnumberid\n')
            found = staging_tables_with_rows(pub_dir)
        self.assertEqual(found, set())


class ShouldPublishAddressExportsTests(unittest.TestCase):
    def test_publish_when_geocode_candidates(self):
        self.assertTrue(should_publish_address_exports(set(), 3))

    def test_publish_when_addresses_staging_had_rows(self):
        self.assertTrue(should_publish_address_exports({'oca_addresses'}, 0))

    def test_skip_when_no_address_changes(self):
        self.assertFalse(should_publish_address_exports({'oca_index'}, 0))
        self.assertFalse(should_publish_address_exports(set(), 0))


class GeocodePublishSkipTests(unittest.TestCase):
    def test_skips_address_exports_when_unchanged(self):
        fake_db = mock.Mock()
        fake_db.sql_fetch_all_from_file.return_value = []
        fake_manifest = mock.Mock()
        fake_s3 = mock.Mock()
        selection = mock.Mock(selected_zip_files=['file.zip'])

        with mock.patch('lib.etl_stages.create_date_files'), \
             mock.patch('lib.etl_stages.upload_public_file'), \
             mock.patch('lib.etl_stages.multiprocessing.Pool') as pool_mock, \
             mock.patch('lib.etl_stages.normalize_published_s3_encryption') as encrypt_mock, \
             mock.patch('os.listdir', return_value=[]):
            pool_mock.return_value.__enter__.return_value.starmap.return_value = []
            geocode_and_publish_addresses(
                fake_manifest,
                fake_db,
                fake_s3,
                '/tmp/priv',
                '/tmp/pub',
                {'aws_bucket_name': 'bucket', 'aws_id': 'id', 'aws_key': 'key'},
                'refactor/',
                '2',
                selection,
                geocode_workers=1,
                census_batch_chunk_size=2500,
                staging_tables_with_data={'oca_index'},
                published_core_keys=['refactor/public/oca_index.csv'],
            )

        fake_db.export_csv.assert_not_called()
        view_exports = [
            call for call in fake_db.sql.call_args_list
            if call.args and 'query_export_to_s3' in call.args[0]
        ]
        self.assertEqual(view_exports, [])
        encrypt_mock.assert_called_once()
        encrypted_keys = encrypt_mock.call_args[0][2]
        self.assertIn('refactor/public/oca_index.csv', encrypted_keys)
        self.assertNotIn('refactor/public/oca_addresses.csv', encrypted_keys)


if __name__ == '__main__':
    unittest.main()
