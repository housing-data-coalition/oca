import csv
import os
import tempfile
import unittest

import duckdb

from lib.duckdb_database import DuckDB
from lib.etl_csv import preprocess_csv_file, replace_postgres_array_brackets
from lib.staging_csv_export import (
    nullable_int_csv_sql,
    postgres_array_brackets_sql,
    staging_csv_needs_preprocess,
)


class PostgresArrayBracketsSqlTests(unittest.TestCase):
    def _eval_sql(self, value: str | None) -> str | None:
        conn = duckdb.connect(':memory:')
        literal = 'NULL' if value is None else f"'{value.replace(chr(39), chr(39)*2)}'"
        row = conn.execute(
            f"SELECT {postgres_array_brackets_sql(literal)}"
        ).fetchone()
        conn.close()
        return row[0]

    def test_matches_python_simple_array(self):
        self.assertEqual(self._eval_sql('[a,b]'), replace_postgres_array_brackets('[a,b]'))

    def test_matches_python_json_object_array(self):
        value = '[{"appearanceoutcometype":"Hearing"}]'
        self.assertEqual(self._eval_sql(value), replace_postgres_array_brackets(value))

    def test_matches_python_plain_text(self):
        self.assertEqual(self._eval_sql('plain'), replace_postgres_array_brackets('plain'))

    def test_null_unchanged(self):
        self.assertIsNone(self._eval_sql(None))


class NullableIntSqlTests(unittest.TestCase):
    def _eval_int(self, value) -> str:
        conn = duckdb.connect(':memory:')
        if value is None:
            row = conn.execute(f"SELECT {nullable_int_csv_sql('NULL::INTEGER')}").fetchone()
        else:
            row = conn.execute(
                f"SELECT {nullable_int_csv_sql(str(int(value)))}"
            ).fetchone()
        conn.close()
        return row[0]

    def test_null_becomes_sql_null(self):
        conn = duckdb.connect(':memory:')
        row = conn.execute(
            f"SELECT {nullable_int_csv_sql('motionsequence')} FROM (SELECT NULL::INTEGER AS motionsequence) t"
        ).fetchone()
        self.assertIsNone(row[0])

    def test_nan_marker_becomes_sql_null(self):
        conn = duckdb.connect(':memory:')
        row = conn.execute(
            f"SELECT {nullable_int_csv_sql('v')} FROM (SELECT 'NaN' AS v) t"
        ).fetchone()
        self.assertIsNone(row[0])


class StagingExportIntegrationTests(unittest.TestCase):
    def test_appearances_export_drops_appearanceid(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'staging.duckdb')
            pub = os.path.join(tmp, 'public')
            os.makedirs(pub)
            db = DuckDB(db_path)
            db.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
            db.execute(
                """
                INSERT INTO oca_appearances_staging (
                    indexnumberid, appearanceid, appearancedatetime,
                    appearancepurpose, motionsequence, appearanceoutcomes
                ) VALUES (
                    'LT-1', 99, '2024-02-15 10:00:00', 'Conference', NULL,
                    '[{"appearanceoutcometype":"Adjourned"}]'
                )
                """
            )
            db.export_tables_to_csv(pub)
            db.close()

            path = os.path.join(pub, 'oca_appearances_staging.csv')
            with open(path, newline='', encoding='utf-8') as f:
                row = next(csv.DictReader(f))
            self.assertNotIn('appearanceid', row)
            self.assertEqual(row['motionsequence'], '')
            self.assertEqual(
                row['appearanceoutcomes'],
                '[{"appearanceoutcometype":"Adjourned"}]',
            )

    def test_index_array_export_matches_preprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_path = os.path.join(tmp, 'raw.csv')
            export_path = os.path.join(tmp, 'export.csv')
            conn = duckdb.connect(':memory:')
            conn.execute('CREATE TABLE t (specialtydesignationtypes VARCHAR[])')
            conn.execute("INSERT INTO t VALUES (['HP', 'RTC'])")
            conn.execute(f"COPY t TO '{raw_path}' (HEADER, DELIMITER ',')")
            conn.close()

            with open(raw_path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                row = next(reader)
            with open(export_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['specialtydesignationtypes'])
                writer.writeheader()
                writer.writerow(row)

            preprocess_csv_file(export_path)

            db_path = os.path.join(tmp, 'staging.duckdb')
            pub = os.path.join(tmp, 'public')
            os.makedirs(pub)
            db = DuckDB(db_path)
            db.execute('CREATE TABLE oca_index_staging (specialtydesignationtypes VARCHAR[])')
            db.execute("INSERT INTO oca_index_staging VALUES (['HP', 'RTC'])")
            db.export_tables_to_csv(pub)
            db.close()

            with open(export_path, newline='', encoding='utf-8') as f:
                preprocessed = next(csv.DictReader(f))['specialtydesignationtypes']
            with open(os.path.join(pub, 'oca_index_staging.csv'), newline='', encoding='utf-8') as f:
                exported = next(csv.DictReader(f))['specialtydesignationtypes']
            self.assertEqual(exported, preprocessed)


class ExportMatchesLegacyPreprocessTests(unittest.TestCase):
    def test_all_staging_csvs_match_raw_copy_plus_preprocess(self):
        import lib.etl_csv as etl_csv_mod
        from parser_xml_fixtures import write_test_zip
        from lib.etl_stages import parse_xml_to_staging

        with tempfile.TemporaryDirectory() as tmp:
            priv = os.path.join(tmp, 'priv')
            os.makedirs(priv)
            write_test_zip(
                os.path.join(priv, 'LandlordTenant.Incr.2024-03-08.zip'),
                10,
                child_profile='weekly',
            )
            pub_legacy = os.path.join(tmp, 'legacy')
            pub_export = os.path.join(tmp, 'export')
            os.makedirs(pub_legacy)
            os.makedirs(pub_export)

            class _Manifest:
                def upsert_step(self, *args, **kwargs):
                    pass

                def upsert_file(self, *args, **kwargs):
                    pass

            db_legacy = DuckDB(os.path.join(priv, 'legacy.duckdb'))
            db_legacy.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
            parse_xml_to_staging(_Manifest(), db_legacy, priv, parse_num_threads=1)
            with db_legacy._lock:
                for table_row in db_legacy.conn.execute('SHOW TABLES').fetchall():
                    table_name = table_row[0]
                    path = os.path.join(pub_legacy, f'{table_name}.csv')
                    db_legacy.conn.execute(
                        f"COPY {table_name} TO '{path}' (HEADER, DELIMITER ',')"
                    )
            db_legacy.close()

            orig = etl_csv_mod.staging_csv_needs_preprocess
            etl_csv_mod.staging_csv_needs_preprocess = lambda _f: True
            try:
                etl_csv_mod.preprocess_staging_csv_dir(pub_legacy)
            finally:
                etl_csv_mod.staging_csv_needs_preprocess = orig

            db_export = DuckDB(os.path.join(priv, 'export.duckdb'))
            db_export.execute_sql_file('lib/sql/create_tables_staging_duckdb.sql')
            parse_xml_to_staging(_Manifest(), db_export, priv, parse_num_threads=1)
            db_export.export_tables_to_csv(pub_export)
            db_export.close()

            for name in sorted(os.listdir(pub_legacy)):
                if not name.endswith('.csv'):
                    continue
                with open(os.path.join(pub_legacy, name), 'rb') as f:
                    legacy = f.read()
                with open(os.path.join(pub_export, name), 'rb') as f:
                    exported = f.read()
                self.assertEqual(exported, legacy, name)


class StagingCsvNeedsPreprocessTests(unittest.TestCase):
    def test_staging_tables_skip_second_pass(self):
        self.assertFalse(staging_csv_needs_preprocess('oca_index_staging.csv'))
        self.assertFalse(staging_csv_needs_preprocess('oca_addresses_staging.csv'))
        self.assertFalse(staging_csv_needs_preprocess('oca_appearances_staging.csv'))

    def test_unknown_table_still_preprocessed(self):
        self.assertTrue(staging_csv_needs_preprocess('custom_table.csv'))


if __name__ == '__main__':
    unittest.main()
