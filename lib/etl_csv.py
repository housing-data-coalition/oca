"""Constant-memory CSV preprocessing for DuckDB staging exports."""

import csv
import os
import time

from .staging_csv_export import staging_csv_needs_preprocess

_APPEARANCES_PREFIX = 'oca_appearances_staging'
_JUDGMENTS_PREFIX = 'oca_judgments_staging'
_WARRANTS_PREFIX = 'oca_warrants_staging'

_EMPTY_INT_MARKERS = frozenset({'', 'nan', 'NaN', 'None', '<NA>'})


def replace_postgres_array_brackets(text):
    """
    Convert DuckDB-style array literals ``[a,b]`` to PostgreSQL ``{a,b}``.

    JSON object arrays (inner ``{...}``) are left unchanged.
    """
    if not text or not isinstance(text, str):
        return text
    stripped = text.strip()
    if not (stripped.startswith('[') and stripped.endswith(']')):
        return text
    inner = stripped[1:-1].strip()
    if inner.startswith('{') and inner.endswith('}'):
        return text
    return '{' + stripped[1:-1] + '}'


def _normalize_int_cell(value):
    if value is None:
        return ''
    if isinstance(value, str) and value.strip() in _EMPTY_INT_MARKERS:
        return ''
    return value


def _preprocess_row(filename, fieldnames, int_columns, row):
    out = {}
    for col in fieldnames:
        value = row.get(col, '')
        if col in int_columns:
            out[col] = _normalize_int_cell(value)
        elif isinstance(value, str):
            out[col] = replace_postgres_array_brackets(value)
        else:
            out[col] = value
    return out


def _file_preprocess_rules(filename):
    drop_columns = set()
    int_columns = set()
    if filename.startswith(_APPEARANCES_PREFIX):
        drop_columns.add('appearanceid')
        int_columns.add('motionsequence')
    elif filename.startswith(_JUDGMENTS_PREFIX):
        int_columns.add('amendedfromjudgmentsequence')
    elif filename.startswith(_WARRANTS_PREFIX):
        int_columns.update(('executionstayeddays', 'issuancestayeddays'))
    return drop_columns, int_columns


def preprocess_csv_file(file_path, chunk_size=1000, metrics=None):
    """
    Rewrite one staging CSV in place using bounded memory.

    ``chunk_size`` controls how many rows are buffered before writing; it does
    not load the full file into a DataFrame.
    """
    filename = os.path.basename(file_path)
    if not filename.endswith('.csv'):
        return 0

    drop_columns, int_columns = _file_preprocess_rules(filename)
    tmp_path = f'{file_path}.tmp'
    rows_touched = 0
    file_start = time.perf_counter()

    with open(file_path, newline='', encoding='utf-8') as infile, open(
        tmp_path, 'w', newline='', encoding='utf-8'
    ) as outfile:
        reader = csv.DictReader(infile)
        if not reader.fieldnames:
            os.remove(tmp_path)
            return 0

        fieldnames = [name for name in reader.fieldnames if name not in drop_columns]
        writer = csv.DictWriter(outfile, fieldnames=fieldnames, lineterminator='\n')
        writer.writeheader()

        batch = []
        for row in reader:
            batch.append(_preprocess_row(filename, fieldnames, int_columns, row))
            rows_touched += 1
            if len(batch) >= chunk_size:
                writer.writerows(batch)
                batch.clear()
        if batch:
            writer.writerows(batch)

    os.replace(tmp_path, file_path)

    if metrics is not None and metrics.enabled:
        metrics.preprocess_rows[filename] = rows_touched
        metrics.increment('preprocess_csv_files', 1)
        per_file = metrics.stages.setdefault('csv_preprocess_per_file', {})
        per_file[filename] = round(time.perf_counter() - file_start, 6)

    return rows_touched


def preprocess_staging_csv_dir(target_dir, chunk_size=1000, metrics=None):
    preprocess_start = time.perf_counter()
    total_rows = 0
    for filename in sorted(os.listdir(target_dir)):
        if not filename.endswith('.csv'):
            continue
        if not staging_csv_needs_preprocess(filename):
            if metrics is not None and metrics.enabled:
                metrics.preprocess_rows[filename] = 0
                metrics.increment('preprocess_csv_files_skipped', 1)
            continue
        total_rows += preprocess_csv_file(
            os.path.join(target_dir, filename),
            chunk_size=chunk_size,
            metrics=metrics,
        )
    if metrics is not None and metrics.enabled:
        metrics.set_counter('preprocess_rows_total', total_rows)
        metrics.record_stage(
            'csv_preprocess',
            time.perf_counter() - preprocess_start,
            files_processed=metrics.counters.get('preprocess_csv_files', 0),
            rows_touched=total_rows,
        )
