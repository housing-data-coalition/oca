#!/usr/bin/env python

import argparse
import os

import dotenv

from lib.database import Database
from lib.etl_run_manifest import EtlRunManifest
from lib.etl_stages import purge_tombstoned_cases

dotenv.load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            'Remove oca_index rows (and child tables via CASCADE) for cases '
            'with oca_metadata.deletedate set'
        ),
    )
    parser.add_argument(
        '--db-schema',
        default=os.environ.get('DB_SCHEMA', ''),
        help='Database schema search_path target',
    )
    return parser.parse_args()


def run_deletion_backfill(db_args, runtime_args=None):
    """Purge production case data for metadata tombstones."""
    runtime_args = runtime_args or {}
    db_schema = runtime_args.get('db_schema') or db_args.get('schema') or 'public'

    db = Database(**db_args)
    manifest = EtlRunManifest(
        db=db,
        schema_name=db_schema,
        s3_prefix='',
        mode='deletion_backfill',
        reprocess_glob='',
        force_reprocess=False,
    )
    manifest.setup_tables()
    manifest.create_run()

    try:
        db.ensure_connection()
        orphan_before, orphan_after = purge_tombstoned_cases(manifest, db)
        manifest.mark_run_completed(0, 0, 0)
        print(
            f'Deletion backfill complete; '
            f'orphans before={orphan_before}, after={orphan_after}'
        )
        return orphan_before, orphan_after
    except Exception as exc:
        manifest.mark_run_failed(exc)
        raise


def main():
    args = parse_args()
    db_args = {
        'db_url': os.environ.get('DATABASE_URL', ''),
        'schema': args.db_schema,
    }
    runtime_args = {'db_schema': args.db_schema}
    run_deletion_backfill(db_args, runtime_args)


if __name__ == '__main__':
    main()
