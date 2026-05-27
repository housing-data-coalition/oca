import io
import os
import re
import shutil
import zipfile

import pandas as pd
import requests

from .etl_constants import S3_PRIVATE_FOLDER, S3_PUBLIC_FOLDER
from .s3 import S3


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
