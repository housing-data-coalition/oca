import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import Error, InterfaceError, OperationalError, sql


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == '':
        return default
    return int(raw)


def default_statement_timeout_ms():
    """RDS statement_timeout for long-running ETL SQL (override via DB_STATEMENT_TIMEOUT_MS)."""
    return _env_int('DB_STATEMENT_TIMEOUT_MS', 3_600_000)


def _connect_params():
    """libpq TCP keepalive settings (override via DB_KEEPALIVES_* env)."""
    return {
        'keepalives': _env_int('DB_KEEPALIVES', 1),
        'keepalives_idle': _env_int('DB_KEEPALIVES_IDLE', 60),
        'keepalives_interval': _env_int('DB_KEEPALIVES_INTERVAL', 10),
        'keepalives_count': _env_int('DB_KEEPALIVES_COUNT', 5),
    }


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
    sql_str = f"INSERT INTO {table_name} ({fields}) VALUES %s"

    return sql_str, template


# https://github.com/nycdb/nycdb/blob/master/src/nycdb/database.py
class Database:
    """Database connection to OCA database"""

    def __init__(self, db_url, schema='', autocommit=False):
        self.db_url = db_url
        self.schema = schema
        self.conn = None
        self._connect()

    def _connect(self):
        self.conn = psycopg2.connect(self.db_url, **_connect_params())
        if self.schema:
            self.set_search_path(self.schema)

    def _close_connection(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def _connection_is_closed(self):
        if self.conn is None:
            return True
        closed = getattr(self.conn, 'closed', None)
        if isinstance(closed, bool):
            return closed
        if isinstance(closed, int):
            return closed != 0
        return False

    def _safe_rollback(self):
        if self._connection_is_closed():
            self._close_connection()
            return
        try:
            self.conn.rollback()
        except (InterfaceError, OperationalError, Error, AttributeError):
            self._close_connection()

    def set_statement_timeout(self, timeout_ms=None):
        timeout = timeout_ms if timeout_ms is not None else default_statement_timeout_ms()
        self.sql(f"SET statement_timeout = '{timeout}'")

    def ensure_connection(self):
        """Ping the connection; reconnect if the server closed an idle session.

        Returns True if a new connection was opened, False if the existing one is healthy.
        """
        if self._connection_is_closed():
            self._connect()
            return True
        try:
            with self.conn.cursor() as curs:
                curs.execute('SELECT 1')
            return False
        except Error:
            try:
                self.conn.rollback()
                with self.conn.cursor() as curs:
                    curs.execute('SELECT 1')
                return False
            except (OperationalError, InterfaceError, Error, AttributeError):
                self._close_connection()
                self._connect()
                return True

    def __exit__(self, exc_type, exc_value, traceback):
        self._close_connection()

    def set_search_path(self, schema):
        with self.conn.cursor() as curs:
            curs.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        self.conn.commit()

    def execute(self, SQL, autocommit=False):
        """Execute SQL without committing (for use inside transaction blocks)."""
        self.ensure_connection()
        if autocommit:
            self.conn.set_session(autocommit=True)

        with self.conn.cursor() as curs:
            curs.execute(SQL)

        if autocommit:
            self.conn.set_session(autocommit=False)

    def sql(self, SQL, autocommit=False):
        """Execute a single SQL statement and commit.

        Set autocommit to run queries like VACUUM FULL [1]
        [1]: https://til.codeinthehole.com/posts/about-a-gotcha-with-psycopg2s-autocommit-handling/
        """
        self.ensure_connection()
        try:
            self.execute(SQL, autocommit=autocommit)
            self.conn.commit()
        except Exception:
            self._safe_rollback()
            raise

    @contextmanager
    def transaction(self):
        """Run a block in one DB transaction; rollback on any exception."""
        self.ensure_connection()
        try:
            yield self
            self.conn.commit()
        except Exception:
            self._safe_rollback()
            raise

    def sql_fetch_one(self, SQL):
        self.ensure_connection()
        with self.conn.cursor() as curs:
            curs.execute(SQL)
            return curs.fetchone()

    def sql_fetch_all(self, SQL):
        self.ensure_connection()
        with self.conn.cursor() as curs:
            curs.execute(SQL)
            return curs.fetchall()

    def sql_fetch_all_from_file(self, sql_file):
        file_path = os.path.join(os.path.dirname(__file__), 'sql', sql_file)
        with open(file_path, 'r', encoding='utf-8') as f:
            return self.sql_fetch_all(f.read())

    def insert_rows(self, rows, table_name, page_size=1000):
        """
        Inserts many rows, all in the same transaction.
        """
        if not rows:
            return

        self.ensure_connection()
        try:
            with self.conn.cursor() as curs:
                sql_str, template = insert_many(table_name, rows)
                try:
                    psycopg2.extras.execute_values(
                        curs,
                        sql_str,
                        rows,
                        template=template,
                        page_size=min(page_size, len(rows)),
                    )
                except psycopg2.DataError:
                    print(rows)  # useful for debugging
                    raise
            self.conn.commit()
        except Exception:
            self._safe_rollback()
            raise

    def execute_sql_file(self, sql_file, commit=True):
        """
        Executes the provided sql file.
        Assumes the path is relative to ./sql
        """
        file_path = os.path.join(os.path.dirname(__file__), 'sql', sql_file)

        with open(file_path, 'r', encoding='utf-8') as f:
            sql_text = f.read()
        if commit:
            self.sql(sql_text)
        else:
            self.execute(sql_text)

    def export_csv(self, table_name, file_path):
        """ Exports tables to CSV files """
        self.ensure_connection()
        with open(file_path, 'w', encoding='utf-8') as f:
            with self.conn.cursor() as curs:
                curs.copy_expert(f"COPY {table_name} TO STDOUT WITH CSV HEADER", f)

    def import_csv(self, table_name, file_path):
        """ Imports a CSV file to existing table """
        self.ensure_connection()
        with open(file_path, 'r', encoding='utf-8') as f:
            with self.conn.cursor() as curs:
                curs.copy_expert(f'COPY {table_name} FROM STDIN WITH CSV HEADER', f)

        self.conn.commit()

    def export_view_as_csv(self, table_name, file_path):
        """ Exports tables to CSV files """
        self.ensure_connection()
        with open(file_path, 'w', encoding='utf-8') as f:
            with self.conn.cursor() as curs:
                curs.copy_expert(f"COPY (SELECT * FROM {table_name}) TO STDOUT WITH CSV HEADER", f)

    def dump_to(self, file_path):
        """ pg_dump the database to file """
        cmd = f"pg_dump {self.db_url} -Fc > {file_path}"
        os.system(cmd)

    def restore_from(self, file_path):
        """ pg_restore the database from file """
        cmd = f"pg_restore -d {self.db_url} -c {file_path}"
        os.system(cmd)
