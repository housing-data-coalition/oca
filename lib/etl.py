import os
import shutil
import zipfile

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
    sftp_zip_files = sftp.list_files(DATA_ZIPFILE_PAT)
    s3_zip_files = s3.list_files(DATA_ZIPFILE_PAT)
    new_sftp_zip_files = list(set(sftp_zip_files) - set(s3_zip_files))

    # It's important that everything is processed in order because files 
    # can contain monidy/delete cases invluded in past files
    new_sftp_zip_files.sort()

    return new_sftp_zip_files

def prep_db(s3, db, local_dir):
    if s3.list_files('oca.dump'):
        print('Rebuilding tables from SQL dump')
        s3.download_file('private/oca.dump', os.path.join(local_dir, 'oca.dump'))
        db.restore_from(os.path.join(local_dir, 'oca.dump'))
    else:
        print('Creating tables from scratch')
        db.execute_sql_file('create_tables.sql')


def oca_etl(db_args, sftp_args, s3_args):
    """ Extract files from SFTP, parse cases, upload to S3 bucket 
    """

    db = Database(**db_args)

    sftp = Sftp(**sftp_args)

    s3 = S3(**s3_args)

    # Create local versions of folder in the S3 bucket "oca-data"
    priv_dir = make_dir('data-private') # "private/"
    pub_dir = make_dir('data-public') # "public/"
    
    # Get list of new files to download from SFTP
    new_sftp_zip_files = list_new_data_files(sftp, s3)

    # If there are no new files we can stop everything here. 
    if not new_sftp_zip_files:
        print('No new files to download from SFTP. Stopping process.')
        return True

    # If there are new files, download them
    print('Downloading new files from SFTP:')
    for f in new_sftp_zip_files:
        print('- ', f)
        sftp.download_files(f, priv_dir)

    # Before we can parse any file we need to set up the tables in the database. 
    # If there is already a SQL dump in the S3 bucket we can rebuild from there, 
    # otherwise we create the tables fresh.
    prep_db(s3, db, priv_dir)

    # For each of the new data files, parse it into the database
    local_zip_files = [os.path.join(priv_dir, f) for f in new_sftp_zip_files]

    print('Parsing files:')
    for zip_file in local_zip_files:
        print('- ', os.path.basename(zip_file))
        with zipfile.ZipFile(zip_file, 'r').open(DATA_FILENAME) as xml_file:
            parse_file(xml_file, db)

    # Update the derived table with new data
    print('Building oca_appearance_outcomes table')
    db.execute_sql_file('update_appearance_outcomes.sql')

    # Create/upload a dump of the database to start with for next update
    print('Creating database dump and uploading to s3')
    db.dump_to(os.path.join(priv_dir, 'oca.dump'))

    # Export tables as CSVs
    for t in OCA_TABLES:
        csv_filepath = os.path.join(pub_dir, f"{t}.csv")
        db.export_csv(t, csv_filepath)

    # Upload csv files to public folder in S3 bucket
    print('Uploading public files to S3:')
    for f in os.listdir(pub_dir):
        print('- ', f)
        s3.upload_file(f"public-test/{f}", os.path.join(pub_dir, f))

    # Upload raw data files and database dump to private folder in S3 bucket
    print('Uploading private files to S3:')
    for f in os.listdir(priv_dir):
        print('- ', f)
        s3.upload_file(f"private/{f}", os.path.join(priv_dir, f))
