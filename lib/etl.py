import os
import io
import shutil
import zipfile
import requests
import re
from datetime import datetime
# TODO - replace os.path with Pathlib and its '/' operator
from pathlib import Path 

import numpy as np
import pandas as pd
import multiprocessing
import functools
from itertools import repeat
import sys

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
        db.execute_sql_file('create_tables.sql')
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


def download_pluto(output_dir):
    """
    Download and unzip PLUTO into the directory.

    :param output_dir: string or Path
    """
    print('downloading pluto')

    #check https://www.nyc.gov/site/planning/data-maps/open-data/dwn-pluto-mappluto.page for updates
    PLUTO_CSV_URL = 'https://s-media.nyc.gov/agencies/dcp/assets/files/zip/data-tools/bytes/nyc_pluto_23v2_csv.zip'

    #download and unzip
    response = requests.get(PLUTO_CSV_URL)
    content = response.content
    z = zipfile.ZipFile(io.BytesIO(response.content))

    pluto_csv = [name for name in z.namelist() if '.csv' in name][0]
    z.extract(pluto_csv, output_dir)

    # rename 
    pluto_file = os.path.join(output_dir, "pluto.csv")
    os.rename(os.path.join(output_dir, pluto_csv), pluto_file)

    return pluto_file


def oca_etl(db_args, sftp_args, s3_args, mode, remote_db_args):
    """ 
    Extract files from SFTP, parse cases, upload to S3 bucket
    """

    db = Database(**db_args)

    sftp = Sftp(**sftp_args)

    s3 = S3(**s3_args)

    # # For debugging only
    # priv_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data-private'))
    # pub_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data-public'))

    # Create local versions of folder in the S3 bucket "oca-data"
    priv_dir = make_dir('data-private') # "private/"
    pub_dir = make_dir('data-public') # "public/"
    
    # Get list of new files to download from SFTP
    new_sftp_zip_files = list_new_data_files(sftp, s3)

    # # If there are no new files we can stop everything here. 
    if not new_sftp_zip_files:
        print('No new files to download from SFTP. Stopping process.')
        return True

    # Before we can parse any file we need to set up the tables in the database. 
    # If there is already a SQL dump in the S3 bucket we can rebuild from there, 
    # otherwise we create the tables fresh.
    prep_db(s3, db, priv_dir)

    # If there are new files, download them.
    sftp = Sftp(**sftp_args) # Refresh connection since prep_db sometimes takes a while and socket will close
    print('Downloading new files from SFTP:')
    for f in new_sftp_zip_files:
        print('-', f)
        sftp.download_files(f, priv_dir)

    # For each of the new data files, parse it into the database
    local_zip_files = [os.path.join(priv_dir, f) for f in new_sftp_zip_files]

    # # For debugging only
    # # ---
    # # When sql dump fails, grab zips from s3 backup
    # aws_id = s3_args['aws_id']
    # aws_key = s3_args['aws_key']
    # aws_bucket_name = 'oca-level2-data'
    # backup_s3 = S3(aws_id, aws_key, aws_bucket_name)
    # for f in backup_s3.list_files('.+\.zip', S3_PRIVATE_FOLDER):
    #     backup_s3.download_file(f"{S3_PRIVATE_FOLDER}/{f}", os.path.join(priv_dir, f))
    # def sort_by_date(file):
    #     r = re.search(r'(\d+.+)\.zip', file).group(0).replace('.',' ')
    #     return r
    # local_zip_files = sorted([os.path.join(priv_dir, f) for f in os.listdir(priv_dir)], key = sort_by_date)
    # # ---

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

        print('\n   - Updating appearance outcomes...')
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

    if mode == "2":
        # Geocode records before uploading to S3
        from .geocode_record import geocode_record, geocode_using_census_batch
        # Geocode 
        input_csv = Path(pub_dir) / 'oca_addresses.csv'
        output_csv = Path(pub_dir) /'oca_addresses.csv'
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
        df_1 = df[(((pd.isna(df['lat'])) | (df['lat'] == '')) & (df['house_number'] != ''))].copy().reset_index()
        print(f'Geocoding {len(df_1)} entries in {output_csv}.')

        records = df_1.to_dict('records')

        # Geocode records using NYC GeoSupport
        # TODO - check if pluto in the database matches the pluto version of the geosupport
        with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
            it = pd.DataFrame(pool.map(functools.partial(geocode_record, addr_cols=addr_cols), records, 10000))

        del df_1 # delete unused objects to avoid docker's memory error / 137
        del records 
        
        # Geocode other records using the US Batch Census Geocoder
        #   Sub-select for all addresses that are missing latitude; also needs to have a house number
        df_2 = it[(((pd.isna(it['lat'])) | (it['lat'] == '')))].copy().reset_index()
        print(f'Geocoding {len(df_2)} entries in {output_csv} using another geocoder. {datetime.now()}')

        # # For debugging only
        # # ---
        # # data_split = np.split(df_2, range(chunk_size, df_2.shape[0], 10000))
        # # geocode_using_census_batch(data_split[2], pub_dir)

        with multiprocessing.Pool(processes=min([5, multiprocessing.cpu_count()])) as pool:
            chunk_size = 2500 # census batch limit is 10,000. Smaller batches tend to work better
            data_split = zip(np.split(df_2, range(chunk_size, df_2.shape[0], chunk_size)), repeat(pub_dir))
            it_2 = pd.concat(pool.starmap(geocode_using_census_batch, data_split))
            del df_2
            del data_split
            
        print(f'Done geocoding. {datetime.now()}')
        # Concat and drop duplicates by keeping the last changes from US Batch Census Geocoder (overwrites the GeoSupport returns
        concat = pd.concat([df, it, it_2], ignore_index = True).drop_duplicates(subset=['indexnumberid'], ignore_index = True, keep = 'last')[it.columns]
        del df
        del it
        del it_2
        pd.DataFrame(concat).to_csv(output_csv, index=False)
        del concat

    s3 = S3(**s3_args)

    # Update "last updated date" files on S3 for the latest file processed
    create_date_files(s3, new_sftp_zip_files[-1], pub_dir)

    # TODO: upload in parallel
    # http://ls.pwd.io/2013/06/parallel-s3-uploads-using-boto-and-threads-in-python/
    
    # Upload csv files to public folder in S3 bucket
    print('Uploading public files to S3:')
    for f in os.listdir(pub_dir):
        print('-', f)
        s3_filename = f
        # to maintain consistent names for public level-1 csv files, we'll rename the level-2 version
        if mode == "2" and f == "oca_addresses.csv":
            s3_filename = "oca_addresses_private.csv"
        s3.upload_file(f"{S3_PUBLIC_FOLDER}/{s3_filename}", os.path.join(pub_dir, f))

    # Upload raw data files and database dump to private folder in S3 bucket
    print('Uploading private files to S3:')
    for f in os.listdir(priv_dir):
        print('-', f)
        s3.upload_file(f"{S3_PRIVATE_FOLDER}/{f}", os.path.join(priv_dir, f))

    # use s3 import to overwrite tables in the remote RDS
    if remote_db_args['db_url']:
        print('Importing csvs to the RDS:')
        remote_db = Database(**remote_db_args)
        
        # reset tables from scratch
        remote_db.execute_sql_file('create_tables.sql')

        # import tables from s3
        for t in OCA_TABLES:
            print('-', f'{t} table to remote db')
            s3_name = t
            if mode == "2" and t == "oca_addresses":
                s3_name = "oca_addresses_private"
            remote_db.sql(f"""
                SELECT aws_s3.table_import_from_s3(
                '{t}', '', '(FORMAT CSV, HEADER)',
                aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', 'public/{s3_name}.csv', 'us-east-1'),
                aws_commons.create_aws_credentials('{s3_args["aws_id"]}', '{s3_args["aws_key"]}', '')
            );
            """)

    # setup pluto if it does not exist
    if not db.sql_fetch_one(
        "SELECT * FROM information_schema.tables WHERE table_name = 'pluto'"):
        pluto_file = download_pluto(pub_dir)
        
        if remote_db_args['db_url']:     
                print('uploading pluto to s3')
                s3.upload_file(f"{S3_PUBLIC_FOLDER}/pluto.csv", pluto_file)

                print('importing pluto to db')
                db.execute_sql_file('create_pluto_table.sql')
                
                db.sql(f"""
                    SELECT aws_s3.table_import_from_s3(
                    'pluto', '', '(FORMAT CSV, HEADER)',
                    aws_commons.create_s3_uri('{s3_args["aws_bucket_name"]}', 'public/pluto.csv', 'us-east-1'),
                    aws_commons.create_aws_credentials('{s3_args["aws_id"]}', '{s3_args["aws_key"]}', '')
                );
                """)
        else:
            db.execute_sql_file('create_pluto_table.sql')
            db.import_csv('pluto', pluto_file)
            
        db.execute_sql_file('alter_pluto_table.sql')

    # TODO: setup census tracts if it does not exist 
            

    if mode == "2":
        if remote_db_args['db_url']:
            db = Database(**remote_db_args)
        else:
            # Todo: Check if local database as postgis setup (also change the docker image to postgis)
            quit()
            
        # create views and grant access to folks
        db.execute_sql_file('create_addresses_views.sql')

        # download bbl view as csv and upload to s3
        view = "oca_addresses_with_bbl"
        print(f"Creating {view} and uploadng to S3")
        csv_filepath = os.path.join(pub_dir, f"{view}.csv")
        db.export_view_as_csv(view, csv_filepath)
        s3.upload_file(f"{S3_PUBLIC_FOLDER}/{view}.csv", os.path.join(pub_dir, f"{view}.csv"))

        view = "oca_addresses_with_ct"
        print(f"Creating {view} and uploadng to S3")
        csv_filepath = os.path.join(pub_dir, f"{view}.csv")
        db.export_view_as_csv(view, csv_filepath)
        s3.upload_file(f"{S3_PUBLIC_FOLDER}/{view}.csv", os.path.join(pub_dir, f"{view}.csv"))

        # add level-1 version of address table from level-2 data and maintain consistent name
        view = "oca_addresses_public"
        s3_filename = "oca_addresses"
        print(f"Creating {view} and uploadng to S3")
        csv_filepath = os.path.join(pub_dir, f"{view}.csv")
        db.export_view_as_csv(view, csv_filepath)
        s3.upload_file(f"{S3_PUBLIC_FOLDER}/{s3_filename}.csv", os.path.join(pub_dir, f"{view}.csv"))
