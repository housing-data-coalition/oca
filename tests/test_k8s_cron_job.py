import os
import re
import unittest

K8S_CRON_JOB = os.path.join(
    os.path.dirname(__file__), '..', 'k8s', 'k8s-cron-job.yaml'
)


class K8sCronJobManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(K8S_CRON_JOB, encoding='utf-8') as handle:
            cls.raw = handle.read()

    def test_memory_limit_two_gib_class(self):
        self.assertIn('memory: "2Gi"', self.raw)
        self.assertIn('memory: "1536Mi"', self.raw)

    def test_credentials_from_secret_not_plaintext(self):
        self.assertIn('secretRef:', self.raw)
        self.assertIn('name: oca-etl-secrets', self.raw)
        self.assertNotIn('name: DATABASE_URL', self.raw)
        self.assertNotIn('name: SFTP_PSWD', self.raw)

    def test_runtime_knobs_documented_in_env(self):
        for name in (
            'MODE',
            'GEOCODE_WORKERS',
            'CENSUS_BATCH_CHUNK_SIZE',
            'CSV_ROW_CHECK_CHUNK_SIZE',
            'S3_PREFIX',
            'DB_SCHEMA',
            'REPROCESS_GLOB',
            'FORCE_REPROCESS',
        ):
            self.assertIn(f'name: {name}', self.raw)

    def test_no_embedded_aws_keys_or_passwords(self):
        self.assertNotRegex(self.raw, r'AKIA[0-9A-Z]{16}')
        self.assertNotRegex(self.raw, r'postgresql://[^:]+:[^@]+@')


if __name__ == '__main__':
    unittest.main()
