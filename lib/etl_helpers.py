import csv
import io
import os
import re
import shutil
import zipfile

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


def csv_has_rows(csv_filepath):
    """Return True when the CSV has at least one data row (header excluded)."""
    with open(csv_filepath, newline='', encoding='utf-8') as csv_file:
        reader = csv.reader(csv_file)
        try:
            next(reader)
        except StopIteration:
            return False
        for _ in reader:
            return True
    return False


def _last_updated_badge_svg(date):
    label = f'Last Updated: {date}'
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="320" height="28" role="img" aria-label="{label}">
  <rect width="100%" height="100%" rx="4" fill="#fecc00"/>
  <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
        font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="14" fill="#000">{label}</text>
</svg>
'''


def create_date_files(data_file, local_dir):
    """
    Create a text file and a local SVG badge with the data last-updated date.

    :param data_file: file path for data being processed
    :param local_dir: path for local directory to save date files
    """
    date = re.search(r'(\d{4}-\d{2}-\d{2})', data_file).group(1)

    txt_file = os.path.join(local_dir, 'last-updated-date.txt')
    with open(txt_file, 'w', encoding='utf-8') as handle:
        handle.write(date)

    svg_file = os.path.join(local_dir, 'last-updated-shield.svg')
    with open(svg_file, 'w', encoding='utf-8') as handle:
        handle.write(_last_updated_badge_svg(date))


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
