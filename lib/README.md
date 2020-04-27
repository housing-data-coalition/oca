# Code

## `database.py`

## `s3.py`

## `sftp.py`

## `parsers.py`

## `utils.py`

A few basic helper functions: 

* `make_dir`
	* Create new local directories

* `list_new_data_files`
	* List files that are in the SFTP but not yet in S3

* `prep_db`
	* Prepare the Postgres database (either from scratch with SQL scripts or from a `pg_dump` file)

* `insert_staging_to_main`
	* Move newly parsed records in the database over from staging tables to the main ones

* `create_date_files`
	* Create plain text and image files for the most recent date of the data extracts for display in this repo

## `etl.py`

This is the main script that does the full process.


## `oca_update.py`

Finally, this file (in the top level of this repo) simply pulls environment variables from the `.env` file and runs `etl.py` to process an update to the data. 