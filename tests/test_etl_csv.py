import csv
import os
import tempfile
import tracemalloc
import unittest

from lib.etl_csv import preprocess_csv_file, replace_postgres_array_brackets
from lib.etl_helpers import csv_has_rows


class ReplacePostgresArrayBracketsTests(unittest.TestCase):
    def test_converts_simple_array(self):
        self.assertEqual(replace_postgres_array_brackets('[a,b]'), '{a,b}')

    def test_preserves_json_object_array(self):
        value = '[{"appearanceoutcometype":"x"}]'
        self.assertEqual(replace_postgres_array_brackets(value), value)

    def test_non_array_unchanged(self):
        self.assertEqual(replace_postgres_array_brackets('plain'), 'plain')


class PreprocessCsvFileTests(unittest.TestCase):
    def test_appearances_drops_appearanceid_and_normalizes_motionsequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'oca_appearances_staging.csv')
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        'indexnumberid',
                        'appearanceid',
                        'motionsequence',
                        'appearanceoutcomes',
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    'indexnumberid': '1',
                    'appearanceid': '99',
                    'motionsequence': '',
                    'appearanceoutcomes': '[{"appearanceoutcometype":"Hearing"}]',
                })

            preprocess_csv_file(path, chunk_size=2)

            with open(path, newline='', encoding='utf-8') as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(
                list(rows[0].keys()),
                ['indexnumberid', 'motionsequence', 'appearanceoutcomes'],
            )
            self.assertEqual(rows[0]['motionsequence'], '')
            self.assertEqual(
                rows[0]['appearanceoutcomes'],
                '[{"appearanceoutcometype":"Hearing"}]',
            )

    def test_index_array_brackets_converted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'oca_index_staging.csv')
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=['indexnumberid', 'specialtydesignationtypes'],
                )
                writer.writeheader()
                writer.writerow({
                    'indexnumberid': '1',
                    'specialtydesignationtypes': '[HP, RTC]',
                })

            preprocess_csv_file(path)

            with open(path, newline='', encoding='utf-8') as f:
                row = next(csv.DictReader(f))

            self.assertEqual(row['specialtydesignationtypes'], '{HP, RTC}')


class CsvHasRowsTests(unittest.TestCase):
    def test_empty_file_has_no_rows(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write('a,b\n')
            path = f.name
        try:
            self.assertFalse(csv_has_rows(path))
        finally:
            os.unlink(path)

    def test_data_row_detected(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write('a,b\n1,2\n')
            path = f.name
        try:
            self.assertTrue(csv_has_rows(path))
        finally:
            os.unlink(path)


class PreprocessMemoryTests(unittest.TestCase):
    def test_preprocess_does_not_scale_with_file_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'oca_index_staging.csv')
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['indexnumberid', 'specialtydesignationtypes'])
                writer.writeheader()
                for i in range(20000):
                    writer.writerow({
                        'indexnumberid': str(i),
                        'specialtydesignationtypes': '[A]',
                    })

            tracemalloc.start()
            preprocess_csv_file(path, chunk_size=500)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            # Full-file materialization would typically exceed a few MB for 20k rows.
            self.assertLess(peak, 5 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
