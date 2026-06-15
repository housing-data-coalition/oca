import csv
import os
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from lib.etl_geocode import (
    ADDRESS_ROW_KEY_COLUMNS,
    GEOCODE_ADDRESS_COLUMNS,
    GEOCODED_STAGING_ADDRESSES_CSV,
    STAGING_ADDRESSES_CSV,
    _run_census_batch,
    address_row_key,
    fetch_addresses_needing_geocode,
    geocode_candidate_records,
    geocode_staging_addresses_csv,
    read_staging_addresses_csv,
    row_needs_geocode,
    upsert_geocoded_addresses,
    write_geocoded_staging_csv,
)
from lib.etl_stages import geocode_addresses, geocode_staging_csvs


class RowNeedsGeocodeTests(unittest.TestCase):
    def test_missing_lat_with_house_number(self):
        self.assertTrue(row_needs_geocode({'lat': '', 'house_number': '123'}))

    def test_existing_lat_skipped(self):
        self.assertFalse(row_needs_geocode({'lat': '40.7', 'house_number': '123'}))

    def test_missing_lat_needs_geocode_regardless_of_house_number(self):
        self.assertTrue(row_needs_geocode({'lat': '', 'house_number': ''}))


class RunCensusBatchTests(unittest.TestCase):
    def test_chunks_are_dataframes_with_multiple_splits(self):
        still_missing = [
            {
                'indexnumberid': f'id-{i}',
                'lat': '',
                'house_number': str(i),
                'street_name': 'Main St',
                'postalcode': '10001',
            }
            for i in range(3)
        ]
        chunk_sizes = []

        def fake_census_batch(dataframe, pub_dir):
            self.assertIsInstance(dataframe, pd.DataFrame)
            chunk_sizes.append(len(dataframe))
            out = dataframe.copy()
            out['lat'] = '40.0'
            out['lon'] = '-73.0'
            return out

        results = _run_census_batch(
            still_missing,
            census_batch_chunk_size=2,
            pub_dir='/tmp',
            geocode_using_census_batch_fn=fake_census_batch,
        )

        self.assertEqual(chunk_sizes, [2, 1])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(results[0]), 2)
        self.assertEqual(len(results[1]), 1)


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

    def test_multi_address_same_case_distinct_geocodes(self):
        """Same indexnumberid, different street1 — each row keeps its own geocode."""
        shared_id = 'case-multi'
        records = [
            {
                'indexnumberid': shared_id,
                'lat': '',
                'house_number': '1',
                'street1': '100 Main St',
                'street2': '',
                'city': 'NYC',
                'state': 'NY',
                'postalcode': '10001',
            },
            {
                'indexnumberid': shared_id,
                'lat': '',
                'house_number': '2',
                'street1': '200 Oak Ave',
                'street2': 'Apt 3',
                'city': 'NYC',
                'state': 'NY',
                'postalcode': '10002',
            },
        ]

        def fake_geocode_record(row, addr_cols):
            row = dict(row)
            if row['street1'] == '100 Main St':
                row['lat'] = '40.100'
                row['lon'] = '-73.100'
            return row

        def fake_census_batch(dataframe, pub_dir):
            dataframe = dataframe.copy()
            lats = []
            lons = []
            for street1 in dataframe['street1']:
                if street1 == '200 Oak Ave':
                    lats.append('40.200')
                    lons.append('-73.200')
                else:
                    lats.append('')
                    lons.append('')
            dataframe['lat'] = lats
            dataframe['lon'] = lons
            return dataframe

        results = geocode_candidate_records(
            records,
            geocode_workers=1,
            census_batch_chunk_size=2500,
            pub_dir='/tmp',
            geocode_record_fn=fake_geocode_record,
            geocode_using_census_batch_fn=fake_census_batch,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['street1'], '100 Main St')
        self.assertEqual(results[0]['lat'], '40.100')
        self.assertEqual(results[1]['street1'], '200 Oak Ave')
        self.assertEqual(results[1]['lat'], '40.200')
        self.assertNotEqual(results[0]['lat'], results[1]['lat'])
        self.assertEqual(
            address_row_key(results[0]),
            address_row_key(records[0]),
        )
        self.assertEqual(
            address_row_key(results[1]),
            address_row_key(records[1]),
        )

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


class AddressRowKeyTests(unittest.TestCase):
    def test_address_row_key_normalizes_none(self):
        row = {
            'indexnumberid': 'case-1',
            'street1': '1 Main',
            'street2': None,
            'city': 'NYC',
            'state': 'NY',
            'postalcode': '10001',
        }
        self.assertEqual(
            address_row_key(row),
            ('case-1', '1 Main', '', 'NYC', 'NY', '10001'),
        )

    def test_distinct_keys_for_different_street1(self):
        base = {
            'indexnumberid': 'case-1',
            'street2': '',
            'city': 'NYC',
            'state': 'NY',
            'postalcode': '10001',
        }
        key_a = address_row_key({**base, 'street1': '100 Main St'})
        key_b = address_row_key({**base, 'street1': '200 Oak Ave'})
        self.assertNotEqual(key_a, key_b)


class UpsertGeocodedAddressesSqlTests(unittest.TestCase):
    def test_upsert_sql_matches_on_natural_address_key(self):
        sql_path = Path(__file__).resolve().parents[1] / 'lib' / 'sql' / 'upsert_geocoded_addresses.sql'
        sql = sql_path.read_text()
        for col in ADDRESS_ROW_KEY_COLUMNS:
            self.assertIn(
                f'o.{col} IS NOT DISTINCT FROM s.{col}',
                sql,
                f'expected null-safe join on {col}',
            )
        self.assertNotRegex(
            sql,
            r'WHERE\s+o\.indexnumberid\s*=\s*s\.indexnumberid\s*;',
            'upsert must not join on indexnumberid alone',
        )
        self.assertIn('geom = ST_SetSRID(ST_Point(s.lon, s.lat), 4326)', sql)


class UpsertGeocodedAddressesTests(unittest.TestCase):
    def test_upsert_writes_staging_and_merges(self):
        fake_db = mock.Mock()
        rows = [{'indexnumberid': 'a', 'lat': '40.1', 'lon': '-73.9', 'house_number': '1'}]

        count = upsert_geocoded_addresses(fake_db, rows)

        self.assertEqual(count, 1)
        fake_db.set_statement_timeout.assert_called_once()
        fake_db.execute_sql_file.assert_any_call('create_geocode_staging_table.sql')
        fake_db.insert_rows.assert_called_once()
        fake_db.execute_sql_file.assert_any_call('upsert_geocoded_addresses.sql')

    def test_empty_rows_skips_db_writes(self):
        fake_db = mock.Mock()
        count = upsert_geocoded_addresses(fake_db, [])
        self.assertEqual(count, 0)
        fake_db.execute_sql_file.assert_not_called()


class StagingCsvGeocodeTests(unittest.TestCase):
    def _write_staging_csv(self, pub_dir, rows):
        path = os.path.join(pub_dir, STAGING_ADDRESSES_CSV)
        fieldnames = list(GEOCODE_ADDRESS_COLUMNS)
        with open(path, 'w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for row in rows:
                writer.writerow({col: row.get(col, '') for col in fieldnames})

    def test_read_and_write_round_trip(self):
        with tempfile.TemporaryDirectory() as pub_dir:
            rows_in = [
                {
                    'indexnumberid': 'case-1',
                    'street1': '1 Main',
                    'street2': '',
                    'city': 'NYC',
                    'state': 'NY',
                    'postalcode': '10001',
                    'lat': '',
                    'lon': '',
                },
            ]
            self._write_staging_csv(pub_dir, rows_in)
            read_rows, fieldnames = read_staging_addresses_csv(pub_dir)
            self.assertEqual(len(read_rows), 1)
            self.assertIn('indexnumberid', fieldnames)

            read_rows[0]['lat'] = '40.1'
            read_rows[0]['lon'] = '-73.9'
            write_geocoded_staging_csv(pub_dir, read_rows, fieldnames, STAGING_ADDRESSES_CSV)
            reread, _ = read_staging_addresses_csv(pub_dir)
            self.assertEqual(reread[0]['lat'], '40.1')

    def test_geocode_staging_overwrites_staging_csv(self):
        with tempfile.TemporaryDirectory() as pub_dir:
            self._write_staging_csv(pub_dir, [
                {
                    'indexnumberid': 'case-1',
                    'street1': '1 Main',
                    'street2': '',
                    'city': 'NYC',
                    'state': 'NY',
                    'postalcode': '10001',
                    'lat': '',
                    'lon': '',
                },
            ])

            def fake_geocode_record(row, addr_cols):
                row = dict(row)
                row['lat'] = '40.5'
                row['lon'] = '-73.5'
                row['house_number'] = '1'
                return row

            count = geocode_staging_addresses_csv(
                pub_dir,
                geocode_workers=1,
                census_batch_chunk_size=2500,
                geocode_record_fn=fake_geocode_record,
                geocode_using_census_batch_fn=mock.Mock(),
            )
            self.assertEqual(count, 1)
            self.assertTrue(os.path.exists(os.path.join(pub_dir, GEOCODED_STAGING_ADDRESSES_CSV)))
            staging_rows, _ = read_staging_addresses_csv(pub_dir)
            self.assertEqual(staging_rows[0]['lat'], '40.5')

    def test_geocode_staging_geocodes_all_rows_not_only_missing_lat(self):
        with tempfile.TemporaryDirectory() as pub_dir:
            self._write_staging_csv(pub_dir, [
                {
                    'indexnumberid': 'has-lat',
                    'street1': '10 Main',
                    'street2': '',
                    'city': 'NYC',
                    'state': 'NY',
                    'postalcode': '10001',
                    'lat': '40.0',
                    'lon': '-74.0',
                },
                {
                    'indexnumberid': 'no-lat',
                    'street1': '20 Main',
                    'street2': '',
                    'city': 'NYC',
                    'state': 'NY',
                    'postalcode': '10002',
                    'lat': '',
                    'lon': '',
                },
            ])
            seen_ids = []

            def fake_geocode_record(row, addr_cols):
                seen_ids.append(row['indexnumberid'])
                row = dict(row)
                row['lat'] = f"40.{row['indexnumberid']}"
                row['lon'] = '-73.0'
                return row

            geocode_staging_addresses_csv(
                pub_dir,
                geocode_workers=1,
                census_batch_chunk_size=2500,
                geocode_record_fn=fake_geocode_record,
                geocode_using_census_batch_fn=mock.Mock(),
            )
            self.assertEqual(seen_ids, ['has-lat', 'no-lat'])

    def test_geocode_staging_stage_records_manifest(self):
        fake_manifest = mock.Mock()
        with tempfile.TemporaryDirectory() as pub_dir:
            with mock.patch(
                'lib.etl_stages.geocode_staging_addresses_csv',
                return_value=3,
            ) as geocode_mock:
                count = geocode_staging_csvs(
                    fake_manifest, pub_dir, geocode_workers=2, census_batch_chunk_size=1000,
                )
        self.assertEqual(count, 3)
        geocode_mock.assert_called_once_with(pub_dir, 2, 1000)
        fake_manifest.upsert_step.assert_any_call('geocode_staging', 'running')
        fake_manifest.upsert_step.assert_any_call(
            'geocode_staging',
            'completed',
            details={'geocoded_row_count': 3},
        )


class GeocodeStageIntegrationTests(unittest.TestCase):
    def test_geocode_stage_skips_reset_and_s3_import(self):
        fake_db = mock.Mock()
        fake_db.sql_fetch_all_from_file.return_value = []
        fake_manifest = mock.Mock()
        fake_s3 = mock.Mock()
        fake_s3.list_files.return_value = []
        selection = mock.Mock(selected_zip_files=['file.zip'])

        with mock.patch('lib.etl_stages.fetch_addresses_needing_geocode', return_value=[]), \
             mock.patch('lib.etl_stages.geocode_candidate_records', return_value=[]), \
             mock.patch('lib.etl_stages.upsert_geocoded_addresses', return_value=0):
            geocode_addresses(
                fake_manifest,
                fake_db,
                '/tmp/pub',
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

        with mock.patch('lib.etl_stages.geocode_candidate_records', return_value=[{'indexnumberid': 'case-1', 'lat': '40.1'}]) as geocode_mock, \
             mock.patch('lib.etl_stages.upsert_geocoded_addresses', return_value=1) as upsert_mock:
            geocode_addresses(
                fake_manifest,
                fake_db,
                '/tmp/pub',
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
