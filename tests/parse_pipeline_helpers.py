"""Test helpers for parse -> DuckDB -> export without the evaluation harness."""

from __future__ import annotations

import os

from lib.duckdb_database import DuckDB, fetch_staging_row_counts
from lib.etl_stages import export_staging_to_csv, parse_xml_to_staging

from csv_checksums import md5_dir_csvs


class _NoopManifest:
    def upsert_step(self, *args, **kwargs):
        pass

    def upsert_file(self, *args, **kwargs):
        pass


def run_parse_export_in_dir(
    priv_dir: str,
    *,
    parse_num_threads: int = 1,
) -> tuple[dict[str, int], dict[str, str]]:
    """
    Run parse -> export -> preprocess on zips in priv_dir (no upload).

    Returns (staging_row_counts, csv_checksums).
    """
    staging_path = os.path.join(priv_dir, 'staging.duckdb')
    pub_dir = os.path.join(priv_dir, 'public')
    os.makedirs(pub_dir, exist_ok=True)

    if os.path.exists(staging_path):
        os.remove(staging_path)

    staging_db = DuckDB(staging_path)
    try:
        parse_xml_to_staging(
            _NoopManifest(),
            staging_db,
            priv_dir,
            parse_num_threads=parse_num_threads,
        )
        row_counts = fetch_staging_row_counts(staging_db)
        export_staging_to_csv(staging_db, pub_dir, upload=False)
        return row_counts, md5_dir_csvs(pub_dir)
    finally:
        staging_db.close()
