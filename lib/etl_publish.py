"""S3 publish helpers: selective exports and targeted post-publish encryption."""

import os

from .etl_constants import OCA_TABLES, S3_PUBLIC_FOLDER
from .etl_helpers import csv_has_rows, s3_key


def staging_tables_with_rows(pub_dir):
    """Main table names whose staging CSV had at least one data row this run."""
    tables = []
    for table in OCA_TABLES:
        csv_path = os.path.join(pub_dir, f"{table}_staging.csv")
        if os.path.isfile(csv_path) and csv_has_rows(csv_path):
            tables.append(table)
    return set(tables)


def should_publish_address_exports(staging_tables_with_data, geocode_candidate_count):
    """
    Whether address CSVs and derived views need S3 export this run.

    Skips full-table address exports when incremental geocode has no work and
    promotion did not load new address staging rows. Core table exports are not
    skipped when oca_index_staging has rows: promotion deletes child rows for the
    batch even when a child staging CSV was empty.
    """
    if geocode_candidate_count > 0:
        return True
    return 'oca_addresses' in staging_tables_with_data


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


def normalize_published_s3_encryption(s3, s3_prefix, object_keys):
    """Re-encrypt only objects written during this publish pass (SSE-S3)."""
    keys = sorted({k for k in object_keys if k})
    if not keys:
        return
    print(f'Updating server-side encryption for {len(keys)} published S3 object(s)')
    for object_key in keys:
        print('-', object_key)
        s3.update_encryption(object_key)
