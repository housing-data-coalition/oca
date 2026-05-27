import unittest

from lib.etl import EtlRunManifest, completed_reprocess_files, select_data_files_to_process


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

    def test_advisory_lock_failure_raises(self):
        fake_db = FakeDb()
        fake_db.fetch_one_queue = [(12345,), (False,)]
        manifest = EtlRunManifest(
            db=fake_db,
            schema_name="oca_refactor",
            s3_prefix="refactor/dev",
            mode="2",
            reprocess_glob="",
            force_reprocess=False,
        )
        with self.assertRaises(RuntimeError):
            manifest.acquire_lock()


if __name__ == "__main__":
    unittest.main()
