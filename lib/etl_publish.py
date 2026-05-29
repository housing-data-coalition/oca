"""S3 publish helpers: exports and targeted post-publish encryption."""

import os

from .etl_constants import OCA_TABLES, S3_PUBLIC_FOLDER
from .etl_helpers import csv_has_rows, s3_key

PRIVATE_ADDRESS_CSV = 'oca_addresses_private.csv'


def staging_tables_with_rows(pub_dir):
    """Main table names whose staging CSV had at least one data row this run."""
    tables = []
    for table in OCA_TABLES:
        csv_path = os.path.join(pub_dir, f"{table}_staging.csv")
        if os.path.isfile(csv_path) and csv_has_rows(csv_path):
            tables.append(table)
    return set(tables)


def export_table_to_s3(db, table, s3_filename, s3_args, s3_prefix):
    """Export one main table via aws_s3.query_export_to_s3; return the object key."""
    object_key = s3_key(f"{S3_PUBLIC_FOLDER}/{s3_filename}", s3_prefix)
    db.sql(f"""
        SELECT * from aws_s3.query_export_to_s3(
            'SELECT * from {table}',
            aws_commons.create_s3_uri(
                '{s3_args["aws_bucket_name"]}',
                '{object_key}',
                'us-east-1'
            ),
            options :='FORMAT CSV, HEADER');
    """)
    return object_key


ADDRESS_VIEW_EXPORTS = (
    ('oca_addresses_with_bbl', 'oca_addresses_with_bbl.csv'),
    ('oca_addresses_with_ct', 'oca_addresses_with_ct.csv'),
    ('oca_addresses_public', 'oca_addresses.csv'),
)


def published_keys_for_encryption(object_keys):
    """Object keys to re-encrypt with SSE-S3; excludes the private address CSV."""
    keys = []
    for key in object_keys:
        if not key:
            continue
        normalized = key.rstrip('/')
        if normalized.endswith(PRIVATE_ADDRESS_CSV):
            continue
        keys.append(key)
    return sorted(set(keys))


def normalize_published_s3_encryption(s3, object_keys):
    """Re-encrypt only objects written during this publish pass (SSE-S3)."""
    keys = published_keys_for_encryption(object_keys)
    if not keys:
        return
    print(f'Updating server-side encryption for {len(keys)} published S3 object(s)')
    for object_key in keys:
        print('-', object_key)
        s3.update_encryption(object_key)
