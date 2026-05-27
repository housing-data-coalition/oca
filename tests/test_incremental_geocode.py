import os
import tracemalloc
import unittest
from unittest import mock

from lib.etl_geocode import (
    GEOCODE_ADDRESS_COLUMNS,
    fetch_addresses_needing_geocode,
    geocode_candidate_records,
    row_needs_geocode,
    upsert_geocoded_addresses,
)
from lib.etl_stages import geocode_and_publish_addresses


class RowNeedsGeocodeTests(unittest.TestCase):
    def test_missing_lat_with_house_number(self):
        self.assertTrue(row_needs_geocode({'lat': '', 'house_number': '123'}))

    def test_existing_lat_skipped(self):
        self.assertFalse(row_needs_geocode({'lat': '40.7', 'house_number': '123'}))

    def test_missing_house_number_skipped(self):
        self.assertFalse(row_needs_geocode({'lat': '', 'house_number': ''}))


class GeocodeCandidateRecordsTests(unittest.TestCase):
    def test_only_missing_lat_rows_sent_to_census(self):
        records = [
            {'indexnumberid': 'a', 'lat': '', 'house_number': '1', 'street1': '1 Main', 'city': 'NYC', 'postalcode': '10001'},
            {'indexnumberid': 'b', 'lat': '', 'house_number': '2', 'street1': '2 Main', 'city': 'NYC', 'postalcode': '10002'},
        ]

        def fake_geocode_record(row, addr_cols):
            row = dict(row)
            if row['indexnumberid'] == 'a':
                row['lat'] = '40.1'
                row['lon'] = '-73.9'
            return row

        census_calls = []

        def fake_census_batch(dataframe, pub_dir):
            census_calls.append(list(dataframe['indexnumberid']))
            dataframe = dataframe.copy()
            dataframe['lat'] = '40.2'
            dataframe['lon'] = '-73.8'
            return dataframe

        results = geocode_candidate_records(
            records,
            geocode_workers=1,
            census_batch_chunk_size=2500,
            pub_dir='/tmp',
            geocode_record_fn=fake_geocode_record,
            geocode_using_census_batch_fn=fake_census_batch,
        )

        self.assertEqual(census_calls, [['b']])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['lat'], '40.1')
        self.assertEqual(results[1]['lat'], '40.2')

    def test_empty_candidates_skips_geocoders(self):
        geocode_mock = mock.Mock()
        results = geocode_candidate_records(
            [],
            geocode_workers=1,
            census_batch_chunk_size=2500,
            pub_dir='/tmp',
            geocode_record_fn=geocode_mock,
        )
        self.assertEqual(results, [])
        geocode_mock.assert_not_called()

    def test_idempotent_rerun_fetches_no_candidates(self):
        fake_db = mock.Mock()
        fake_db.sql_fetch_all_from_file.return_value = []
        first = fetch_addresses_needing_geocode(fake_db)
        second = fetch_addresses_needing_geocode(fake_db)
        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual(fake_db.sql_fetch_all_from_file.call_count, 2)


class FetchAddressesNeedingGeocodeTests(unittest.TestCase):
    def test_fetch_uses_sql_file(self):
        fake_db = mock.Mock()
        fake_db.sql_fetch_all_from_file.return_value = [
            tuple('' if col == 'lat' else f'val-{col}' for col in GEOCODE_ADDRESS_COLUMNS),
        ]

        rows = fetch_addresses_needing_geocode(fake_db)

        fake_db.sql_fetch_all_from_file.assert_called_once_with(
            'select_addresses_needing_geocode.sql'
        )
        self.assertEqual(rows[0]['indexnumberid'], 'val-indexnumberid')
        self.assertEqual(rows[0]['lat'], '')


class UpsertGeocodedAddressesTests(unittest.TestCase):
    def test_upsert_writes_staging_and_merges(self):
        fake_db = mock.Mock()
        rows = [{'indexnumberid': 'a', 'lat': '40.1', 'lon': '-73.9', 'house_number': '1'}]

        count = upsert_geocoded_addresses(fake_db, rows)

        self.assertEqual(count, 1)
        fake_db.execute_sql_file.assert_any_call('create_geocode_staging_table.sql')
        fake_db.insert_rows.assert_called_once()
        fake_db.execute_sql_file.assert_any_call('upsert_geocoded_addresses.sql')

    def test_empty_rows_skips_db_writes(self):
        fake_db = mock.Mock()
        count = upsert_geocoded_addresses(fake_db, [])
        self.assertEqual(count, 0)
        fake_db.execute_sql_file.assert_not_called()


class GeocodeStageIntegrationTests(unittest.TestCase):
    def test_geocode_stage_skips_reset_and_s3_import(self):
        fake_db = mock.Mock()
        fake_db.sql_fetch_all_from_file.return_value = []
        fake_manifest = mock.Mock()
        fake_s3 = mock.Mock()
        fake_s3.list_files.return_value = []
        selection = mock.Mock(selected_zip_files=['file.zip'])

        with mock.patch('lib.etl_stages.create_date_files'), \
             mock.patch('lib.etl_stages.upload_public_file'), \
             mock.patch('os.listdir', return_value=[]):
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
            )

        executed_files = [
            call.args[0]
            for call in fake_db.execute_sql_file.call_args_list
        ]
        self.assertNotIn('reset_addresses_table.sql', executed_files)
        import_calls = [
            call for call in fake_db.sql.call_args_list
            if call.args and 'table_import_from_s3' in call.args[0]
        ]
        self.assertEqual(import_calls, [])

    def test_geocode_stage_delta_path_invoked(self):
        fake_db = mock.Mock()
        fake_db.sql_fetch_all_from_file.return_value = [
            (
                'case-1', '1 Main', '', 'NYC', 'NY', '10001', '', '1', 'Main',
                '', '', '', '', '', '', None, '', '', '', '', '', '', '', '', None, '',
            ),
        ]
        fake_manifest = mock.Mock()
        fake_s3 = mock.Mock()
        fake_s3.list_files.return_value = []
        selection = mock.Mock(selected_zip_files=['file.zip'])

        with mock.patch('lib.etl_stages.geocode_candidate_records', return_value=[{'indexnumberid': 'case-1', 'lat': '40.1'}]) as geocode_mock, \
             mock.patch('lib.etl_stages.upsert_geocoded_addresses', return_value=1) as upsert_mock, \
             mock.patch('lib.etl_stages.create_date_files'), \
             mock.patch('lib.etl_stages.upload_public_file'), \
             mock.patch('os.listdir', return_value=[]):
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
                geocode_workers=2,
                census_batch_chunk_size=1000,
            )

        geocode_mock.assert_called_once()
        upsert_mock.assert_called_once()
        self.assertEqual(geocode_mock.call_args.args[1], 2)
        self.assertEqual(geocode_mock.call_args.args[2], 1000)


class GeocodeMemoryTests(unittest.TestCase):
    def test_candidate_only_geocode_uses_bounded_memory(self):
        records = [
            {
                'indexnumberid': f'id-{i}',
                'lat': '',
                'house_number': str(i),
                'street1': f'{i} Main St',
                'city': 'NYC',
                'postalcode': '10001',
            }
            for i in range(5000)
        ]

        def fake_geocode_record(row, addr_cols):
            row = dict(row)
            row['lat'] = '40.0'
            row['lon'] = '-73.0'
            return row

        tracemalloc.start()
        geocode_candidate_records(
            records,
            geocode_workers=1,
            census_batch_chunk_size=2500,
            pub_dir='/tmp',
            geocode_record_fn=fake_geocode_record,
            geocode_using_census_batch_fn=mock.Mock(),
        )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Candidate-only path should stay well under a 2GB envelope on sample data.
        self.assertLess(peak, 50 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
