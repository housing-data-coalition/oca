from lxml import etree
import frogress
import os
import shutil
import subprocess

from .database import Database
from .parsers import parse_case, oca_tag
from .s3 import S3


OCA_TABLES = [
    'oca_index',
    'oca_causes',
    'oca_addresses',
    'oca_parties',
    'oca_events',
    'oca_appearances',
    'oca_motions',
    'oca_decisions',
    'oca_judgments',
    'oca_warrants',
]


def process_oca_extract(xml_filename, db_url, aws_id, aws_key):

    db = Database(db_url)

    s3 = S3(aws_id, aws_key)

    # Drop/Create all tables
    db.execute_sql_file('create_tables.sql')

    # Create a local folder to download the XML files from S3
    xml_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data-raw'))
    shutil.rmtree(xml_dir, ignore_errors=True)
    os.mkdir(xml_dir)

    xml_filepath = os.path.join(xml_dir, xml_filename)

    s3.get_object_download(xml_filename, xml_filepath)

    context = etree.iterparse(xml_filepath, tag=oca_tag('Index'))

    for action, case in frogress.bar(context, source=xml_filepath):

        # If case already exists in DB delete it, 
        # if we have delete instructions don't re-add it, 
        # otheriwse parse the case and insert it into the various tables.
        parse_case(case, db)

        # Clear the case element to free memory
        case.clear()

    # Create apperance outcomes table
    db.execute_sql_file('update_appearance_outcomes.sql')

    OCA_TABLES.append('oca_appearance_outcomes')

    # Create a local folder to export the CSV files before uploading to S3
    csv_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data-clean'))
    shutil.rmtree(csv_dir, ignore_errors=True)
    os.mkdir(csv_dir)

    for t in OCA_TABLES:
        csv_filename = f"{t}.csv"
        csv_filepath = os.path.abspath(os.path.join(csv_dir, csv_filename))
        # csv_filepath = os.path.join('/var/lib/postgresql/data/pgdata', csv_filename)
        print(csv_filepath)

        # Export tables locally
        db.export_csv(t, csv_filepath)

        # upload CSVs to Public S3 bucket
        s3.put_object_file(csv_filename, csv_filepath)
        
