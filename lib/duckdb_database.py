import duckdb
import os
import threading
import time
from contextlib import contextmanager

from .etl_metrics import EtlStageMetrics, STAGING_TABLE_FAMILIES


def fetch_staging_row_counts(db) -> dict[str, int]:
    """Return row counts for known staging tables (missing tables -> 0)."""
    counts = {}
    with db._lock:
        for table_name in STAGING_TABLE_FAMILIES:
            try:
                row = db.conn.execute(f'SELECT COUNT(*) FROM {table_name}').fetchone()
                counts[table_name] = int(row[0]) if row else 0
            except Exception:
                counts[table_name] = 0
    return counts


class DuckDB:
    """DuckDB database helper with methods for 
    exporting to csv, and running sql files and commands with thread safety"""
    
    def __init__(self, dbname, metrics=None):
        self.dbname = dbname
        self.conn = duckdb.connect(dbname)
        self._lock = threading.Lock()
        self.metrics = metrics if metrics is not None else EtlStageMetrics.disabled()
    
    def execute_sql_file(self, sql_file_path):
        """Execute SQL commands from a file"""
        with open(sql_file_path, 'r') as f:
            sql_content = f.read()
        
        # Split by semicolon and execute each statement
        statements = [stmt.strip() for stmt in sql_content.split(';') if stmt.strip()]
        
        with self._lock:
            for statement in statements:
                try:
                    self.conn.execute(statement)
                except Exception as e:
                    print(f"Error executing statement: {statement[:100]}...")
                    print(f"Error: {e}")
                    raise
    
    def execute(self, sql, params=None):
        """Execute a single SQL statement"""
        with self._lock:
            return self._execute_unlocked(sql, params)

    def _execute_unlocked(self, sql, params=None):
        if params:
            return self.conn.execute(sql, params)
        return self.conn.execute(sql)

    def executemany(self, sql, params_list):
        """Execute SQL with multiple parameter sets"""
        with self._lock:
            return self._executemany_unlocked(sql, params_list)

    def _executemany_unlocked(self, sql, params_list):
        return self.conn.executemany(sql, params_list)

    @contextmanager
    def transaction(self):
        """Run a block in one DuckDB transaction (caller should not nest locks)."""
        with self._lock:
            self.conn.execute('BEGIN TRANSACTION')
            try:
                yield self
                self.conn.execute('COMMIT')
            except Exception:
                self.conn.execute('ROLLBACK')
                raise
    
    def close(self):
        if self.conn: self.conn.close()
    
    def export_tables_to_csv(self, output_dir):
        """Export all tables to CSV files"""
        os.makedirs(output_dir, exist_ok=True)
        export_start = time.perf_counter()

        with self._lock:
            # Get list of all tables
            tables = self.conn.execute("SHOW TABLES").fetchall()
            
            for table_row in tables:
                table_name = table_row[0]
                csv_path = os.path.join(output_dir, f"{table_name}.csv")
                table_start = time.perf_counter()

                # Export to CSV
                self.conn.execute(f"COPY {table_name} TO '{csv_path}' (HEADER, DELIMITER ',')")
                print(f"Exported {table_name} to {csv_path}")

                if self.metrics.enabled:
                    if os.path.isfile(csv_path):
                        self.metrics.export_bytes[table_name] = os.path.getsize(csv_path)
                    self.metrics.increment('export_tables', 1)
                    table_sec = time.perf_counter() - table_start
                    per_table = self.metrics.stages.setdefault('duckdb_export_per_table', {})
                    per_table[table_name] = round(table_sec, 6)

                # TODO: before exporting covert arrays to the postgres format, but ignore json objects
                # Transform arrays: [1,2,3] -> {1,2,3}
                # Ignore JSON objects: {[key: value]} -> [{key: value}]

        if self.metrics.enabled:
            self.metrics.record_stage(
                'duckdb_export',
                time.perf_counter() - export_start,
                table_count=len(tables),
                total_bytes=sum(self.metrics.export_bytes.values()),
            )