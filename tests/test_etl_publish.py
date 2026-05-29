import os
import tempfile
import unittest
from unittest import mock

from lib.etl_publish import (
    ADDRESS_VIEW_EXPORTS,
    PRIVATE_ADDRESS_CSV,
    published_keys_for_encryption,
    staging_tables_with_rows,
)
from lib.etl_stages import (
    geocode_addresses,
    normalize_public_s3_encryption,
    publish_public_artifacts,
)


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


class PublishedKeysForEncryptionTests(unittest.TestCase):
    def test_excludes_private_address_csv(self):
        keys = [
            'refactor/public/oca_index.csv',
            'refactor/public/oca_addresses_private.csv',
            'public/oca_addresses_private.csv',
        ]
        filtered = published_keys_for_encryption(keys)
        self.assertEqual(
            filtered,
            ['refactor/public/oca_index.csv'],
        )

    def test_dedupes_and_sorts(self):
        keys = [
            'refactor/public/oca_index.csv',
            'refactor/public/oca_index.csv',
            '',
        ]
        self.assertEqual(
            published_keys_for_encryption(keys),
            ['refactor/public/oca_index.csv'],
        )

    def test_private_constant_matches_suffix(self):
        self.assertTrue(PRIVATE_ADDRESS_CSV.endswith('oca_addresses_private.csv'))


class PublishPublicArtifactsTests(unittest.TestCase):
    def test_always_exports_core_and_views(self):
        fake_db = mock.Mock()
        fake_manifest = mock.Mock()
        selection = mock.Mock(selected_zip_files=['LandlordTenant.Incr.2024-03-08.zip'])
        s3_args = {'aws_bucket_name': 'bucket', 'aws_id': 'id', 'aws_key': 'key'}

        with mock.patch('lib.etl_stages.publish_core_tables', return_value=['refactor/public/oca_index.csv']) as core_mock, \
             mock.patch('lib.etl_stages.export_table_to_s3', side_effect=[
                 'refactor/public/oca_addresses_with_bbl.csv',
                 'refactor/public/oca_addresses_with_ct.csv',
                 'refactor/public/oca_addresses.csv',
             ]) as view_export_mock, \
             mock.patch('lib.etl_stages.create_date_files'), \
             mock.patch('lib.etl_stages.upload_public_file'), \
             mock.patch('lib.etl_stages.multiprocessing.Pool') as pool_mock:
            pool_mock.return_value.__enter__.return_value.starmap.return_value = []
            published_keys = publish_public_artifacts(
                fake_manifest,
                fake_db,
                s3_args,
                'refactor/',
                '2',
                selection,
                '/tmp/pub',
            )

        fake_db.execute_sql_file.assert_called_once_with('create_addresses_views.sql')
        core_mock.assert_called_once_with(fake_db, s3_args, 'refactor/')
        self.assertEqual(view_export_mock.call_count, len(ADDRESS_VIEW_EXPORTS))
        self.assertEqual(len(published_keys), 1 + len(ADDRESS_VIEW_EXPORTS) + 2)

    def test_create_addresses_views_before_exports(self):
        call_order = []
        fake_db = mock.Mock()
        fake_db.execute_sql_file.side_effect = lambda name: call_order.append(name)

        fake_manifest = mock.Mock()
        selection = mock.Mock(selected_zip_files=['file.2024-03-08.zip'])

        def track_core(*args, **kwargs):
            call_order.append('publish_core_tables')
            return []

        with mock.patch('lib.etl_stages.publish_core_tables', side_effect=track_core), \
             mock.patch('lib.etl_stages.export_table_to_s3', side_effect=lambda *a, **k: call_order.append('export_view') or 'k'), \
             mock.patch('lib.etl_stages.create_date_files'), \
             mock.patch('lib.etl_stages.upload_public_file'), \
             mock.patch('lib.etl_stages.multiprocessing.Pool') as pool_mock:
            pool_mock.return_value.__enter__.return_value.starmap.return_value = []
            publish_public_artifacts(
                fake_manifest, fake_db,
                {'aws_bucket_name': 'b', 'aws_id': 'i', 'aws_key': 'k'},
                '', '2', selection, '/tmp/pub',
            )

        views_idx = call_order.index('create_addresses_views.sql')
        core_idx = call_order.index('publish_core_tables')
        export_idx = call_order.index('export_view')
        self.assertLess(views_idx, core_idx)
        self.assertLess(core_idx, export_idx)


class GeocodeAddressesTests(unittest.TestCase):
    def test_geocode_does_not_export_to_s3(self):
        fake_db = mock.Mock()
        fake_manifest = mock.Mock()

        with mock.patch('lib.etl_stages.fetch_addresses_needing_geocode', return_value=[]), \
             mock.patch('lib.etl_stages.geocode_candidate_records', return_value=[]), \
             mock.patch('lib.etl_stages.upsert_geocoded_addresses', return_value=0):
            geocode_addresses(fake_manifest, fake_db, '/tmp/pub', 1, 2500)

        fake_db.sql.assert_not_called()
        fake_db.execute_sql_file.assert_not_called()


class NormalizePublicS3EncryptionTests(unittest.TestCase):
    def test_delegates_with_filtered_keys(self):
        fake_manifest = mock.Mock()
        fake_s3 = mock.Mock()
        published = [
            'refactor/public/oca_index.csv',
            'refactor/public/oca_addresses_private.csv',
        ]

        with mock.patch('lib.etl_stages.normalize_published_s3_encryption') as encrypt_mock:
            normalize_public_s3_encryption(fake_manifest, fake_s3, published)

        encrypt_mock.assert_called_once_with(
            fake_s3,
            published,
        )


if __name__ == '__main__':
    unittest.main()
