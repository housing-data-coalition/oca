import functools
import multiprocessing
import os
from itertools import repeat

import numpy as np
import pandas as pd

from .geocode_record import geocode_record, geocode_using_census_batch

ADDRESS_ROW_KEY_COLUMNS = [
    'indexnumberid', 'street1', 'street2', 'city', 'state', 'postalcode',
]

GEOCODE_ADDRESS_COLUMNS = [
    'indexnumberid', 'street1', 'street2', 'city', 'state', 'postalcode',
    'status', 'house_number', 'street_name', 'borough_code', 'place_name',
    'sname', 'hnum', 'boro', 'lat', 'bin', 'bbl', 'cd', 'ct', 'council',
    'grc', 'grc2', 'msg', 'msg2', 'lon', 'zip_code',
]

GEOCODE_EXPORT_COLUMNS = GEOCODE_ADDRESS_COLUMNS


def _stringify_row_values(row):
    normalized = {}
    for key, value in row.items():
        if value is None:
            normalized[key] = ''
        elif isinstance(value, float) and np.isnan(value):
            normalized[key] = ''
        else:
            normalized[key] = str(value)
    return normalized


def _has_lat(value):
    if value is None:
        return False
    text = str(value).strip()
    return text != '' and text.lower() != 'nan'


def address_row_key(row):
    """Stable per-address identity for merge/upsert (ingest columns only)."""
    parts = []
    for col in ADDRESS_ROW_KEY_COLUMNS:
        value = row.get(col)
        if value is None:
            parts.append('')
        elif isinstance(value, float) and np.isnan(value):
            parts.append('')
        else:
            parts.append(str(value))
    return tuple(parts)


def row_needs_geocode(row):
    """Mirror select_addresses_needing_geocode.sql for unit tests."""
    return not _has_lat(row.get('lat')) and str(row.get('house_number') or '').strip() != ''


def _rows_from_fetchall(rows):
    return [
        _stringify_row_values(dict(zip(GEOCODE_ADDRESS_COLUMNS, row)))
        for row in rows
    ]


def fetch_addresses_needing_geocode(db):
    rows = db.sql_fetch_all_from_file('select_addresses_needing_geocode.sql')
    return _rows_from_fetchall(rows)


def _prepare_rows_for_db(rows):
    prepared = []
    for row in rows:
        db_row = {}
        for col in GEOCODE_EXPORT_COLUMNS:
            value = row.get(col, '')
            if col in ('lat', 'lon') and not _has_lat(value):
                db_row[col] = None
            else:
                db_row[col] = value if value != '' else None
        prepared.append(db_row)
    return prepared


def _run_geosupport(records, geocode_workers, geocode_record_fn):
    geocode_one = functools.partial(
        geocode_record_fn,
        addr_cols=['street1', 'city', 'postalcode'],
    )
    use_pool = geocode_record_fn is geocode_record
    if not use_pool:
        return [geocode_one(record) for record in records]

    worker_count = min(geocode_workers, multiprocessing.cpu_count())
    with multiprocessing.Pool(processes=worker_count) as pool:
        return pool.map(geocode_one, records, 10000)


def _run_census_batch(still_missing, census_batch_chunk_size, pub_dir, geocode_using_census_batch_fn):
    if not still_missing:
        return []

    use_pool = geocode_using_census_batch_fn is geocode_using_census_batch
    chunk_size = census_batch_chunk_size
    df_missing = pd.DataFrame(still_missing)
    splits = list(np.split(df_missing, range(chunk_size, df_missing.shape[0], chunk_size)))

    if not use_pool:
        return [geocode_using_census_batch_fn(chunk, pub_dir) for chunk in splits]

    census_pool_workers = min(5, multiprocessing.cpu_count())
    data_split = zip(splits, repeat(pub_dir))
    with multiprocessing.Pool(processes=census_pool_workers) as pool:
        return pool.starmap(geocode_using_census_batch_fn, data_split)


def geocode_candidate_records(
    records,
    geocode_workers,
    census_batch_chunk_size,
    pub_dir,
    geocode_record_fn=geocode_record,
    geocode_using_census_batch_fn=geocode_using_census_batch,
):
    if not records:
        return []

    geosupport_results = _run_geosupport(records, geocode_workers, geocode_record_fn)

    still_missing = [row for row in geosupport_results if not _has_lat(row.get('lat'))]
    if not still_missing:
        return geosupport_results

    census_chunks = _run_census_batch(
        still_missing,
        census_batch_chunk_size,
        pub_dir,
        geocode_using_census_batch_fn,
    )
    if census_chunks:
        census_results = pd.concat(census_chunks, ignore_index=True).to_dict('records')
    else:
        census_results = []

    by_key = {address_row_key(row): row for row in geosupport_results}
    for row in census_results:
        by_key[address_row_key(row)] = row
    return [by_key[address_row_key(row)] for row in records]


def upsert_geocoded_addresses(db, rows):
    if not rows:
        return 0

    db.execute_sql_file('create_geocode_staging_table.sql')
    db.insert_rows(_prepare_rows_for_db(rows), 'oca_addresses_geocode_staging')
    db.execute_sql_file('upsert_geocoded_addresses.sql')
    return len(rows)
