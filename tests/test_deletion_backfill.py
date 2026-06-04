import unittest
from unittest import mock

from lib.etl_stages import count_tombstone_orphans, purge_tombstoned_cases


class TombstoneOrphanCountTests(unittest.TestCase):
    def test_count_tombstone_orphans(self):
        db = mock.Mock()
        db.sql_fetch_one.return_value = (3,)
        self.assertEqual(count_tombstone_orphans(db), 3)
        self.assertIn('oca_metadata', db.sql_fetch_one.call_args[0][0])
        self.assertIn('deletedate IS NOT NULL', db.sql_fetch_one.call_args[0][0])


class PurgeTombstonedCasesTests(unittest.TestCase):
    def test_purge_runs_sql_and_records_manifest(self):
        db = mock.Mock()
        db.sql_fetch_one.side_effect = [(5,), (0,)]
        manifest = mock.Mock()

        before, after = purge_tombstoned_cases(manifest, db)

        self.assertEqual((before, after), (5, 0))
        db.execute_sql_file.assert_called_once_with('purge_tombstoned_cases.sql')
        manifest.upsert_step.assert_any_call('deletion_backfill', 'running')
        manifest.upsert_step.assert_any_call(
            'deletion_backfill',
            'completed',
            details={'orphan_count_before': 5, 'orphan_count_after': 0},
        )


if __name__ == '__main__':
    unittest.main()
