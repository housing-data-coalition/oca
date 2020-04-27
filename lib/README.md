# Code

### `sftp.py`

This class provides a connection to the SFTP maintained by OCA and allows us to list the available files and download selected files.

### `s3.py`

This class provides a connection to our Amazon S3 account where both the private raw files and public csv files are stored, and allows us to list the available files and upload new files. 

### `database.py`

This class is adapted from [NYCDB](https://github.com/nycdb/nycdb/blob/master/src/nycdb/database.py), and provides a connection to the PostgreSQL database where the parsed files are stored. It includes methods to insert new rows, execute SQL files, export tables to CSV, and to create and restore from [pg_dump](https://www.postgresql.org/docs/12/app-pgdump.html) files.

### `parsers.py`

The final function `parse_file` takes an XML file and database connection from `database.py` and iterates over each case, parsing all the data into the various tables.

### `utils.py`

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

### `etl.py`

This is the main script that does the full process.


### `oca_update.py`

Finally, this file (in the top level of this repo) simply pulls environment variables from the `.env` file and runs `etl.py` to process an update to the data. 
