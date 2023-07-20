#!/usr/bin/env python

import dotenv
import os

from lib.etl import oca_etl

dotenv.load_dotenv()

def main():

	db_args = {
		'db_url': os.environ.get('DATABASE_URL', '')
	}

	s3_args = {
		'aws_id': os.environ.get('AWS_ACCESS_KEY_ID', ''),
		'aws_key': os.environ.get('AWS_SECRET_ACCESS_KEY', ''),
		'aws_bucket_name': os.environ.get('AWS_S3_BUCKET_NAME', '')
	}

	sftp_args = {
		'host': os.environ.get('SFTP_HOST', ''),
		'user': os.environ.get('SFTP_USER', ''),
		'pswd': os.environ.get('SFTP_PSWD', ''),
		'dir': os.environ.get('SFTP_DIR', '')
	}

	mode = os.environ.get('MODE', '')
	remote_rds = os.environ.get('CLONED_DATABASE_URL', '')

	oca_etl(db_args, sftp_args, s3_args, mode, remote_rds)

if __name__== "__main__":
	main()
