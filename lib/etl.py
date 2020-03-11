import os
import shutil
import zipfile
import requests
import re

from .database import Database
from .s3 import S3
from .sftp import Sftp
from .parsers import parse_file


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
    'oca_warrants'
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
        db.restore_from(os.path.join(local_dir, 'oca.dump'))
    else:
        print('Creating tables from scratch')
        db.execute_sql_file('create_tables.sql')


def insert_staging_to_main(db):
    """ 
    Delete all cases from main tables if they exist in the staging table, 
    then insert all records from the staging tables to the main tables

    :param db: Database object
    """

    db.sql(f"DELETE FROM oca_index WHERE indexnumberid IN (SELECT indexnumberid FROM oca_index_staging)")
    for table in OCA_TABLES:
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


def oca_etl(db_args, sftp_args, s3_args):
    """ 
    Extract files from SFTP, parse cases, upload to S3 bucket


    """

    db = Database(**db_args)

    sftp = Sftp(**sftp_args)

    s3 = S3(**s3_args)

    # Create local versions of folder in the S3 bucket "oca-data"
    priv_dir = make_dir('data-private') # "private/"
    pub_dir = make_dir('data-public') # "public/"

    # For debugging only
    # priv_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data-private'))
    # pub_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data-public'))
    
    # Get list of new files to download from SFTP
    new_sftp_zip_files = list_new_data_files(sftp, s3)

    # If there are no new files we can stop everything here. 
    if not new_sftp_zip_files:
        print('No new files to download from SFTP. Stopping process.')
        return True

    # Before we can parse any file we need to set up the tables in the database. 
    # If there is already a SQL dump in the S3 bucket we can rebuild from there, 
    # otherwise we create the tables fresh.
    prep_db(s3, db, priv_dir)

    # If there are new files, download them
    print('Downloading new files from SFTP:')
    for f in new_sftp_zip_files:
        print('-', f)
        sftp.download_files(f, priv_dir)

    # For each of the new data files, parse it into the database
    local_zip_files = [os.path.join(priv_dir, f) for f in new_sftp_zip_files]

    # For each zipfile, rebuild the staging tables, unzip the XML file and 
    # parse it into the staging tables, then insert all the newly parsed records 
    # into the main tables.
    print('Processing files:')
    for zip_file in local_zip_files:
        print('-', os.path.basename(zip_file))

        print('  - Creating staging tables...')
        db.execute_sql_file('create_tables_staging.sql')

        print('  - Parsing XML file...')
        with zipfile.ZipFile(zip_file, 'r').open(DATA_FILENAME) as xml_file:
            parse_file(xml_file, db)

        print('   - Updating appearance outcomes...')
        db.execute_sql_file('update_appearance_outcomes.sql')

        print('  - Inserting from staging to main...')
        insert_staging_to_main(db)

    # Create/upload a dump of the database to start with for next update
    print('Creating database dump and uploading to s3')
    db.dump_to(os.path.join(priv_dir, 'oca.dump'))

    # Export tables as CSVs
    for t in OCA_TABLES:
        csv_filepath = os.path.join(pub_dir, f"{t}.csv")
        db.export_csv(t, csv_filepath)

    s3 = S3(**s3_args)

    # Update "last updated date" files on S3 for the latest file processed
    create_date_files(s3, new_sftp_zip_files[-1], pub_dir)

    # Upload csv files to public folder in S3 bucket
    print('Uploading public files to S3:')
    for f in os.listdir(pub_dir):
        print('-', f)
        s3.upload_file(f"{S3_PUBLIC_FOLDER}/{f}", os.path.join(pub_dir, f))

    # Upload raw data files and database dump to private folder in S3 bucket
    print('Uploading private files to S3:')
    for f in os.listdir(priv_dir):
        print('-', f)
        s3.upload_file(f"{S3_PRIVATE_FOLDER}/{f}", os.path.join(priv_dir, f))

