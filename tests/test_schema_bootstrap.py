import os
import unittest
from unittest import mock

from lib.etl_stages import ensure_core_tables_exist


class CreateTablesSqlContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sql_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'lib',
            'sql',
            'create_tables.sql',
        )
        with open(sql_path, encoding='utf-8') as f:
            cls.sql = f.read()

    def test_bootstrap_sql_is_non_destructive(self):
        self.assertNotIn('DROP TABLE', self.sql.upper())
        self.assertNotIn('DROP VIEW', self.sql.upper())

    def test_bootstrap_sql_uses_idempotent_create_patterns(self):
        self.assertIn('CREATE TABLE IF NOT EXISTS oca_index', self.sql)
        self.assertIn('CREATE TABLE IF NOT EXISTS oca_metadata', self.sql)
        self.assertIn('CREATE INDEX IF NOT EXISTS oca_addresses_bbl_idx', self.sql)


class EnsureCoreTablesExistTests(unittest.TestCase):
    def test_bootstrap_runs_when_schema_context_matches(self):
        db = mock.Mock()
        db.sql_fetch_one.return_value = ('oca_refactor', '"oca_refactor", public')

        ensure_core_tables_exist(db, 'oca_refactor')

        db.execute_sql_file.assert_called_once_with('create_tables.sql')

    def test_bootstrap_fails_when_expected_schema_missing(self):
        db = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, 'DB schema must be set'):
            ensure_core_tables_exist(db, '')

        db.execute_sql_file.assert_not_called()

    def test_bootstrap_fails_when_current_schema_does_not_match_expected(self):
        db = mock.Mock()
        db.sql_fetch_one.return_value = ('public', 'public')

        with self.assertRaisesRegex(RuntimeError, 'expected current_schema'):
            ensure_core_tables_exist(db, 'oca_refactor')

        db.execute_sql_file.assert_not_called()


if __name__ == '__main__':
    unittest.main()
