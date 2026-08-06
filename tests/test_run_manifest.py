import unittest

from lib.etl_run_manifest import EtlRunManifest, completed_reprocess_files
from lib.etl_file_selection import select_data_files_to_process


class FakeDb:
    def __init__(self):
        self.sql_calls = []
        self.fetch_one_queue = []
        self.fetch_all_result = []

    def execute_sql_file(self, sql_file):
        self.sql_calls.append(("execute_sql_file", sql_file))

    def sql(self, statement):
        self.sql_calls.append(("sql", statement))

    def sql_fetch_one(self, statement):
        self.sql_calls.append(("sql_fetch_one", statement))
        if self.fetch_one_queue:
            return self.fetch_one_queue.pop(0)
        return (None,)

    def sql_fetch_all(self, statement):
        self.sql_calls.append(("sql_fetch_all", statement))
        return self.fetch_all_result


class RunManifestTests(unittest.TestCase):
    def test_completed_reprocess_files_filters_manifest_hits(self):
        fake_db = FakeDb()
        fake_db.fetch_all_result = [("file_a.zip",), ("file_b.zip",)]
        completed = completed_reprocess_files(fake_db, ["file_a.zip", "file_c.zip"])
        self.assertEqual(completed, {"file_a.zip", "file_b.zip"})
        sql = fake_db.sql_calls[-1][1]
        self.assertIn("cases_failed", sql)
        self.assertIn("= 0", sql)

    def test_completed_reprocess_files_excludes_files_with_case_failures(self):
        """SQL must filter out completed rows where details.cases_failed > 0."""
        fake_db = FakeDb()
        fake_db.fetch_all_result = [("file_clean.zip",)]
        completed = completed_reprocess_files(
            fake_db,
            ["file_clean.zip", "file_dirty.zip"],
        )
        self.assertEqual(completed, {"file_clean.zip"})
        sql = fake_db.sql_calls[-1][1]
        self.assertIn("COALESCE((ef.details->>'cases_failed')::int, 0) = 0", sql)

    def test_reprocess_without_force_skips_completed_files(self):
        new_files = ["LandlordTenant.Incr.2024-03-01.zip"]
        reprocess_files = [
            "LandlordTenant.Incr.2023-01-01.zip",
            "LandlordTenant.Incr.2023-01-08.zip",
        ]
        already_completed = {"LandlordTenant.Incr.2023-01-01.zip"}
        selected = select_data_files_to_process(
            new_files=new_files,
            reprocess_files=sorted(set(reprocess_files) - already_completed),
            force_reprocess=False,
        )
        self.assertEqual(selected, ["LandlordTenant.Incr.2024-03-01.zip"])

    def test_mark_run_completed_records_files_needing_reprocess(self):
        fake_db = FakeDb()
        manifest = EtlRunManifest(fake_db, 'public', '', '2', '', False)
        manifest.mark_run_completed(
            2,
            1,
            0,
            files_needing_reprocess=['dirty.zip'],
        )
        sql = fake_db.sql_calls[-1][1]
        self.assertIn('files_needing_reprocess', sql)
        self.assertIn('dirty.zip', sql)
        self.assertIn('processed_file_count = 1', sql)


if __name__ == '__main__':
    unittest.main()
