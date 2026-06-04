import hashlib
import json

from .etl_constants import OCA_TABLES

PROMOTION_SQL_FILE = 'promote_staging_to_main.sql'
PROMOTION_INDEX_SQL_FILE = 'ensure_promotion_indexes.sql'
PURGE_TOMBSTONED_CASES_SQL_FILE = 'purge_tombstoned_cases.sql'

# Tables promoted via promote_staging_to_main.sql (oca_metadata merged in-SQL).
PROMOTED_TABLES = [t for t in OCA_TABLES if t != 'oca_metadata']

ADDRESS_NATURAL_KEY_COLUMNS = [
    'indexnumberid', 'street1', 'street2', 'city', 'state', 'postalcode',
]


def ensure_promotion_indexes(db):
    """Create indexes used by scoped promotion deletes when staging tables exist."""
    db.execute_sql_file(PROMOTION_INDEX_SQL_FILE, commit=False)


def promotion_table_counts(db, tables=None):
    """Return row counts per main table (checksum hook for validation)."""
    tables = tables or OCA_TABLES
    counts = {}
    for table in tables:
        row = db.sql_fetch_one(f'SELECT COUNT(*)::bigint FROM {table}')
        counts[table] = int(row[0]) if row else 0
    return counts


def promotion_counts_checksum(counts):
    """Stable checksum string for comparing promotion snapshots."""
    payload = json.dumps(counts, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def promote_staging_to_main(db):
    """
    Promote all populated staging tables to main in one transaction.

    On failure, PostgreSQL rolls back deletes/inserts/metadata merge and staging
  drops so a retry can re-import or re-run promotion safely.
    """
    with db.transaction():
        ensure_promotion_indexes(db)
        db.execute_sql_file(PROMOTION_SQL_FILE, commit=False)

