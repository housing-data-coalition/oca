#!/usr/bin/env python

import dotenv
import os
import argparse
from pathlib import Path

from lib.etl import oca_etl

dotenv.load_dotenv()

def parse_bool(raw_value):
	if raw_value is None:
		return False
	return str(raw_value).strip().lower() in ('1', 'true', 'yes', 'y', 'on')

def parse_optional_int(raw_value):
	if raw_value in (None, ''):
		return None
	return int(raw_value)

def parse_args():
	parser = argparse.ArgumentParser(description='Run OCA ETL pipeline')
	parser.add_argument('--db-schema', default=os.environ.get('DB_SCHEMA', ''), help='Database schema search_path target')
	parser.add_argument('--s3-prefix', default=os.environ.get('S3_PREFIX', ''), help='Optional S3 prefix namespace for private/public files')
	parser.add_argument('--reprocess-glob', default=os.environ.get('REPROCESS_GLOB', ''), help='Filename glob for S3 private zip reprocessing')
	parser.add_argument('--force-reprocess', action='store_true', default=parse_bool(os.environ.get('FORCE_REPROCESS')), help='Reprocess matched files even if already in S3 private backup')
	parser.add_argument('--geocode-workers', type=int, default=parse_optional_int(os.environ.get('GEOCODE_WORKERS')), help='Worker process count for geocode pool')
	parser.add_argument('--census-batch-chunk-size', type=int, default=int(os.environ.get('CENSUS_BATCH_CHUNK_SIZE', '2500')), help='Chunk size for census batch geocoder input')
	parser.add_argument('--csv-row-check-chunk-size', type=int, default=int(os.environ.get('CSV_ROW_CHECK_CHUNK_SIZE', '1000')), help='Chunk size used for constant-memory CSV non-empty checks')
	parser.add_argument('--parse-write-batch-enabled', action='store_true', default=parse_bool(os.environ.get('PARSE_WRITE_BATCH_ENABLED', '1')), help='Buffer parser DuckDB writes and flush in transaction windows')
	parser.add_argument('--parse-write-batch-size', type=int, default=int(os.environ.get('PARSE_WRITE_BATCH_SIZE', '128')), help='Max buffered INSERT statements before flush')
	parser.add_argument('--parse-write-flush-every-n-cases', type=int, default=int(os.environ.get('PARSE_WRITE_FLUSH_EVERY_N_CASES', '16')), help='Flush buffered writes after this many cases per worker')
	return parser.parse_args()

def main():
	args = parse_args()

	db_args = {
		'db_url': os.environ.get('DATABASE_URL', ''),
		'schema': args.db_schema
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

	remote_db_args = {
		'db_url': os.environ.get('CLONED_DATABASE_URL', '')
	}

	os.environ['PARSE_WRITE_BATCH_ENABLED'] = '1' if args.parse_write_batch_enabled else '0'
	os.environ['PARSE_WRITE_BATCH_SIZE'] = str(args.parse_write_batch_size)
	os.environ['PARSE_WRITE_FLUSH_EVERY_N_CASES'] = str(args.parse_write_flush_every_n_cases)

	runtime_args = {
		'db_schema': args.db_schema,
		's3_prefix': args.s3_prefix,
		'reprocess_glob': args.reprocess_glob,
		'force_reprocess': args.force_reprocess,
		'geocode_workers': args.geocode_workers,
		'census_batch_chunk_size': args.census_batch_chunk_size,
		'csv_row_check_chunk_size': args.csv_row_check_chunk_size,
	}

	oca_etl(db_args, sftp_args, s3_args, mode, remote_db_args, runtime_args)

if __name__== "__main__":
	main()
