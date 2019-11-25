#!/usr/bin/env python

import dotenv
import os

from lib.etl import process_oca_extract

dotenv.load_dotenv()


def main():
	xml_filename="LandlordTenantExtract.xml"
	db_url=os.environ.get('DATABASE_URL', '')
	aws_id=os.environ.get('AWS_ACCESS_KEY_ID', '')
	aws_key=os.environ.get('AWS_SECRET_ACCESS_KEY', '')

	process_oca_extract(xml_filename, db_url, aws_id, aws_key)

if __name__== "__main__":
	main()
