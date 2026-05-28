"""Repeatable benchmark harness for parse -> DuckDB -> export -> CSV preprocess."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
import zipfile
from typing import Any

from .benchmark_fixtures import SAMPLE_PROFILES, materialize_benchmark_samples
from .duckdb_database import DuckDB, fetch_staging_row_counts
from .etl_metrics import EtlStageMetrics, STAGING_TABLE_FAMILIES
from .etl_stages import export_staging_to_csv, parse_xml_to_staging


def _checksum_pub_dir(pub_dir: str) -> dict[str, str]:
    """MD5 hex digest per CSV in pub_dir (stable parity fingerprint)."""
    digests = {}
    for name in sorted(os.listdir(pub_dir)):
        if not name.endswith('.csv'):
            continue
        path = os.path.join(pub_dir, name)
        h = hashlib.md5()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        digests[name] = h.hexdigest()
    return digests


def _row_count_fingerprint(row_counts: dict[str, int]) -> str:
    parts = [f'{t}:{row_counts.get(t, 0)}' for t in STAGING_TABLE_FAMILIES]
    return hashlib.md5('|'.join(parts).encode()).hexdigest()


def run_parse_export_preprocess(
    priv_dir: str,
    *,
    metrics: EtlStageMetrics | None = None,
    csv_preprocess_chunk_size: int = 1000,
    parse_num_threads: int = 1,
) -> tuple[EtlStageMetrics, dict[str, str], dict[str, int]]:
    """
    Run parse -> export -> preprocess on zips in priv_dir (no upload).

    Returns (metrics, csv_checksums, staging_row_counts).
    """
    metrics = metrics or EtlStageMetrics()
    staging_path = os.path.join(priv_dir, 'staging.duckdb')
    pub_dir = os.path.join(priv_dir, 'public')
    os.makedirs(pub_dir, exist_ok=True)

    if os.path.exists(staging_path):
        os.remove(staging_path)

    staging_db = DuckDB(staging_path, metrics=metrics)

    class _NoopManifest:
        def upsert_step(self, *args, **kwargs):
            pass

        def upsert_file(self, *args, **kwargs):
            pass

    try:
        with metrics.stage('parse_xml_total'):
            parse_xml_to_staging(
                _NoopManifest(),
                staging_db,
                priv_dir,
                metrics=metrics,
                parse_num_threads=parse_num_threads,
            )

        metrics.row_counts.update(fetch_staging_row_counts(staging_db))

        export_staging_to_csv(
            staging_db,
            pub_dir,
            metrics=metrics,
            csv_preprocess_chunk_size=csv_preprocess_chunk_size,
            upload=False,
        )

        checksums = _checksum_pub_dir(pub_dir)
        return metrics, checksums, dict(metrics.row_counts)
    finally:
        staging_db.close()


def run_benchmark_profile(
    profile_name: str,
    zip_path: str,
    *,
    iterations: int = 2,
    csv_preprocess_chunk_size: int = 1000,
) -> dict[str, Any]:
    """Run a single sample profile multiple times; return aggregated results."""
    spec = SAMPLE_PROFILES[profile_name]
    runs = []
    reference_checksums = None
    reference_row_fingerprint = None

    for run_idx in range(iterations):
        with tempfile.TemporaryDirectory(prefix=f'oca-bench-{profile_name}-') as tmp:
            priv_dir = os.path.join(tmp, 'private')
            os.makedirs(priv_dir, exist_ok=True)
            shutil.copy2(zip_path, os.path.join(priv_dir, os.path.basename(zip_path)))

            metrics = EtlStageMetrics()
            t0 = time.perf_counter()
            metrics, checksums, row_counts = run_parse_export_preprocess(
                priv_dir,
                metrics=metrics,
                csv_preprocess_chunk_size=csv_preprocess_chunk_size,
            )
            wall_sec = time.perf_counter() - t0
            row_fp = _row_count_fingerprint(row_counts)

            if reference_checksums is None:
                reference_checksums = checksums
                reference_row_fingerprint = row_fp
            parity_ok = (
                checksums == reference_checksums
                and row_fp == reference_row_fingerprint
            )

            runs.append({
                'run': run_idx + 1,
                'wall_sec': round(wall_sec, 6),
                'metrics': metrics.to_dict(),
                'csv_checksums': checksums,
                'row_count_fingerprint': row_fp,
                'parity_with_run_1': parity_ok if run_idx > 0 else True,
            })

    durations = [r['wall_sec'] for r in runs]
    parse_durations = [
        r['metrics']['stages'].get('parse_xml_total', {}).get('duration_sec', 0)
        for r in runs
    ]
    export_durations = [
        r['metrics']['stages'].get('duckdb_export', {}).get('duration_sec', 0)
        for r in runs
    ]
    preprocess_durations = [
        r['metrics']['stages'].get('csv_preprocess', {}).get('duration_sec', 0)
        for r in runs
    ]

    def _variance_pct(values: list[float]) -> float | None:
        if len(values) < 2 or not values[0]:
            return None
        return round(abs(values[1] - values[0]) / values[0] * 100, 2)

    return {
        'profile': profile_name,
        'description': spec['description'],
        'case_count': spec['case_count'],
        'zip_path': zip_path,
        'iterations': iterations,
        'runs': runs,
        'summary': {
            'wall_sec': {'min': min(durations), 'max': max(durations), 'variance_pct': _variance_pct(durations)},
            'parse_sec': {'min': min(parse_durations), 'max': max(parse_durations), 'variance_pct': _variance_pct(parse_durations)},
            'export_sec': {'min': min(export_durations), 'max': max(export_durations), 'variance_pct': _variance_pct(export_durations)},
            'preprocess_sec': {'min': min(preprocess_durations), 'max': max(preprocess_durations), 'variance_pct': _variance_pct(preprocess_durations)},
            'row_counts_run_1': runs[0]['metrics']['row_counts'],
            'csv_checksums_run_1': runs[0]['csv_checksums'],
            'all_runs_parity_ok': all(r['parity_with_run_1'] for r in runs),
        },
    }


def run_full_baseline(
    *,
    fixtures_dir: str | None = None,
    output_dir: str,
    profiles: list[str] | None = None,
    iterations: int = 2,
    task_label: str = 'task1_baseline',
    json_filename: str | None = None,
) -> dict[str, Any]:
    """Materialize fixtures (if needed), run all profiles, write JSON + markdown report."""
    import json
    from datetime import datetime, timezone

    os.makedirs(output_dir, exist_ok=True)
    if fixtures_dir is None:
        fixtures_dir = os.path.join(output_dir, 'fixtures')
    zip_paths = materialize_benchmark_samples(fixtures_dir, profiles=profiles)

    results = []
    for profile_name, zip_path in zip_paths.items():
        results.append(
            run_benchmark_profile(
                profile_name,
                zip_path,
                iterations=iterations,
            )
        )

    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'option': 'A',
        'task': task_label,
        'profiles': results,
    }

    json_name = json_filename or f'{task_label}_metrics.json'
    json_path = os.path.join(output_dir, json_name)
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    md_name = json_name.replace('.json', '.md')
    md_path = os.path.join(output_dir, md_name)
    _write_markdown_report(md_path, report, title=task_label.replace('_', ' ').title())

    report['artifacts'] = {'json': json_path, 'markdown': md_path}
    return report


def _write_markdown_report(path: str, report: dict[str, Any], *, title: str = 'Task 1 baseline metrics (Option A)') -> None:
    lines = [
        f'# {title} (Option A)',
        '',
        f"Generated: {report['generated_at']}",
        '',
    ]
    for profile in report['profiles']:
        s = profile['summary']
        lines.extend([
            f"## {profile['profile']}",
            '',
            profile['description'],
            '',
            f"- Cases in fixture: {profile['case_count']}",
            f"- Iterations: {profile['iterations']}",
            f"- Run parity (checksums + row counts): **{s['all_runs_parity_ok']}**",
            '',
            '| Stage | Run 1 (s) | Run 2 (s) | Variance % |',
            '|-------|-----------|-----------|------------|',
        ])
        runs = profile['runs']
        for stage_key, label in (
            ('wall_sec', 'Total wall'),
            ('parse_sec', 'Parse'),
            ('export_sec', 'DuckDB export'),
            ('preprocess_sec', 'CSV preprocess'),
        ):
            v = s[stage_key]
            r1 = runs[0]['wall_sec'] if stage_key == 'wall_sec' else runs[0]['metrics']['stages'].get(
                {'parse_sec': 'parse_xml_total', 'export_sec': 'duckdb_export', 'preprocess_sec': 'csv_preprocess'}[stage_key],
                {},
            ).get('duration_sec', 0)
            r2 = runs[1]['wall_sec'] if stage_key == 'wall_sec' else runs[1]['metrics']['stages'].get(
                {'parse_sec': 'parse_xml_total', 'export_sec': 'duckdb_export', 'preprocess_sec': 'csv_preprocess'}[stage_key],
                {},
            ).get('duration_sec', 0)
            lines.append(f"| {label} | {r1:.3f} | {r2:.3f} | {v.get('variance_pct', 'n/a')} |")

        lines.extend(['', '### Row counts (run 1)', '', '```',])
        for table, count in sorted(s['row_counts_run_1'].items()):
            lines.append(f'{table}: {count}')
        lines.extend(['```', '', '### CSV checksums (run 1)', '', '```'])
        for name, digest in sorted(s['csv_checksums_run_1'].items()):
            lines.append(f'{name}: {digest}')
        lines.extend(['```', ''])

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main(argv: list[str] | None = None) -> int:
    import argparse

    default_artifacts = os.path.join(
        os.path.dirname(__file__),
        '..',
        '..',
        'justfix',
        'repos',
        'cursor-workspaces',
        'oca-etl',
        '.cursor',
        'plans',
        'artifacts',
    )
    parser = argparse.ArgumentParser(description='OCA parse pipeline baseline benchmark')
    parser.add_argument(
        '--output-dir',
        default=os.environ.get(
            'OCA_BENCHMARK_ARTIFACTS_DIR',
            '/Users/maxwell/justfix/repos/cursor-workspaces/oca-etl/.cursor/plans/artifacts',
        ),
        help='Directory for JSON/markdown reports and fixtures',
    )
    parser.add_argument('--profiles', nargs='+', choices=list(SAMPLE_PROFILES.keys()), default=None)
    parser.add_argument('--iterations', type=int, default=2)
    parser.add_argument('--fixtures-dir', default=None)
    parser.add_argument(
        '--task-label',
        default=os.environ.get('OCA_BENCHMARK_TASK', 'task1_baseline'),
        help='Report task label (e.g. task2_batched_writes)',
    )
    parser.add_argument(
        '--json-filename',
        default=None,
        help='Override JSON output filename (default: <task-label>_metrics.json)',
    )
    args = parser.parse_args(argv)

    run_full_baseline(
        fixtures_dir=args.fixtures_dir,
        output_dir=os.path.abspath(args.output_dir),
        profiles=args.profiles,
        iterations=args.iterations,
        task_label=args.task_label,
        json_filename=args.json_filename,
    )
    print(f"Wrote baseline artifacts to {os.path.abspath(args.output_dir)}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
