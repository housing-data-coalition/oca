import os
import io
import shutil
import zipfile
import requests
import re
import json
from datetime import datetime
# TODO - replace os.path with Pathlib and its '/' operator
from pathlib import Path 

import numpy as np
import pandas as pd
import multiprocessing
import functools
from itertools import repeat
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


def list_new_data_files(sftp, s3):
    """ 
    Get a list of filenames for all the data files available in the SFTP
    that are not already in the private S3 folder. These are the new ones 
    that still need to be processed. They are returned in the proper order 
    in which they need to be processed.

    :param sftp: SFTP object
    :param s3: S3 object
    """

    sftp_zip_files = sftp.list_files(DATA_ZIPFILE_PAT)
    s3_zip_files = s3.list_files(DATA_ZIPFILE_PAT, S3_PRIVATE_FOLDER)
    new_sftp_zip_files = list(set(sftp_zip_files) - set(s3_zip_files))

    # It's important that everything is processed in order because files 
    # can contain modify/delete cases included in past files
    init_files = [f for f in new_sftp_zip_files if 'Initial' in f]
    incr_files = [f for f in new_sftp_zip_files if 'Incr' in f]

    files = []
    files += sorted(init_files) if init_files else []
    files += sorted(incr_files) if incr_files else []

    return files


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


def upload_public_file(f, pub_dir, mode, s3_args):
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
    s3.upload_file(f"{S3_PUBLIC_FOLDER}/{s3_filename}", os.path.join(pub_dir, f))
    del s3

def oca_etl(db_args, sftp_args, s3_args, mode, remote_db_args):
    """ 
    Extract files from SFTP, parse cases, upload to S3 bucket
    """

    db = Database(**db_args)
    Path('staging.duckdb').unlink(missing_ok=True)
    staging_db = DuckDB(dbname='staging.duckdb')
    sftp = Sftp(**sftp_args)
    s3 = S3(**s3_args)
    

    # Create local versions of folder in the S3 bucket "oca-data"
    # # For debugging only -- replace with the var declarations below
    # priv_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data-private'))
    # pub_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data-public'))
    priv_dir = make_dir('data-private') # "private/"
    pub_dir = make_dir('data-public') # "public/"
    
    # Get list of new files to download from SFTP
    new_sftp_zip_files = list_new_data_files(sftp, s3)

    # If there are no new files we can stop everything here. 
    if not new_sftp_zip_files:
        print('No new files to download from SFTP. Stopping process.')
        return True

    # If there are new files, download them.
    print('Downloading new files from SFTP:')
    for f in new_sftp_zip_files:
        print('-', f)
        sftp.download_files(f, priv_dir)

    # Sort zipfiles by date 
    def sort_by_date(file):
        r = re.search(r'(\d+.+)\.zip', file).group(0).replace('.',' ')
        return r
    local_zip_files = sorted([os.path.join(priv_dir, f) for f in os.listdir(priv_dir) if f.endswith('.zip')], key = sort_by_date)

    # Rebuild the staging tables
    # Then for each zipfile, unzip the XML file and 
    # parse it into the staging tables
    print('  - Creating staging tables...')
    staging_db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
    print('Processing files:')
    for zip_file in local_zip_files:
        print('-', os.path.basename(zip_file))
        print('  - Parsing XML file...') 
        # takes about 4-5 minutes per xml
        extract_date = None
        with zipfile.ZipFile(zip_file, 'r').open(DATA_FILENAME) as xml_file:
            for _, elem in etree.iterparse(xml_file, tag=oca_tag('RunDate')):
                # Grab the first date and break 
                if not extract_date:
                    extract_date = elem.text
                    break

        with zipfile.ZipFile(zip_file, 'r').open(DATA_FILENAME) as xml_file:
            parse_file(xml_file, staging_db, extract_date)

    # export staging tables to the pub_dir, upload to s3, and then rds
    staging_db.export_tables_to_csv(output_dir=pub_dir)

    def preprocess_csvs(pub_dir):
        """Convert all CSV files from DuckDB to PostgreSQL array format; and make small corrections (todo fix this in the parser/ duckdb export)"""
        for filename in os.listdir(pub_dir):
            if filename.endswith('.csv'):
                file_path = os.path.join(pub_dir, filename)
                df = pd.read_csv(file_path)
                for col in df.columns:
                    if df[col].dtype == 'object':
                        # Convert arrays: [anything] -> {anything}
                        # But only if the content doesn't contain JSON objects
                        def replace_brackets(text):
                            if pd.isna(text) or not isinstance(text, str):
                                return text

                            if text.startswith('[') and text.endswith(']'):
                                inner_content = text[1:-1].strip()
                                # Don't replace if the inner content is wrapped in {}
                                # Todo: fix appearanceoutcomes that are blank [] ... they are still converted to {}
                                if inner_content.startswith('{') and inner_content.endswith('}'):
                                    return text  # Keep original - it's [{}] format
                                else:
                                    return '{' + text[1:-1] + '}'  # Convert [] to {}
                            
                            return text
                        
                        df[col] = df[col].apply(replace_brackets)

                if filename.startswith('oca_appearances'):
                    # remove the appearanceid column, BIGSERIAL is assigned in postgres
                    if 'appearanceid' in df.columns: del df['appearanceid']
                    # change motionsequence to a int instead of a float
                    df['motionsequence'] = df['motionsequence'].astype('Int64')

                if filename.startswith('oca_judgments'):
                    df['amendedfromjudgmentsequence'] = df['amendedfromjudgmentsequence'].astype('Int64')

                if filename.startswith('oca_warrants'):
                    df['executionstayeddays'] = df['executionstayeddays'].astype('Int64')
                    df['issuancestayeddays'] = df['issuancestayeddays'].astype('Int64')

                df.to_csv(file_path, index=False)
    
    print('Convert csvs:')
    preprocess_csvs(pub_dir)
    staging_tables = [t + '_staging' for t in OCA_TABLES]
    public_files = [i for i in os.listdir(pub_dir) if i.endswith('.csv')]
    with multiprocessing.Pool(processes=min((2, multiprocessing.cpu_count()))) as pool:
        files_zip = zip(public_files, repeat(pub_dir), repeat(mode), repeat(s3_args)) 
        pool.starmap(upload_public_file, files_zip)

    # reset staging tables then import from s3 to rds
    db.execute_sql_file('create_tables_staging.sql')
    for t in staging_tables:
        print('-', f"{t} table to db")
        # only import to the rds, if the local csv has rows
        csv_filepath = os.path.join(pub_dir, f"{t}.csv")
        if len(pd.read_csv(csv_filepath)):
            columns = ''
            # ignore the appearanceid column
            if t == 'oca_appearances_staging': 
                columns = 'indexnumberid, appearancedatetime, appearancepurpose, appearancereason, appearancepart, motionsequence, appearanceoutcomes'
            db.sql(f"""
                SELECT aws_s3.table_import_from_s3(
                '{t}', '{columns}', '(FORMAT CSV, HEADER)',
                aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', 'public/{t}.csv', 'us-east-1'),
                aws_commons.create_aws_credentials('{s3_args["aws_id"]}', '{s3_args["aws_key"]}', '')
            );
            """)

    # reset appearanceid continuing from the postgresql sequence and expand appearance_outcomes from json
    print('\n   - Updating appearance outcomes...')
    db.execute_sql_file('update_appearance_outcomes.sql')
    
    print('\n   - Inserting from staging to main ...')
    # moves records from staging tables to the main tables, skips oca_metadata
    insert_staging_to_main(db, OCA_TABLES) 

    # Merging in oca_metadata using case if logic 
    print('\n   - Update metadata in main ...')
    db.execute_sql_file('update_metadata.sql')

    
    # Export the rds tables to csv files directly into the s3 bucket
    for t in OCA_TABLES:
        print('-', f'{t} table from db to s3')
        # to maintain consistent names for public level-1 csv files, we'll rename the level-2 version
        s3_filename = t + '.csv'
        if t == "oca_addresses":
            s3_filename = "oca_addresses_private.csv"
        db.sql(f"""
                SELECT * from aws_s3.query_export_to_s3(
                    'SELECT * from {t}', 
                    aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', 'public/{s3_filename}', 'us-east-1'), 
                    options :='FORMAT CSV, HEADER');
                """)

    # Export oca_addresses_private.csv to pub_dir to geocode
    csv_filepath = os.path.join(pub_dir, f"oca_addresses_private.csv")
    db.export_csv('oca_addresses', csv_filepath)

    input_csv = Path(pub_dir) / 'oca_addresses_private.csv'
    output_csv = Path(pub_dir) /'oca_addresses_private.csv'
    addr_cols = ['street1', 'city', 'postalcode']

    #keep all cols
    keep_cols = lambda x: x

    df = pd.read_csv(
        input_csv, 
        dtype = str,
        index_col = False, 
        usecols=keep_cols,
        keep_default_na=False
    )

    #filter for only records that need to be geocoded
    df_1 = df[
            ((pd.isna(df['lat'])) | (df['lat'] == '')) & 
            ((df['house_number'] != '') | (pd.notna(df['house_number'])))
        ].copy().reset_index()
    
    # # DEBUG: geocode all records
    # df_1 = df

    print(f'Geocoding {len(df_1)} entries in {output_csv}.')

    records = df_1.to_dict('records')

    # Geocode records using NYC GeoSupport
    # TODO - check if pluto in the database matches the pluto version of the geosupport
    # TODO - adjust geocode to put lat/lng on the lot centroid? instead of the centerline/sidewalk
    with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
        it = pd.DataFrame(pool.map(functools.partial(geocode_record, addr_cols=addr_cols), records, 10000))

    del df_1 # delete unused objects to avoid docker's memory error / 137
    del records 
    
    # Geocode other records using the US Batch Census Geocoder
    #   Sub-select for all addresses that are missing latitude; also needs to have a house number
    df_2 = it[(((pd.isna(it['lat'])) | (it['lat'] == '')))].copy().reset_index()
    print(f'Geocoding {len(df_2)} entries in {output_csv} using another geocoder. {datetime.now()}')

    # For debugging only
    # ---
    # data_split = np.split(df_2, range(chunk_size, df_2.shape[0], 10000))
    # geocode_using_census_batch(data_split[2], pub_dir)

    with multiprocessing.Pool(processes=min([5, multiprocessing.cpu_count()])) as pool:
        chunk_size = 2500 # census batch limit is 10,000. Smaller batches tend to work better
        data_split = zip(np.split(df_2, range(chunk_size, df_2.shape[0], chunk_size)), repeat(pub_dir))
        it_2 = pd.concat(pool.starmap(geocode_using_census_batch, data_split))
        del df_2
        del data_split
        
    print(f'Done geocoding. {datetime.now()}')
    # Concat and drop duplicates by keeping the last changes from US Batch Census Geocoder (overwrites the GeoSupport returns
    export_cols = ['indexnumberid', 'street1', 'street2', 'city', 'state',
        'postalcode', 'status', 'house_number', 'street_name', 'borough_code',
        'place_name', 'sname', 'hnum', 'boro', 'lat', 'bin', 'bbl', 'cd',
        'ct', 'council', 'grc', 'grc2', 'msg', 'msg2', 'lon', 'zip_code']
    concat = pd.concat([df, it, it_2], ignore_index = True).drop_duplicates(subset=['indexnumberid'], ignore_index = True, keep = 'last')[export_cols]
    del df
    del it
    del it_2
    pd.DataFrame(concat).to_csv(output_csv, index=False)
    del concat

    # # reset connection to s3
    # s3 = S3(**s3_args)

    # Update "last updated date" files on S3 for the latest file processed
    create_date_files(s3, new_sftp_zip_files[-1], pub_dir)

    print('Uploading public files to S3:')
    public_files = [i for i in os.listdir(pub_dir) 
                    if i in ('last-updated-shield.png', 'last-updated-date.txt', 'oca_addresses_private.csv')]
    with multiprocessing.Pool(processes=min((2, multiprocessing.cpu_count()))) as pool:
        files_zip = zip(public_files, repeat(pub_dir), repeat(mode), repeat(s3_args)) 
        pool.starmap(upload_public_file, files_zip) 

    # # Create/upload a dump of the database as a backup
    # print('Creating database dump and uploading to s3')
    # db.dump_to(os.path.join(priv_dir, 'oca.dump'))

    # Upload raw data files and database dump to private folder in S3 bucket
    print('Uploading private files to S3:')
    for f in os.listdir(priv_dir):
        if f != '.DS_Store': 
            print('-', f)
            s3.upload_file(f"{S3_PRIVATE_FOLDER}/{f}", os.path.join(priv_dir, f))

    # reset oca_addresses (removes geom), and uses the geocoded s3 import to overwrite oca_addresses table
    print('-', f'overwrite oca_addresses with geocoded version')
    db.execute_sql_file('reset_addresses_table.sql')
    db.sql(f"""
    SET statement_timeout = '2000000';
        SELECT aws_s3.table_import_from_s3(
        'oca_addresses', '', '(FORMAT CSV, HEADER)',
        aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', 'public/oca_addresses_private.csv', 'us-east-1'),
        aws_commons.create_aws_credentials('{s3_args["aws_id"]}', '{s3_args["aws_key"]}', '')
    );
    """) # TODO: replace with similar sql query as update_metadata.sql to reduce the time this takes (10 mins)

    # # setup pluto if it does not exist
    # # # TODO: setup census tracts if it does not exist 
    # if not db.sql_fetch_one(
    #     "SELECT * FROM information_schema.tables WHERE table_name = 'pluto'"):
    #     pluto_file = download_pluto(pub_dir)
        

    #     print('uploading pluto to s3')
    #     s3.upload_file(f"{S3_PUBLIC_FOLDER}/pluto.csv", pluto_file)

    #     print('importing pluto to db')
    #     db.execute_sql_file('create_pluto_table.sql')
                
    #     db.sql(f"""
    #         SELECT aws_s3.table_import_from_s3(
    #         'pluto', '', '(FORMAT CSV, HEADER)',
    #         aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', 'public/pluto_24v2.csv', 'us-east-1'),
    #         aws_commons.create_aws_credentials('{s3_args["aws_id"]}', '{s3_args["aws_key"]}', '')
    #     );
    #     """)
   
    #     db.execute_sql_file('alter_pluto_table.sql')

   
    # create views and grant access to folks
    db.execute_sql_file('create_addresses_views.sql')

    # export views directly to s3, each takes 1-2 minutes
    print(f"Creating oca_addresses_with_bbl and exporting to S3")
    db.sql(f"""
            SELECT * from aws_s3.query_export_to_s3(
                'SELECT * from oca_addresses_with_bbl', 
                aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', 'public/oca_addresses_with_bbl.csv', 'us-east-1'), 
                options :='FORMAT CSV, HEADER'); 
        """)

    print(f"Creating oca_addresses_with_ct and exporting to S3")
    db.sql(f"""
            SELECT * from aws_s3.query_export_to_s3(
                'SELECT * from oca_addresses_with_ct', 
                aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', 'public/oca_addresses_with_ct.csv', 'us-east-1'), 
                options :='FORMAT CSV, HEADER'); 
        """)

    # add level-1 version of address table from level-2 data and maintain consistent name
    print(f"Creating oca_addresses_public and exporting to S3")
    db.sql(f"""
        SELECT * from aws_s3.query_export_to_s3(
            'SELECT * from oca_addresses_public', 
            aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', 'public/oca_addresses.csv', 'us-east-1'), 
            options :='FORMAT CSV, HEADER'); 
    """)

    # update server-side encryption for all non-staged files (sse-s3) using the s3 key, 
    # as the rds query_export_to_s3 uses its own key.. and that causes https://github.com/housing-data-coalition/oca/issues/15
    print('Updating server-side encryption for S3 files')
    public_files_to_encrypt = [
        f for f in s3.list_files('', S3_PUBLIC_FOLDER) 
        if not f.endswith('_staging.csv') and 'oca_addresses_private' not in f
    ]
    for f in public_files_to_encrypt:
        print('-', f)
        s3.update_encryption(f"{S3_PUBLIC_FOLDER}/{f}")