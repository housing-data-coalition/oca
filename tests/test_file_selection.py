import unittest

from lib.etl import select_data_files_to_process


class FileSelectionTests(unittest.TestCase):
    def test_default_new_only_behavior(self):
        selected = select_data_files_to_process(
            new_files=[
                'LandlordTenant.Initial.FiledIn2024.2024-03-01.zip',
                'LandlordTenant.Incr.2024-03-08.zip',
            ],
            reprocess_files=[],
            force_reprocess=False
        )
        self.assertEqual(
            selected,
            [
                'LandlordTenant.Initial.FiledIn2024.2024-03-01.zip',
                'LandlordTenant.Incr.2024-03-08.zip',
            ]
        )

    def test_reprocess_glob_without_force_skips_matches(self):
        selected = select_data_files_to_process(
            new_files=['LandlordTenant.Incr.2024-03-08.zip'],
            reprocess_files=[
                'LandlordTenant.Initial.FiledIn2023.2023-01-05.zip',
                'LandlordTenant.Incr.2023-05-05.zip',
            ],
            force_reprocess=False
        )
        self.assertEqual(selected, ['LandlordTenant.Incr.2024-03-08.zip'])

    def test_reprocess_glob_with_force_includes_matches(self):
        selected = select_data_files_to_process(
            new_files=['LandlordTenant.Incr.2024-03-08.zip'],
            reprocess_files=[
                'LandlordTenant.Initial.FiledIn2023.2023-01-05.zip',
                'LandlordTenant.Incr.2023-05-05.zip',
            ],
            force_reprocess=True
        )
        self.assertEqual(
            selected,
            [
                'LandlordTenant.Initial.FiledIn2023.2023-01-05.zip',
                'LandlordTenant.Incr.2023-05-05.zip',
                'LandlordTenant.Incr.2024-03-08.zip',
            ]
        )


if __name__ == '__main__':
    unittest.main()
