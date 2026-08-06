import os
import tempfile
import unittest
from unittest import mock

from lib.etl_helpers import create_date_files


class CreateDateFilesTests(unittest.TestCase):
    def test_writes_txt_and_svg_without_network(self):
        with tempfile.TemporaryDirectory() as local_dir:
            with mock.patch('lib.etl_helpers.requests.get') as get_mock:
                create_date_files('LandlordTenant.Incr.2024-03-08.zip', local_dir)
                get_mock.assert_not_called()

            txt_path = os.path.join(local_dir, 'last-updated-date.txt')
            svg_path = os.path.join(local_dir, 'last-updated-shield.svg')
            self.assertTrue(os.path.isfile(txt_path))
            self.assertTrue(os.path.isfile(svg_path))

            with open(txt_path, encoding='utf-8') as handle:
                self.assertEqual(handle.read(), '2024-03-08')

            with open(svg_path, encoding='utf-8') as handle:
                svg = handle.read()
            self.assertIn('Last Updated: 2024-03-08', svg)
            self.assertIn('<svg', svg)


if __name__ == '__main__':
    unittest.main()
