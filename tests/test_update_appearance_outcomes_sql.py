import os
import unittest


class UpdateAppearanceOutcomesSqlTests(unittest.TestCase):
    def test_assigns_appearanceid_before_outcomes_insert(self):
        sql_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'lib',
            'sql',
            'update_appearance_outcomes.sql',
        )
        with open(sql_path, encoding='utf-8') as f:
            sql = f.read()

        self.assertIn('DO $$', sql)
        self.assertIn('setval', sql)
        self.assertIn('MAX(appearanceid)', sql)
        do_pos = sql.index('DO $$')
        insert_pos = sql.index('INSERT INTO oca_appearance_outcomes_staging')
        self.assertLess(do_pos, insert_pos)


if __name__ == '__main__':
    unittest.main()
