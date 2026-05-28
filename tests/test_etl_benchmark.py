import json
import os
import tempfile
import unittest

from lib.benchmark_fixtures import SAMPLE_PROFILES, build_extract_xml, materialize_benchmark_samples
from lib.etl_benchmark import run_benchmark_profile, run_parse_export_preprocess
from lib.etl_metrics import EtlStageMetrics


class BenchmarkFixturesTests(unittest.TestCase):
    def test_weekly_fixture_xml_parses(self):
        xml = build_extract_xml(5, child_profile='weekly')
        self.assertIn(b'RunDate', xml)
        self.assertEqual(xml.count(b'LT-BENCH-'), 5)

    def test_materialize_creates_zips(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_benchmark_samples(tmp, profiles=['weekly'])
            self.assertTrue(os.path.isfile(paths['weekly']))
            self.assertEqual(
                os.path.basename(paths['weekly']),
                SAMPLE_PROFILES['weekly']['zip_name'],
            )


class BenchmarkHarnessTests(unittest.TestCase):
    def test_small_profile_produces_metrics_and_stable_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = os.path.join(tmp, 'fixtures')
            paths = materialize_benchmark_samples(fixtures, profiles=['weekly'])
            # Smaller run for unit test speed
            from lib.benchmark_fixtures import write_benchmark_zip
            small_zip = os.path.join(fixtures, 'LandlordTenant.Incr.2024-03-08.small.zip')
            write_benchmark_zip(small_zip, 30, child_profile='weekly')

            result = run_benchmark_profile(
                'weekly',
                small_zip,
                iterations=2,
            )
            self.assertTrue(result['summary']['all_runs_parity_ok'])
            self.assertEqual(len(result['runs']), 2)
            self.assertIn('parse_xml_total', result['runs'][0]['metrics']['stages'])
            self.assertIn('duckdb_export', result['runs'][0]['metrics']['stages'])
            self.assertIn('csv_preprocess', result['runs'][0]['metrics']['stages'])
            self.assertGreater(result['runs'][0]['metrics']['counters'].get('parse_cases_total', 0), 0)

    def test_instrumentation_does_not_change_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            priv = os.path.join(tmp, 'private')
            os.makedirs(priv)
            from lib.benchmark_fixtures import write_benchmark_zip
            write_benchmark_zip(
                os.path.join(priv, 'LandlordTenant.Incr.2024-03-08.zip'),
                20,
                child_profile='weekly',
            )

            _, checksums_off, rows_off = run_parse_export_preprocess(
                priv,
                metrics=EtlStageMetrics.disabled(),
                parse_num_threads=1,
            )

            priv2 = os.path.join(tmp, 'private2')
            os.makedirs(priv2)
            write_benchmark_zip(
                os.path.join(priv2, 'LandlordTenant.Incr.2024-03-08.zip'),
                20,
                child_profile='weekly',
            )
            _, checksums_on, rows_on = run_parse_export_preprocess(
                priv2,
                metrics=EtlStageMetrics(),
                parse_num_threads=1,
            )

            self.assertEqual(checksums_off, checksums_on)
            self.assertEqual(rows_off, rows_on)


class EtlMetricsTests(unittest.TestCase):
    def test_disabled_metrics_no_ops(self):
        m = EtlStageMetrics.disabled()
        m.increment('x')
        m.record_stage('s', 1.0)
        self.assertFalse(m.enabled)
        self.assertEqual(m.to_dict()['counters'], {})

    def test_to_json_roundtrip(self):
        m = EtlStageMetrics()
        m.increment('cases', 3)
        m.record_stage('parse', 0.5)
        data = json.loads(m.to_json())
        self.assertEqual(data['counters']['cases'], 3)
        self.assertEqual(data['stages']['parse']['duration_sec'], 0.5)


if __name__ == '__main__':
    unittest.main()
