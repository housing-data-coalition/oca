#!/usr/bin/env python

import argparse
import multiprocessing
import os

import dotenv

from lib.database import Database
from lib.etl_helpers import make_dir
from lib.etl_run_manifest import EtlRunManifest
from lib.etl_stages import geocode_addresses

dotenv.load_dotenv()


def parse_optional_int(raw_value):
    if raw_value in (None, ''):
        return None
    return int(raw_value)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Geocode oca_addresses rows in RDS where lat IS NULL',
    )
    parser.add_argument(
        '--db-schema',
        default=os.environ.get('DB_SCHEMA', ''),
        help='Database schema search_path target',
    )
    parser.add_argument(
        '--geocode-workers',
        type=int,
        default=parse_optional_int(os.environ.get('GEOCODE_WORKERS')),
        help='Worker process count for geocode pool',
    )
    parser.add_argument(
        '--census-batch-chunk-size',
        type=int,
        default=int(os.environ.get('CENSUS_BATCH_CHUNK_SIZE', '2500')),
        help='Chunk size for census batch geocoder input',
    )
    return parser.parse_args()


def run_geocode_backfill(db_args, runtime_args=None):
    """Fetch ungeocoded addresses from RDS, geocode, and upsert (+ geom)."""
    runtime_args = runtime_args or {}
    geocode_workers = runtime_args.get('geocode_workers') or multiprocessing.cpu_count()
    census_batch_chunk_size = runtime_args.get('census_batch_chunk_size') or 2500
    db_schema = runtime_args.get('db_schema') or db_args.get('schema') or 'public'

    db = Database(**db_args)
    manifest = EtlRunManifest(
        db=db,
        schema_name=db_schema,
        s3_prefix='',
        mode='geocode_backfill',
        reprocess_glob='',
        force_reprocess=False,
    )
    manifest.setup_tables()
    manifest.create_run()

    pub_dir = make_dir('data-public')
    try:
        db.ensure_connection()
        candidate_count = geocode_addresses(
            manifest,
            db,
            pub_dir,
            geocode_workers,
            census_batch_chunk_size,
        )
        manifest.mark_run_completed(0, 0, 0)
        print(f'Backfill complete; {candidate_count} candidate addresses processed')
        return candidate_count
    except Exception as exc:
        manifest.mark_run_failed(exc)
        raise


def main():
    args = parse_args()
    db_args = {
        'db_url': os.environ.get('DATABASE_URL', ''),
        'schema': args.db_schema,
    }
    runtime_args = {
        'db_schema': args.db_schema,
        'geocode_workers': args.geocode_workers,
        'census_batch_chunk_size': args.census_batch_chunk_size,
    }
    run_geocode_backfill(db_args, runtime_args)


if __name__ == '__main__':
    main()
