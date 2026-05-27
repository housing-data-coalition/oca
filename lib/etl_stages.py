import functools
import multiprocessing
import os
import re
import zipfile
from itertools import repeat
from pathlib import Path

import numpy as np
import pandas as pd
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
    insert_staging_to_main,
    s3_key,
    upload_public_file,
)
from .geocode_record import geocode_record, geocode_using_census_batch
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


def parse_xml_to_staging(manifest, staging_db, priv_dir):
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
            parse_file(xml_file, staging_db, extract_date)
        manifest.upsert_file(
            file_name, source='local', status='parsed', stage='parse',
            details={'extract_date': extract_date}
        )
    manifest.upsert_step('parse_xml', 'completed')


def preprocess_and_upload_staging_csvs(
    staging_db, pub_dir, mode, s3_args, s3_prefix, csv_preprocess_chunk_size=1000
):
    staging_db.export_tables_to_csv(output_dir=pub_dir)
    preprocess_staging_csv_dir(pub_dir, chunk_size=csv_preprocess_chunk_size)
    public_files = [i for i in os.listdir(pub_dir) if i.endswith('.csv')]
    with multiprocessing.Pool(processes=min((2, multiprocessing.cpu_count()))) as pool:
        files_zip = zip(public_files, repeat(pub_dir), repeat(mode), repeat(s3_args), repeat(s3_prefix))
        pool.starmap(upload_public_file, files_zip)


def import_and_promote_staging(manifest, db, pub_dir, s3_args, s3_prefix, selection):
    staging_tables = [t + '_staging' for t in OCA_TABLES]
    manifest.upsert_step('promote_staging', 'running')
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
    insert_staging_to_main(db, OCA_TABLES)
    db.execute_sql_file('update_metadata.sql')
    for selected_name in selection.selected_zip_files:
        source = 'sftp' if selected_name in selection.new_file_set else 's3_private'
        manifest.upsert_file(selected_name, source=source, status='completed', stage='promote')
    manifest.upsert_step('promote_staging', 'completed')


def publish_core_tables(manifest, db, s3_args, s3_prefix):
    manifest.upsert_step('publish_tables', 'running')
    for t in OCA_TABLES:
        s3_filename = t + '.csv'
        if t == "oca_addresses":
            s3_filename = "oca_addresses_private.csv"
        db.sql(f"""
                SELECT * from aws_s3.query_export_to_s3(
                    'SELECT * from {t}',
                    aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', '{s3_key(f"{S3_PUBLIC_FOLDER}/{s3_filename}", s3_prefix)}', 'us-east-1'),
                    options :='FORMAT CSV, HEADER');
                """)
    manifest.upsert_step('publish_tables', 'completed')


def geocode_and_publish_addresses(
    manifest, db, s3, priv_dir, pub_dir, s3_args, s3_prefix, mode, selection,
    geocode_workers, census_batch_chunk_size
):
    manifest.upsert_step('geocode_refresh', 'running')
    csv_filepath = os.path.join(pub_dir, "oca_addresses_private.csv")
    db.export_csv('oca_addresses', csv_filepath)
    input_csv = Path(pub_dir) / 'oca_addresses_private.csv'
    output_csv = Path(pub_dir) / 'oca_addresses_private.csv'
    df = pd.read_csv(input_csv, dtype=str, index_col=False, usecols=lambda x: x, keep_default_na=False)
    df_1 = df[((pd.isna(df['lat'])) | (df['lat'] == '')) & ((df['house_number'] != '') | (pd.notna(df['house_number'])))].copy().reset_index()
    records = df_1.to_dict('records')
    with multiprocessing.Pool(processes=min((geocode_workers, multiprocessing.cpu_count()))) as pool:
        it = pd.DataFrame(pool.map(functools.partial(geocode_record, addr_cols=['street1', 'city', 'postalcode']), records, 10000))
    df_2 = it[(((pd.isna(it['lat'])) | (it['lat'] == '')))].copy().reset_index()
    with multiprocessing.Pool(processes=min([5, multiprocessing.cpu_count()])) as pool:
        chunk_size = census_batch_chunk_size
        data_split = zip(np.split(df_2, range(chunk_size, df_2.shape[0], chunk_size)), repeat(pub_dir))
        it_2 = pd.concat(pool.starmap(geocode_using_census_batch, data_split))
    export_cols = ['indexnumberid', 'street1', 'street2', 'city', 'state', 'postalcode', 'status', 'house_number', 'street_name', 'borough_code', 'place_name', 'sname', 'hnum', 'boro', 'lat', 'bin', 'bbl', 'cd', 'ct', 'council', 'grc', 'grc2', 'msg', 'msg2', 'lon', 'zip_code']
    concat = pd.concat([df, it, it_2], ignore_index=True).drop_duplicates(subset=['indexnumberid'], ignore_index=True, keep='last')[export_cols]
    pd.DataFrame(concat).to_csv(output_csv, index=False)
    create_date_files(s3, selection.selected_zip_files[-1], pub_dir)
    public_files = [i for i in os.listdir(pub_dir) if i in ('last-updated-shield.png', 'last-updated-date.txt', 'oca_addresses_private.csv')]
    with multiprocessing.Pool(processes=min((2, multiprocessing.cpu_count()))) as pool:
        files_zip = zip(public_files, repeat(pub_dir), repeat(mode), repeat(s3_args), repeat(s3_prefix))
        pool.starmap(upload_public_file, files_zip)
    for f in os.listdir(priv_dir):
        if f != '.DS_Store':
            s3.upload_file(s3_key(f"{S3_PRIVATE_FOLDER}/{f}", s3_prefix), os.path.join(priv_dir, f))
    db.execute_sql_file('reset_addresses_table.sql')
    db.sql(f"""
        SET statement_timeout = '2000000';
        SELECT aws_s3.table_import_from_s3(
        'oca_addresses', '', '(FORMAT CSV, HEADER)',
        aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', '{s3_key(f"{S3_PUBLIC_FOLDER}/oca_addresses_private.csv", s3_prefix)}', 'us-east-1'),
        aws_commons.create_aws_credentials('{s3_args["aws_id"]}', '{s3_args["aws_key"]}', '')
    );
    """)
    db.execute_sql_file('create_addresses_views.sql')
    db.sql(f"""
            SELECT * from aws_s3.query_export_to_s3(
                'SELECT * from oca_addresses_with_bbl',
                aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', '{s3_key(f"{S3_PUBLIC_FOLDER}/oca_addresses_with_bbl.csv", s3_prefix)}', 'us-east-1'),
                options :='FORMAT CSV, HEADER');
        """)
    db.sql(f"""
            SELECT * from aws_s3.query_export_to_s3(
                'SELECT * from oca_addresses_with_ct',
                aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', '{s3_key(f"{S3_PUBLIC_FOLDER}/oca_addresses_with_ct.csv", s3_prefix)}', 'us-east-1'),
                options :='FORMAT CSV, HEADER');
        """)
    db.sql(f"""
        SELECT * from aws_s3.query_export_to_s3(
            'SELECT * from oca_addresses_public',
            aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', '{s3_key(f"{S3_PUBLIC_FOLDER}/oca_addresses.csv", s3_prefix)}', 'us-east-1'),
            options :='FORMAT CSV, HEADER');
    """)
    print('Updating server-side encryption for S3 files')
    public_folder = s3_key(S3_PUBLIC_FOLDER, s3_prefix)
    public_files_to_encrypt = [
        f for f in s3.list_files('', public_folder)
        if not f.endswith('_staging.csv') and 'oca_addresses_private' not in f
    ]
    for f in public_files_to_encrypt:
        print('-', f)
        s3.update_encryption(s3_key(f"{S3_PUBLIC_FOLDER}/{f}", s3_prefix))
    manifest.upsert_step('geocode_refresh', 'completed')
