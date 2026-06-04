import multiprocessing
import os
import re
import zipfile
from itertools import repeat
from lxml import etree

from .etl_constants import DATA_FILENAME, OCA_TABLES, S3_PRIVATE_FOLDER, S3_PUBLIC_FOLDER
from .etl_file_selection import (
    list_new_data_files,
    list_reprocess_data_files,
    select_data_files_to_process,
)
from .etl_run_manifest import completed_reprocess_files
from .etl_csv import preprocess_staging_csv_dir
from .etl_helpers import (
    create_date_files,
    csv_has_rows,
    s3_key,
    upload_public_file,
)
from .etl_promotion import (
    PURGE_TOMBSTONED_CASES_SQL_FILE,
    promote_staging_to_main,
)
from .etl_publish import (
    ADDRESS_VIEW_EXPORTS,
    export_table_to_s3,
    list_staging_csvs_in_dir,
    normalize_published_s3_encryption,
    staging_tables_with_rows,
)
from .etl_geocode import (
    fetch_addresses_needing_geocode,
    geocode_candidate_records,
    geocode_staging_addresses_csv,
    upsert_geocoded_addresses,
)
from .parsers import oca_tag, parse_file


class FileSelection:
    """Selected input files and download routing for one ETL run."""

    def __init__(
        self,
        selected_zip_files,
        skipped_reprocess_files,
        new_file_set,
        reprocess_file_set,
        sftp_download_files,
        s3_download_files,
    ):
        self.selected_zip_files = selected_zip_files
        self.skipped_reprocess_files = skipped_reprocess_files
        self.new_file_set = new_file_set
        self.reprocess_file_set = reprocess_file_set
        self.sftp_download_files = sftp_download_files
        self.s3_download_files = s3_download_files


def select_input_files(manifest, db, sftp, s3, s3_prefix, reprocess_glob, force_reprocess):
    manifest.upsert_step('select_files', 'running')
    new_sftp_zip_files = list_new_data_files(sftp, s3, s3_prefix=s3_prefix)
    reprocess_s3_zip_files = list_reprocess_data_files(s3, reprocess_glob, s3_prefix=s3_prefix)
    skipped_reprocess_files = []
    if reprocess_glob and not force_reprocess and reprocess_s3_zip_files:
        already_completed = completed_reprocess_files(db, reprocess_s3_zip_files)
        skipped_reprocess_files = sorted(already_completed)
        reprocess_s3_zip_files = sorted(set(reprocess_s3_zip_files) - already_completed)

    selected_zip_files = select_data_files_to_process(
        new_sftp_zip_files,
        reprocess_s3_zip_files,
        force_reprocess=force_reprocess
    )
    manifest.upsert_step('select_files', 'completed', details={'selected_file_count': len(selected_zip_files)})

    if reprocess_glob:
        print(f"Reprocess selector active: REPROCESS_GLOB={reprocess_glob}, FORCE_REPROCESS={force_reprocess}")
        print(f"Matched S3 private files: {len(reprocess_s3_zip_files)}")
        if skipped_reprocess_files and not force_reprocess:
            print(f"Skipping already-completed reprocess files from manifest: {len(skipped_reprocess_files)}")

    if not selected_zip_files:
        return FileSelection([], skipped_reprocess_files, set(), set(), [], [])

    reprocess_file_set = set(reprocess_s3_zip_files)
    new_file_set = set(new_sftp_zip_files)
    selected_set = set(selected_zip_files)
    sftp_download_files = sorted(selected_set & new_file_set)
    s3_download_files = sorted(selected_set & reprocess_file_set)

    for f in sftp_download_files:
        manifest.upsert_file(f, source='sftp', status='selected', stage='select')
    for f in s3_download_files:
        manifest.upsert_file(f, source='s3_private', status='selected', stage='select')
    for f in skipped_reprocess_files:
        manifest.upsert_file(
            f, source='s3_private', status='skipped', stage='select',
            details={'reason': 'already_completed_manifest'}
        )

    return FileSelection(
        selected_zip_files,
        skipped_reprocess_files,
        new_file_set,
        reprocess_file_set,
        sftp_download_files,
        s3_download_files,
    )


def download_selected_files(manifest, sftp, s3, priv_dir, s3_prefix, selection):
    manifest.upsert_step('download_files', 'running')
    print('Downloading selected files:')
    for f in selection.sftp_download_files:
        print('-', f)
        sftp.download_files(f, priv_dir)
        manifest.upsert_file(f, source='sftp', status='downloaded', stage='download')
    for f in selection.s3_download_files:
        print('-', f)
        s3.download_file(s3_key(f"{S3_PRIVATE_FOLDER}/{f}", s3_prefix), os.path.join(priv_dir, f))
        manifest.upsert_file(f, source='s3_private', status='downloaded', stage='download')
    manifest.upsert_step('download_files', 'completed')


def parse_xml_to_staging(manifest, staging_db, priv_dir, parse_num_threads=8):
    def sort_by_date(file):
        r = re.search(r'(\d+.+)\.zip', file).group(0).replace('.', ' ')
        return r

    local_zip_files = sorted(
        [os.path.join(priv_dir, f) for f in os.listdir(priv_dir) if f.endswith('.zip')],
        key=sort_by_date
    )

    manifest.upsert_step('parse_xml', 'running')
    staging_db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
    print('Processing files:')
    for zip_file in local_zip_files:
        file_name = os.path.basename(zip_file)
        manifest.upsert_file(file_name, source='local', status='processing', stage='parse')
        extract_date = None
        with zipfile.ZipFile(zip_file, 'r').open(DATA_FILENAME) as xml_file:
            for _, elem in etree.iterparse(xml_file, tag=oca_tag('RunDate')):
                if not extract_date:
                    extract_date = elem.text
                    break
        with zipfile.ZipFile(zip_file, 'r').open(DATA_FILENAME) as xml_file:
            parse_file(
                xml_file,
                staging_db,
                extract_date,
                num_threads=parse_num_threads,
            )
        manifest.upsert_file(
            file_name, source='local', status='parsed', stage='parse',
            details={'extract_date': extract_date}
        )
    manifest.upsert_step('parse_xml', 'completed')


def export_staging_to_csv(
    staging_db,
    pub_dir,
    *,
    csv_preprocess_chunk_size=1000,
    upload=True,
    mode=None,
    s3_args=None,
    s3_prefix=None,
):
    """Export DuckDB staging tables to CSV and optionally preprocess + upload."""
    staging_db.export_tables_to_csv(output_dir=pub_dir)
    preprocess_staging_csv_dir(pub_dir, chunk_size=csv_preprocess_chunk_size)

    if not upload:
        return

    public_files = list_staging_csvs_in_dir(pub_dir)
    with multiprocessing.Pool(processes=min((2, multiprocessing.cpu_count()))) as pool:
        files_zip = zip(public_files, repeat(pub_dir), repeat(mode), repeat(s3_args), repeat(s3_prefix))
        pool.starmap(upload_public_file, files_zip)


def export_staging_csvs(manifest, staging_db, pub_dir, csv_preprocess_chunk_size=1000):
    """Export DuckDB staging tables to local CSV (no S3 upload)."""
    manifest.upsert_step('export_staging', 'running')
    export_staging_to_csv(
        staging_db,
        pub_dir,
        csv_preprocess_chunk_size=csv_preprocess_chunk_size,
        upload=False,
    )
    manifest.upsert_step('export_staging', 'completed')


def geocode_staging_csvs(manifest, pub_dir, geocode_workers, census_batch_chunk_size):
    """Geocode all rows in ``oca_addresses_staging.csv`` before S3 upload."""
    manifest.upsert_step('geocode_staging', 'running')
    geocoded_row_count = geocode_staging_addresses_csv(
        pub_dir,
        geocode_workers,
        census_batch_chunk_size,
    )
    manifest.upsert_step(
        'geocode_staging',
        'completed',
        details={'geocoded_row_count': geocoded_row_count},
    )
    return geocoded_row_count


def upload_staging_csvs(manifest, pub_dir, mode, s3_args, s3_prefix):
    """Upload preprocessed staging CSVs to S3 ``public/``."""
    manifest.upsert_step('upload_staging', 'running')
    public_files = list_staging_csvs_in_dir(pub_dir)
    with multiprocessing.Pool(processes=min((2, multiprocessing.cpu_count()))) as pool:
        files_zip = zip(public_files, repeat(pub_dir), repeat(mode), repeat(s3_args), repeat(s3_prefix))
        pool.starmap(upload_public_file, files_zip)
    manifest.upsert_step(
        'upload_staging',
        'completed',
        details={'uploaded_file_count': len(public_files)},
    )


def _assert_schema_bootstrap_context(db, expected_schema):
    schema_name = (expected_schema or '').strip()
    if not schema_name:
        raise RuntimeError('DB schema must be set before running core table bootstrap.')

    schema_row = db.sql_fetch_one(
        "SELECT current_schema(), current_setting('search_path')"
    )
    current_schema, search_path = schema_row if schema_row else (None, '')
    if not current_schema:
        raise RuntimeError('Unable to resolve active schema before core table bootstrap.')

    if current_schema != schema_name:
        raise RuntimeError(
            f"Schema bootstrap guard failed: expected current_schema '{schema_name}', got '{current_schema}'."
        )

    if schema_name not in (search_path or ''):
        raise RuntimeError(
            f"Schema bootstrap guard failed: search_path '{search_path}' does not include '{schema_name}'."
        )


def ensure_core_tables_exist(db, expected_schema):
    _assert_schema_bootstrap_context(db, expected_schema)
    db.execute_sql_file('create_tables.sql')


def import_and_promote_staging(manifest, db, pub_dir, s3_args, s3_prefix, selection, expected_schema):
    imported_staging_tables = staging_tables_with_rows(pub_dir)
    staging_tables = [t + '_staging' for t in OCA_TABLES]
    manifest.upsert_step('promote_staging', 'running')
    db.set_statement_timeout()
    ensure_core_tables_exist(db, expected_schema)
    db.execute_sql_file('create_tables_staging.sql')
    for t in staging_tables:
        csv_filepath = os.path.join(pub_dir, f"{t}.csv")
        if csv_has_rows(csv_filepath):
            columns = ''
            if t == 'oca_appearances_staging':
                columns = 'indexnumberid, appearancedatetime, appearancepurpose, appearancereason, appearancepart, motionsequence, appearanceoutcomes'
            db.sql(f"""
                SELECT aws_s3.table_import_from_s3(
                '{t}', '{columns}', '(FORMAT CSV, HEADER)',
                aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', '{s3_key(f"{S3_PUBLIC_FOLDER}/{t}.csv", s3_prefix)}', 'us-east-1'),
                aws_commons.create_aws_credentials('{s3_args["aws_id"]}', '{s3_args["aws_key"]}', '')
            );
            """)

    db.execute_sql_file('normalize_staging_after_import.sql')
    db.execute_sql_file('update_appearance_outcomes.sql')
    print('\t...Promoting staging tables to main (single transaction)')
    promote_staging_to_main(db)
    for selected_name in selection.selected_zip_files:
        source = 'sftp' if selected_name in selection.new_file_set else 's3_private'
        manifest.upsert_file(selected_name, source=source, status='completed', stage='promote')
    manifest.upsert_step('promote_staging', 'completed')
    return imported_staging_tables


def publish_core_tables(db, s3_args, s3_prefix):
    """
    Export all core tables via aws_s3.query_export_to_s3.

    When oca_index_staging has rows, promotion deletes child rows for the batch
    even if a child staging CSV was empty, so per-table skip is unsafe.
    """
    published_keys = []
    for t in OCA_TABLES:
        s3_filename = t + '.csv'
        if t == "oca_addresses":
            s3_filename = "oca_addresses_private.csv"
        published_keys.append(
            export_table_to_s3(db, t, s3_filename, s3_args, s3_prefix)
        )
    return published_keys


def count_tombstone_orphans(db):
    """Cases with oca_metadata.deletedate still present in oca_index."""
    row = db.sql_fetch_one("""
        SELECT COUNT(*)::bigint
        FROM oca_index i
        INNER JOIN oca_metadata m ON m.indexnumberid = i.indexnumberid
        WHERE m.deletedate IS NOT NULL
    """)
    return int(row[0]) if row else 0


def purge_tombstoned_cases(manifest, db):
    """Delete oca_index rows (and children via CASCADE) for metadata tombstones."""
    manifest.upsert_step('deletion_backfill', 'running')
    orphan_count_before = count_tombstone_orphans(db)
    db.execute_sql_file(PURGE_TOMBSTONED_CASES_SQL_FILE)
    orphan_count_after = count_tombstone_orphans(db)
    manifest.upsert_step(
        'deletion_backfill',
        'completed',
        details={
            'orphan_count_before': orphan_count_before,
            'orphan_count_after': orphan_count_after,
        },
    )
    return orphan_count_before, orphan_count_after


def geocode_addresses(manifest, db, pub_dir, geocode_workers, census_batch_chunk_size):
    """Incremental geocode for addresses missing lat/lon; upsert into RDS."""
    manifest.upsert_step('geocode_refresh', 'running')
    candidates = fetch_addresses_needing_geocode(db)
    geocoded_rows = geocode_candidate_records(
        candidates,
        geocode_workers,
        census_batch_chunk_size,
        pub_dir,
    )
    print(f'Upserting {len(geocoded_rows)} geocoded addresses')
    upsert_geocoded_addresses(db, geocoded_rows)
    manifest.upsert_step(
        'geocode_refresh',
        'completed',
        details={
            'geocode_candidate_count': len(candidates),
            'geocoded_row_count': len(geocoded_rows),
        },
    )
    return len(candidates)


def publish_public_artifacts(manifest, db, s3_args, s3_prefix, mode, selection, pub_dir):
    """Rebuild address views and export all public CSVs and date artifacts to S3."""
    manifest.upsert_step('publish_public', 'running')
    print('Publishing address views and all public CSVs')
    db.execute_sql_file('create_addresses_views.sql')
    published_keys = publish_core_tables(db, s3_args, s3_prefix)
    for view_name, s3_filename in ADDRESS_VIEW_EXPORTS:
        published_keys.append(
            export_table_to_s3(db, view_name, s3_filename, s3_args, s3_prefix)
        )

    create_date_files(selection.selected_zip_files[-1], pub_dir)
    date_files = ['last-updated-shield.svg', 'last-updated-date.txt']
    with multiprocessing.Pool(processes=min((2, multiprocessing.cpu_count()))) as pool:
        files_zip = zip(date_files, repeat(pub_dir), repeat(mode), repeat(s3_args), repeat(s3_prefix))
        pool.starmap(upload_public_file, files_zip)
    for date_file in date_files:
        published_keys.append(s3_key(f"{S3_PUBLIC_FOLDER}/{date_file}", s3_prefix))

    manifest.upsert_step(
        'publish_public',
        'completed',
        details={'published_object_count': len(published_keys)},
    )
    return published_keys


def normalize_public_s3_encryption(manifest, s3, published_keys):
    """SSE-S3 normalization for published public objects (except private address CSV)."""
    manifest.upsert_step('normalize_s3_encryption', 'running')
    normalize_published_s3_encryption(s3, published_keys)
    manifest.upsert_step('normalize_s3_encryption', 'completed')


def upload_private_source_files(manifest, s3, priv_dir, s3_prefix):
    """Upload raw XML zip backups to the S3 private folder."""
    manifest.upsert_step('upload_private', 'running')
    for f in os.listdir(priv_dir):
        if f != '.DS_Store':
            s3.upload_file(
                s3_key(f"{S3_PRIVATE_FOLDER}/{f}", s3_prefix),
                os.path.join(priv_dir, f),
            )
    manifest.upsert_step('upload_private', 'completed')
