import urllib.parse
import psycopg2
import psycopg2.extras
from psycopg2 import sql
import os

# https://github.com/nycdb/nycdb/blob/master/src/nycdb/sql.py
def insert_many(table_name, rows):
    '''
    Given a table name and a list of dictionaries representing
    rows, generate a (sql, template) tuple of strings that can be
    passed to psycopg2.extras.execute_values() [1] to bulk insert all the
    values for improved efficiency [2].
    For example:
        >>> insert_many('boop', [{'foo': 1, 'bar': 2}])
        ('INSERT INTO boop (foo, bar) VALUES %s', '(%(foo)s, %(bar)s)')
    [1]: http://initd.org/psycopg/docs/extras.html#psycopg2.extras.execute_values
    [2]: https://stackoverflow.com/a/30985541
    '''

    field_names = list(rows[0].keys())
    fields = ', '.join(field_names)
    placeholders = ', '.join(["%({})s".format(k) for k in field_names])
    template = f"({placeholders})"
    sql = f"INSERT INTO {table_name} ({fields}) VALUES %s"

    return sql, template


# https://github.com/nycdb/nycdb/blob/master/src/nycdb/database.py
class Database:
    """Database connection to OCA database"""

    def __init__(self, db_url, autocommit = False):
        self.db_url = db_url
        self.conn = psycopg2.connect(db_url) 

    def __exit__(self, exc_type, exc_value, traceback):
        self.conn.close()

    def sql(self, SQL, autocommit = False):
        """ Executes single sql statement 

        Set auto commit to run queries like VACUUM FULL [1]
        [1]: https://til.codeinthehole.com/posts/about-a-gotcha-with-psycopg2s-autocommit-handling/
        """
        if autocommit: self.conn.set_session(autocommit=True)
        
        with self.conn.cursor() as curs:
            curs.execute(SQL)

        if autocommit: self.conn.set_session(autocommit=False) # unset
        self.conn.commit()

    def sql_fetch_one(self, SQL):
        with self.conn.cursor() as curs:
            curs.execute(SQL)
            return curs.fetchone()

    def insert_rows(self, rows, table_name):
        """
        Inserts many rows, all in the same transaction.
        """

        with self.conn.cursor() as curs:
            sql_str, template = insert_many(table_name, rows)
            try:
                psycopg2.extras.execute_values(
                    curs,
                    sql_str,
                    rows,
                    template=template,
                    page_size=len(rows)
                )
            except psycopg2.DataError:
                print(rows) # useful for debugging
                raise
        self.conn.commit()


    def execute_sql_file(self, sql_file):
        """
        Executes the provided sql file.
        Assumes the path is relative to ./sql
        """
        file_path = os.path.join(os.path.dirname(__file__), 'sql', sql_file)

        with open(file_path, 'r', encoding='utf-8') as f:
            self.sql(f.read())


    def export_csv(self, table_name, file_path):
        """ Exports tables to CSV files """
        
        f = open(file_path, 'w')

        with self.conn.cursor() as curs:
            curs.copy_expert(f"COPY {table_name} TO STDOUT WITH CSV HEADER", f)

        f.close()

    def import_csv(self, table_name, file_path):
        """ Imports a CSV file to existing table """

        f = open(file_path, 'r')

        with self.conn.cursor() as curs:
            curs.copy_expert(f'COPY {table_name} FROM STDIN WITH CSV HEADER', f)

        self.conn.commit()
        f.close()



    def export_view_as_csv(self, table_name, file_path):
        """ Exports tables to CSV files """
        
        f = open(file_path, 'w')

        with self.conn.cursor() as curs:
            curs.copy_expert(f"COPY (SELECT * FROM {table_name}) TO STDOUT WITH CSV HEADER", f)

        f.close()

    def dump_to(self, file_path):
        """ pg_dump the database to file """
        cmd = f"pg_dump {self.db_url} -Fc > {file_path}"
        os.system(cmd)


    def restore_from(self, file_path):
        """ pg_restore the database from file """
        cmd = f"pg_restore -d {self.db_url} -c {file_path}"
        os.system(cmd)

