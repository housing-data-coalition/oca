import os
import io
import shutil
import zipfile
import requests
import re
import json
import fnmatch
import uuid
import traceback
from datetime import datetime
# TODO - replace os.path with Pathlib and its '/' operator
from pathlib import Path 

import numpy as np
import pandas as pd
import multiprocessing
import functools
from itertools import repeat
from contextlib import contextmanager
from lxml import etree
import sys

from .database import Database
from .duckdb_database import DuckDB
from .s3 import S3
from .sftp import Sftp
from .parsers import oca_tag, parse_file

from .geocode_record import geocode_record, geocode_using_census_batch

OCA_TABLES = [
    'oca_index',
    'oca_causes',
    'oca_addresses',
    'oca_parties',
    'oca_events',
    'oca_appearances',
    'oca_appearance_outcomes',
    'oca_motions',
    'oca_decisions',
    'oca_judgments',
    'oca_warrants',
    'oca_metadata'
]

DATA_ZIPFILE_PAT = r'LandlordTenant\.(Initial\.FiledIn\d{4}|Incr)\.\d{4}-\d{2}-\d{2}\.zip'

DATA_FILENAME = 'LandlordTenantExtract.xml'

S3_PRIVATE_FOLDER = 'private'

S3_PUBLIC_FOLDER = 'public'


def s3_key(path, s3_prefix=''):
    normalized_path = path.lstrip('/')
    if not s3_prefix:
        return normalized_path
    normalized_prefix = s3_prefix.strip('/')
    return f"{normalized_prefix}/{normalized_path}"


def make_dir(dir_name):
    """ 
    Create a new directory in the same folder as this file, 
    deleting everything in the folder if it already exists 

    :param dir_name: The name of the directory to be created as a string
    """
    dir_path = os.path.abspath(os.path.join(os.path.dirname(__file__), dir_name))
    shutil.rmtree(dir_path, ignore_errors=True)
    os.mkdir(dir_path)
    return dir_path


def list_new_data_files(sftp, s3, s3_prefix=''):
    """ 
    Get a list of filenames for all the data files available in the SFTP
    that are not already in the private S3 folder. These are the new ones 
    that still need to be processed. They are returned in the proper order 
    in which they need to be processed.

    :param sftp: SFTP object
    :param s3: S3 object
    """

    sftp_zip_files = sftp.list_files(DATA_ZIPFILE_PAT)
    s3_zip_files = s3.list_files(DATA_ZIPFILE_PAT, s3_key(S3_PRIVATE_FOLDER, s3_prefix))
    new_sftp_zip_files = list(set(sftp_zip_files) - set(s3_zip_files))

    # It's important that everything is processed in order because files 
    # can contain modify/delete cases included in past files
    init_files = [f for f in new_sftp_zip_files if 'Initial' in f]
    incr_files = [f for f in new_sftp_zip_files if 'Incr' in f]

    files = []
    files += sorted(init_files) if init_files else []
    files += sorted(incr_files) if incr_files else []

    return files


def list_reprocess_data_files(s3, reprocess_glob, s3_prefix=''):
    if not reprocess_glob:
        return []
    s3_zip_files = s3.list_files(DATA_ZIPFILE_PAT, s3_key(S3_PRIVATE_FOLDER, s3_prefix))
    return sorted([f for f in s3_zip_files if fnmatch.fnmatch(f, reprocess_glob)])


def select_data_files_to_process(new_files, reprocess_files, force_reprocess=False):
    def ordered(files):
        init_files = sorted([f for f in files if 'Initial' in f])
        incr_files = sorted([f for f in files if 'Incr' in f])
        return init_files + incr_files

    if not reprocess_files:
        return ordered(new_files)

    if not force_reprocess:
        # Keep backward-compatible default behavior unless force mode is explicitly set.
        return ordered(new_files)

    merged = set(new_files) | set(reprocess_files)
    return ordered(merged)


def completed_reprocess_files(db, reprocess_files):
    if not reprocess_files:
        return set()
    quoted_files = ",".join(["'" + f.replace("'", "''") + "'" for f in reprocess_files])
    rows = db.sql_fetch_all(f"""
        SELECT DISTINCT ef.file_name
        FROM etl_files ef
        JOIN etl_runs er ON er.run_id = ef.run_id
        WHERE ef.status = 'completed'
          AND er.status = 'completed'
          AND ef.file_name IN ({quoted_files})
    """)
    return {row[0] for row in rows}


class EtlRunManifest:
    @staticmethod
    def _escape(value):
        return str(value).replace("'", "''")

    def _literal(self, value):
        return f"'{self._escape(value)}'"

    def _json_literal(self, value):
        return f"'{self._escape(json.dumps(value))}'::jsonb"

    def __init__(self, db, schema_name, s3_prefix, mode, reprocess_glob, force_reprocess):
        self.db = db
        self.schema_name = schema_name or 'public'
        self.s3_prefix = s3_prefix or ''
        self.mode = mode
        self.reprocess_glob = reprocess_glob or ''
        self.force_reprocess = force_reprocess
        self.run_id = str(uuid.uuid4())
        self.lock_key = None
        self.lock_acquired = False

    def setup_tables(self):
        self.db.execute_sql_file('create_etl_manifest_tables.sql')

    def acquire_lock(self):
        row = self.db.sql_fetch_one(
            f"SELECT hashtext('oca_etl:' || {self._literal(self.schema_name)})::bigint"
        )
        self.lock_key = row[0]
        locked = self.db.sql_fetch_one(f"SELECT pg_try_advisory_lock({self.lock_key})")
        self.lock_acquired = bool(locked and locked[0])
        if not self.lock_acquired:
            raise RuntimeError(f"Another ETL run is already active for schema '{self.schema_name}'.")

    def release_lock(self):
        if self.lock_acquired and self.lock_key is not None:
            self.db.sql_fetch_one(f"SELECT pg_advisory_unlock({self.lock_key})")
            self.lock_acquired = False

    def create_run(self):
        payload = {
            "mode": self.mode,
            "schema_name": self.schema_name,
            "s3_prefix": self.s3_prefix,
            "reprocess_glob": self.reprocess_glob,
            "force_reprocess": self.force_reprocess,
        }
        self.db.sql(f"""
            INSERT INTO etl_runs (
                run_id, schema_name, s3_prefix, mode, reprocess_glob, force_reprocess, status, metadata, started_at
            ) VALUES (
                {self._literal(self.run_id)}, {self._literal(self.schema_name)}, {self._literal(self.s3_prefix)},
                {self._literal(self.mode)}, {self._literal(self.reprocess_glob)},
                {str(self.force_reprocess).upper()}, 'running', {self._json_literal(payload)}, NOW()
            )
        """)

    def mark_run_completed(self, selected_count, processed_count, skipped_count):
        self.db.sql(f"""
            UPDATE etl_runs
            SET status = 'completed',
                completed_at = NOW(),
                selected_file_count = {selected_count},
                processed_file_count = {processed_count},
                skipped_file_count = {skipped_count}
            WHERE run_id = '{self.run_id}'
        """)

    def mark_run_failed(self, exc):
        message = str(exc)
        details = {"traceback": traceback.format_exc()}
        self.db.sql(f"""
            UPDATE etl_runs
            SET status = 'failed',
                completed_at = NOW(),
                error_message = {self._literal(message)},
                error_details = {self._json_literal(details)}
            WHERE run_id = {self._literal(self.run_id)}
        """)

    def upsert_file(self, file_name, source, status, stage=None, details=None, error=None):
        stage_value = "NULL" if stage is None else self._literal(stage)
        details_value = self._json_literal(details or {})
        error_message = "NULL" if error is None else self._literal(str(error))
        error_details = "NULL" if error is None else self._json_literal({'traceback': traceback.format_exc()})
        completed_at = "NOW()" if status in ("completed", "failed", "skipped") else "NULL"
        started_at = "NOW()" if status in ("processing", "downloaded", "parsed", "promoted") else "NULL"
        self.db.sql(f"""
            INSERT INTO etl_files (
                run_id, file_name, source, status, stage, details, started_at, completed_at, error_message, error_details, updated_at
            ) VALUES (
                {self._literal(self.run_id)}, {self._literal(file_name)}, {self._literal(source)}, {self._literal(status)}, {stage_value},
                {details_value}, {started_at}, {completed_at}, {error_message}, {error_details}, NOW()
            )
            ON CONFLICT (run_id, file_name) DO UPDATE
            SET source = EXCLUDED.source,
                status = EXCLUDED.status,
                stage = EXCLUDED.stage,
                details = EXCLUDED.details,
                started_at = COALESCE(etl_files.started_at, EXCLUDED.started_at),
                completed_at = EXCLUDED.completed_at,
                error_message = EXCLUDED.error_message,
                error_details = EXCLUDED.error_details,
                updated_at = NOW()
        """)

    def upsert_step(self, step_name, status, details=None, error=None):
        details_value = self._json_literal(details or {})
        started_at = "NOW()" if status == "running" else "NULL"
        completed_at = "NOW()" if status in ("completed", "failed") else "NULL"
        error_message = "NULL" if error is None else self._literal(str(error))
        error_details = "NULL" if error is None else self._json_literal({'traceback': traceback.format_exc()})
        self.db.sql(f"""
            INSERT INTO etl_steps (
                run_id, step_name, status, started_at, completed_at, error_message, error_details, details, updated_at
            ) VALUES (
                {self._literal(self.run_id)}, {self._literal(step_name)}, {self._literal(status)}, {started_at}, {completed_at},
                {error_message}, {error_details}, {details_value}, NOW()
            )
            ON CONFLICT (run_id, step_name) DO UPDATE
            SET status = EXCLUDED.status,
                started_at = COALESCE(etl_steps.started_at, EXCLUDED.started_at),
                completed_at = EXCLUDED.completed_at,
                error_message = EXCLUDED.error_message,
                error_details = EXCLUDED.error_details,
                details = EXCLUDED.details,
                updated_at = NOW()
        """)


@contextmanager
def manifest_step(manifest, step_name, details=None):
    manifest.upsert_step(step_name, 'running', details=details)
    try:
        yield
        manifest.upsert_step(step_name, 'completed', details=details)
    except Exception as exc:
        manifest.upsert_step(step_name, 'failed', details=details, error=exc)
        raise


def csv_has_rows(csv_filepath, chunk_size=1000):
    for _ in pd.read_csv(csv_filepath, chunksize=chunk_size):
        return True
    return False


def prep_db(s3, db, local_dir):
    """ 
    Create a new directory in the same folder as this file, 
    deleting everything in the folder if it already exists 

    :param s3: S3 object
    :param db: Database object
    :param local_dir: Path for local directory to save database dump file
    """
    if s3.list_files('oca.dump', S3_PRIVATE_FOLDER):
        print('Rebuilding tables from SQL dump')
        s3.download_file(f"{S3_PRIVATE_FOLDER}/oca.dump", os.path.join(local_dir, 'oca.dump'))
        db.execute_sql_file('create_tables.sql')
        db.restore_from(os.path.join(local_dir, 'oca.dump'))
    else:
        print('Creating tables from scratch')
        db.execute_sql_file('create_tables.sql')


def insert_staging_to_main(db, tables):
    """ 
    Delete all cases from main tables if they exist in the staging table, 
    then insert all records from the staging tables to the main tables

    issue: SET session_replication_role = replica 
        https://stackoverflow.com/questions/3942258/how-do-i-temporarily-disable-triggers-in-postgresql/18709987#18709987 
        to a work around to avoid DELETE FROM command stalling. 
        A VACUUM FULL on all the tables were tried, it does not seem to help
        Might be an issue with the staging table schema?

    :param db: Database object
    """

    db.sql("SET session_replication_role = replica;")
    for table in tables:
        if table in ('oca_metadata'): # skip these tables
            continue
        print(f"\t...Deleting older entries from {table}")
        db.sql(f"DELETE FROM {table} WHERE indexnumberid IN (SELECT indexnumberid FROM oca_index_staging)")
    db.sql("SET session_replication_role = default;")

    for table in tables:
        if table in ('oca_metadata'): # skip these tables
            continue
        print(f"\t...Inserting to {table}")
        db.sql(f"INSERT INTO {table} SELECT * FROM {table}_staging")
        db.sql(f"DROP TABLE {table}_staging")


def create_date_files(s3, data_file, local_dir):
    """
    Create a text file and a custom shield image with date the data was 
    last updated and add them to the public S3 folder.

    :param s3: S3 object
    :param data_file: file path for data being processed
    """
    date = re.search(r'(\d{4}-\d{2}-\d{2})', data_file).group(1)

    txt_file = os.path.join(local_dir, 'last-updated-date.txt')
    open(txt_file, 'w').write(date)

    url = f"https://raster.shields.io/badge/Last%20Updated-{date.replace('-', '--')}-yellow"
    r = requests.get(url)
    img_file = os.path.join(local_dir, 'last-updated-shield.png')
    open(img_file, 'wb').write(r.content)


def download_pluto(output_dir):
    """
    Download and unzip PLUTO into the directory.

    :param output_dir: string or Path
    """
    print('downloading pluto')

    # Check https://www.nyc.gov/content/planning/pages/resources/datasets/mappluto-pluto-change for updates
    PLUTO_CSV_URL = 'https://s-media.nyc.gov/agencies/dcp/assets/files/zip/data-tools/bytes/pluto/nyc_pluto_25v1_1_csv.zip'

    #download and unzip
    response = requests.get(PLUTO_CSV_URL)
    content = response.content
    z = zipfile.ZipFile(io.BytesIO(content))

    pluto_csv = [name for name in z.namelist() if '.csv' in name][0]
    z.extract(pluto_csv, output_dir)

    # rename 
    pluto_file = os.path.join(output_dir, "pluto.csv")
    os.rename(os.path.join(output_dir, pluto_csv), pluto_file)

    return pluto_file


def upload_public_file(f, pub_dir, mode, s3_args, s3_prefix=''):
    """
    Uploads a local file from the pub_dir folder to the S3_PUBLIC_FOLDER.

    :param f: filename
    :paramp ub_dir: local path folder
    :param mode: string
    :param s3_args: dict/ kwargs with aws_id, aws_key aws_bucket_name
    """
    s3 = S3(**s3_args)
    print('-', f)
    s3_filename = f
    # to maintain consistent names for public level-1 csv files, we'll rename the level-2 version
    if mode == "2" and f == "oca_addresses.csv":
        s3_filename = "oca_addresses_private.csv"
    s3.upload_file(s3_key(f"{S3_PUBLIC_FOLDER}/{s3_filename}", s3_prefix), os.path.join(pub_dir, f))
    del s3

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
    selected_zip_files = []
    skipped_reprocess_files = []
    new_file_set = set()

    try:
        manifest.upsert_step('select_files', 'running')
        new_sftp_zip_files = list_new_data_files(sftp, s3, s3_prefix=s3_prefix)
        reprocess_s3_zip_files = list_reprocess_data_files(s3, reprocess_glob, s3_prefix=s3_prefix)
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
            print('No files selected for processing. Stopping process.')
            manifest.mark_run_completed(0, 0, len(skipped_reprocess_files))
            return True

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
            manifest.upsert_file(f, source='s3_private', status='skipped', stage='select', details={'reason': 'already_completed_manifest'})

        manifest.upsert_step('download_files', 'running')
        print('Downloading selected files:')
        for f in sftp_download_files:
            print('-', f)
            sftp.download_files(f, priv_dir)
            manifest.upsert_file(f, source='sftp', status='downloaded', stage='download')
        for f in s3_download_files:
            print('-', f)
            s3.download_file(s3_key(f"{S3_PRIVATE_FOLDER}/{f}", s3_prefix), os.path.join(priv_dir, f))
            manifest.upsert_file(f, source='s3_private', status='downloaded', stage='download')
        manifest.upsert_step('download_files', 'completed')

        def sort_by_date(file):
            r = re.search(r'(\d+.+)\.zip', file).group(0).replace('.', ' ')
            return r
        local_zip_files = sorted([os.path.join(priv_dir, f) for f in os.listdir(priv_dir) if f.endswith('.zip')], key=sort_by_date)

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
            manifest.upsert_file(file_name, source='local', status='parsed', stage='parse', details={'extract_date': extract_date})
        manifest.upsert_step('parse_xml', 'completed')

        staging_db.export_tables_to_csv(output_dir=pub_dir)

        def preprocess_csvs(target_dir):
            for filename in os.listdir(target_dir):
                if filename.endswith('.csv'):
                    file_path = os.path.join(target_dir, filename)
                    df = pd.read_csv(file_path)
                    for col in df.columns:
                        if df[col].dtype == 'object':
                            def replace_brackets(text):
                                if pd.isna(text) or not isinstance(text, str):
                                    return text
                                if text.startswith('[') and text.endswith(']'):
                                    inner = text[1:-1].strip()
                                    if inner.startswith('{') and inner.endswith('}'):
                                        return text
                                    return '{' + text[1:-1] + '}'
                                return text
                            df[col] = df[col].apply(replace_brackets)
                    if filename.startswith('oca_appearances'):
                        if 'appearanceid' in df.columns:
                            del df['appearanceid']
                        df['motionsequence'] = df['motionsequence'].astype('Int64')
                    if filename.startswith('oca_judgments'):
                        df['amendedfromjudgmentsequence'] = df['amendedfromjudgmentsequence'].astype('Int64')
                    if filename.startswith('oca_warrants'):
                        df['executionstayeddays'] = df['executionstayeddays'].astype('Int64')
                        df['issuancestayeddays'] = df['issuancestayeddays'].astype('Int64')
                    df.to_csv(file_path, index=False)

        preprocess_csvs(pub_dir)
        staging_tables = [t + '_staging' for t in OCA_TABLES]
        public_files = [i for i in os.listdir(pub_dir) if i.endswith('.csv')]
        with multiprocessing.Pool(processes=min((2, multiprocessing.cpu_count()))) as pool:
            files_zip = zip(public_files, repeat(pub_dir), repeat(mode), repeat(s3_args), repeat(s3_prefix))
            pool.starmap(upload_public_file, files_zip)

        manifest.upsert_step('promote_staging', 'running')
        db.execute_sql_file('create_tables_staging.sql')
        for t in staging_tables:
            csv_filepath = os.path.join(pub_dir, f"{t}.csv")
            if csv_has_rows(csv_filepath, chunk_size=csv_row_check_chunk_size):
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

        db.execute_sql_file('update_appearance_outcomes.sql')
        insert_staging_to_main(db, OCA_TABLES)
        db.execute_sql_file('update_metadata.sql')
        for selected_name in selected_zip_files:
            source = 'sftp' if selected_name in new_file_set else 's3_private'
            manifest.upsert_file(selected_name, source=source, status='completed', stage='promote')
        manifest.upsert_step('promote_staging', 'completed')

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
        create_date_files(s3, selected_zip_files[-1], pub_dir)
        public_files = [i for i in os.listdir(pub_dir) if i in ('last-updated-shield.png', 'last-updated-date.txt', 'oca_addresses_private.csv')]
        with multiprocessing.Pool(processes=min((2, multiprocessing.cpu_count()))) as pool:
            files_zip = zip(public_files, repeat(pub_dir), repeat(mode), repeat(s3_args), repeat(s3_prefix))
            pool.starmap(upload_public_file, files_zip)
        for f in os.listdir(priv_dir):
            if f != '.DS_Store':
                s3.upload_file(s3_key(f"{S3_PRIVATE_FOLDER}/{f}", s3_prefix), os.path.join(priv_dir, f))
        db.execute_sql_file('reset_addresses_table.sql')
        db.sql(f"""
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
        manifest.upsert_step('geocode_refresh', 'completed')

        manifest.mark_run_completed(len(selected_zip_files), len(selected_zip_files), len(skipped_reprocess_files))
        return True
    except Exception as exc:
        for selected_name in selected_zip_files:
            source = 'sftp' if selected_name in new_file_set else 's3_private'
            manifest.upsert_file(selected_name, source=source, status='failed', stage='run', error=exc)
        manifest.mark_run_failed(exc)
        raise
    finally:
        manifest.release_lock()
