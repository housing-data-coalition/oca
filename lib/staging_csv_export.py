"""DuckDB COPY export shaping for RDS-compatible staging CSVs."""

from __future__ import annotations

from dataclasses import dataclass, field

# Match Task 1 raw DuckDB COPY + Python preprocess CSV shape (unquoted empty fields).
DUCKDB_CSV_COPY_OPTIONS = "HEADER, DELIMITER ','"

_EMPTY_INT_MARKERS_SQL = "('', 'nan', 'NaN', 'None', '<NA>')"


@dataclass(frozen=True)
class StagingExportSpec:
    """Per-table transforms applied during DuckDB export (replaces CSV preprocess)."""

    drop_columns: frozenset[str] = field(default_factory=frozenset)
    array_columns: frozenset[str] = field(default_factory=frozenset)
    int_columns: frozenset[str] = field(default_factory=frozenset)


def postgres_array_brackets_sql(column_expr: str) -> str:
    """
    SQL expression matching ``replace_postgres_array_brackets`` in etl_csv.py.

  Converts DuckDB list literals ``[a,b]`` to PostgreSQL ``{a,b}`` while leaving
  JSON object arrays (inner ``{...}``) unchanged.
    """
    text = f"trim(cast({column_expr} AS VARCHAR))"
    inner = f"trim(substr({text}, 2, length({text}) - 2))"
    return (
        f"CASE WHEN {column_expr} IS NULL THEN NULL "
        f"WHEN NOT (starts_with({text}, '[') AND ends_with({text}, ']')) "
        f"THEN cast({column_expr} AS VARCHAR) "
        f"WHEN starts_with({inner}, '{{') AND ends_with({inner}, '}}') "
        f"THEN cast({column_expr} AS VARCHAR) "
        f"ELSE '{{' || substr({text}, 2, length({text}) - 2) || '}}' END"
    )


def nullable_int_csv_sql(column_expr: str) -> str:
    """
    SQL expression matching nullable integer CSV normalization in etl_csv.py.

    Python writes an empty CSV field (not ``""``); DuckDB COPY does the same when
    the cell is NULL rather than an empty string literal.
    """
    as_text = f"cast({column_expr} AS VARCHAR)"
    return (
        f"CASE WHEN {column_expr} IS NULL THEN NULL "
        f"WHEN {as_text} IN {_EMPTY_INT_MARKERS_SQL} THEN NULL "
        f"ELSE {as_text} END"
    )


def _export_column_sql(column_name: str, column_type: str, spec: StagingExportSpec) -> str | None:
    if column_name in spec.drop_columns:
        return None
    if column_name in spec.array_columns:
        return f"{postgres_array_brackets_sql(column_name)} AS {column_name}"
    if column_name in spec.int_columns:
        return f"{nullable_int_csv_sql(column_name)} AS {column_name}"
    if column_type.upper() in ('JSON',):
        return f"cast({column_name} AS VARCHAR) AS {column_name}"
    return column_name


STAGING_TABLE_EXPORT_SPECS: dict[str, StagingExportSpec] = {
    'oca_index_staging': StagingExportSpec(
        array_columns=frozenset({'specialtydesignationtypes'}),
    ),
    'oca_events_staging': StagingExportSpec(
        array_columns=frozenset({'filingpartiesroles'}),
    ),
    'oca_motions_staging': StagingExportSpec(
        array_columns=frozenset({'filingpartiesroles'}),
    ),
    'oca_judgments_staging': StagingExportSpec(
        array_columns=frozenset({'creditorsroles', 'debtorsroles'}),
        int_columns=frozenset({'amendedfromjudgmentsequence'}),
    ),
    'oca_warrants_staging': StagingExportSpec(
        array_columns=frozenset({
            'propertiesonwarrantcities',
            'propertiesonwarrantstates',
            'propertiesonwarrantpostalcodes',
        }),
        int_columns=frozenset({'executionstayeddays', 'issuancestayeddays'}),
    ),
    'oca_appearances_staging': StagingExportSpec(
        drop_columns=frozenset({'appearanceid'}),
        int_columns=frozenset({'motionsequence'}),
    ),
}

# Staging tables with no export-time transforms (no second-pass CSV rewrite).
STAGING_TABLES_PASSTHROUGH_EXPORT = frozenset({
    'oca_addresses_staging',
    'oca_causes_staging',
    'oca_decisions_staging',
    'oca_metadata_staging',
    'oca_parties_staging',
    'oca_appearance_outcomes_staging',
})


def staging_csv_needs_preprocess(filename: str) -> bool:
    """Return True when a staging CSV still requires the Python preprocess pass."""
    if not filename.endswith('.csv'):
        return False
    table_name = filename[:-4]
    if table_name in STAGING_TABLE_EXPORT_SPECS:
        return False
    if table_name in STAGING_TABLES_PASSTHROUGH_EXPORT:
        return False
    return True


def build_staging_copy_sql(table_name: str, csv_path: str, columns: list[tuple[str, str]]) -> str:
    """
    Build COPY SQL for a staging table.

    ``columns`` is a list of (name, type) from DESCRIBE.
    """
    spec = STAGING_TABLE_EXPORT_SPECS.get(table_name)
    options = DUCKDB_CSV_COPY_OPTIONS
    if spec is None:
        return f"COPY {table_name} TO '{csv_path}' ({options})"

    select_cols = []
    for name, col_type in columns:
        expr = _export_column_sql(name, col_type, spec)
        if expr is not None:
            select_cols.append(expr)
    select_sql = ', '.join(select_cols)
    return f"COPY (SELECT {select_sql} FROM {table_name}) TO '{csv_path}' ({options})"
