import multiprocessing
from pathlib import Path

from .database import Database
from .duckdb_database import DuckDB
from .etl_constants import (
    DATA_FILENAME,
    DATA_ZIPFILE_PAT,
    OCA_TABLES,
    S3_PRIVATE_FOLDER,
    S3_PUBLIC_FOLDER,
)
from .etl_file_selection import (
    list_new_data_files,
    list_reprocess_data_files,
    select_data_files_to_process,
)
from .etl_helpers import (
    create_date_files,
    csv_has_rows,
    download_pluto,
    make_dir,
    prep_db,
    s3_key,
    upload_public_file,
)
from .etl_promotion import (
    promote_staging_to_main,
    promotion_counts_checksum,
    promotion_table_counts,
)
from .etl_run_manifest import EtlRunManifest, completed_reprocess_files, manifest_step
from .etl_stages import (
    FileSelection,
    download_selected_files,
    geocode_and_publish_addresses,
    import_and_promote_staging,
    parse_xml_to_staging,
    preprocess_and_upload_staging_csvs,
    publish_core_tables,
    select_input_files,
)
from .s3 import S3
from .sftp import Sftp

__all__ = [
    'OCA_TABLES',
    'DATA_ZIPFILE_PAT',
    'DATA_FILENAME',
    'S3_PRIVATE_FOLDER',
    'S3_PUBLIC_FOLDER',
    's3_key',
    'make_dir',
    'list_new_data_files',
    'list_reprocess_data_files',
    'select_data_files_to_process',
    'completed_reprocess_files',
    'EtlRunManifest',
    'manifest_step',
    'csv_has_rows',
    'prep_db',
    'promote_staging_to_main',
    'promotion_table_counts',
    'promotion_counts_checksum',
    'create_date_files',
    'download_pluto',
    'upload_public_file',
    'FileSelection',
    'oca_etl',
]


def oca_etl(db_args, sftp_args, s3_args, mode, remote_db_args, runtime_args=None):
    """ 
    Extract files from SFTP, parse cases, upload to S3 bucket
    """

    runtime_args = runtime_args or {}
    s3_prefix = (runtime_args.get('s3_prefix') or '').strip('/')
    reprocess_glob = runtime_args.get('reprocess_glob') or ''
    force_reprocess = bool(runtime_args.get('force_reprocess'))
    geocode_workers = runtime_args.get('geocode_workers') or multiprocessing.cpu_count()
    census_batch_chunk_size = runtime_args.get('census_batch_chunk_size') or 2500
    csv_row_check_chunk_size = runtime_args.get('csv_row_check_chunk_size') or 1000

    db = Database(**db_args)
    manifest = EtlRunManifest(
        db=db,
        schema_name=(runtime_args.get('db_schema') or db_args.get('schema') or 'public'),
        s3_prefix=s3_prefix,
        mode=mode,
        reprocess_glob=reprocess_glob,
        force_reprocess=force_reprocess
    )
    manifest.setup_tables()
    manifest.acquire_lock()
    manifest.create_run()

    Path('staging.duckdb').unlink(missing_ok=True)
    staging_db = DuckDB(dbname='staging.duckdb')
    sftp = Sftp(**sftp_args)
    s3 = S3(**s3_args)
    priv_dir = make_dir('data-private')
    pub_dir = make_dir('data-public')
    selection = None

    try:
        selection = select_input_files(
            manifest, db, sftp, s3, s3_prefix, reprocess_glob, force_reprocess
        )
        if not selection.selected_zip_files:
            print('No files selected for processing. Stopping process.')
            manifest.mark_run_completed(0, 0, len(selection.skipped_reprocess_files))
            return True

        download_selected_files(manifest, sftp, s3, priv_dir, s3_prefix, selection)
        parse_xml_to_staging(manifest, staging_db, priv_dir)
        preprocess_and_upload_staging_csvs(
            staging_db, pub_dir, mode, s3_args, s3_prefix,
            csv_preprocess_chunk_size=csv_row_check_chunk_size,
        )
        staging_tables_with_data = import_and_promote_staging(
            manifest,
            db,
            pub_dir,
            s3_args,
            s3_prefix,
            selection,
            runtime_args.get('db_schema') or db_args.get('schema') or 'public',
        )
        published_core_keys = publish_core_tables(manifest, db, s3_args, s3_prefix)
        geocode_and_publish_addresses(
            manifest, db, s3, priv_dir, pub_dir, s3_args, s3_prefix, mode, selection,
            geocode_workers, census_batch_chunk_size,
            staging_tables_with_data, published_core_keys,
        )

        manifest.mark_run_completed(
            len(selection.selected_zip_files),
            len(selection.selected_zip_files),
            len(selection.skipped_reprocess_files)
        )
        return True
    except Exception as exc:
        if selection and selection.selected_zip_files:
            for selected_name in selection.selected_zip_files:
                source = 'sftp' if selected_name in selection.new_file_set else 's3_private'
                manifest.upsert_file(selected_name, source=source, status='failed', stage='run', error=exc)
        manifest.mark_run_failed(exc)
        raise
    finally:
        manifest.release_lock()
