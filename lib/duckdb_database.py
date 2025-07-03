import duckdb
import os
import threading

class DuckDB:
    """DuckDB database helper with methods for 
    exporting to csv, and running sql files and commands with thread safety"""
    
    def __init__(self, dbname):
        self.dbname = dbname
        self.conn = duckdb.connect(dbname)
        self._lock = threading.Lock()
    
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
            if params:
                return self.conn.execute(sql, params)
            return self.conn.execute(sql)
    
    def executemany(self, sql, params_list):
        """Execute SQL with multiple parameter sets"""
        with self._lock:
            return self.conn.executemany(sql, params_list)
    
    def close(self):
        if self.conn: self.conn.close()
    
    def export_tables_to_csv(self, output_dir):
        """Export all tables to CSV files"""
        os.makedirs(output_dir, exist_ok=True)
        
        with self._lock:
            # Get list of all tables
            tables = self.conn.execute("SHOW TABLES").fetchall()
            
            for table_row in tables:
                table_name = table_row[0]
                csv_path = os.path.join(output_dir, f"{table_name}.csv")
                
                # Export to CSV
                self.conn.execute(f"COPY {table_name} TO '{csv_path}' (HEADER, DELIMITER ',')")
                print(f"Exported {table_name} to {csv_path}")

                # TODO: before exporting covert arrays to the postgres format, but ignore json objects
                # Transform arrays: [1,2,3] -> {1,2,3}
                # Ignore JSON objects: {[key: value]} -> [{key: value}]