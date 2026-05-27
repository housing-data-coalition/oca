import json
import traceback
import uuid
from contextlib import contextmanager


class EtlRunManifest:
    @staticmethod
    def _escape(value):
        return str(value).replace("'", "''")

    def _literal(self, value):
        return f"'{self._escape(value)}'"

    def _json_literal(self, value):
        return f"'{self._escape(json.dumps(value))}'::jsonb"

    def __init__(self, db, schema_name, s3_prefix, mode, reprocess_glob, force_reprocess):
        self.db = db
        self.schema_name = schema_name or 'public'
        self.s3_prefix = s3_prefix or ''
        self.mode = mode
        self.reprocess_glob = reprocess_glob or ''
        self.force_reprocess = force_reprocess
        self.run_id = str(uuid.uuid4())
        self.lock_key = None
        self.lock_acquired = False

    def setup_tables(self):
        self.db.execute_sql_file('create_etl_manifest_tables.sql')

    def acquire_lock(self):
        row = self.db.sql_fetch_one(
            f"SELECT hashtext('oca_etl:' || {self._literal(self.schema_name)})::bigint"
        )
        self.lock_key = row[0]
        locked = self.db.sql_fetch_one(f"SELECT pg_try_advisory_lock({self.lock_key})")
        self.lock_acquired = bool(locked and locked[0])
        if not self.lock_acquired:
            raise RuntimeError(f"Another ETL run is already active for schema '{self.schema_name}'.")

    def release_lock(self):
        if self.lock_acquired and self.lock_key is not None:
            self.db.sql_fetch_one(f"SELECT pg_advisory_unlock({self.lock_key})")
            self.lock_acquired = False

    def create_run(self):
        payload = {
            "mode": self.mode,
            "schema_name": self.schema_name,
            "s3_prefix": self.s3_prefix,
            "reprocess_glob": self.reprocess_glob,
            "force_reprocess": self.force_reprocess,
        }
        self.db.sql(f"""
            INSERT INTO etl_runs (
                run_id, schema_name, s3_prefix, mode, reprocess_glob, force_reprocess, status, metadata, started_at
            ) VALUES (
                {self._literal(self.run_id)}, {self._literal(self.schema_name)}, {self._literal(self.s3_prefix)},
                {self._literal(self.mode)}, {self._literal(self.reprocess_glob)},
                {str(self.force_reprocess).upper()}, 'running', {self._json_literal(payload)}, NOW()
            )
        """)

    def mark_run_completed(self, selected_count, processed_count, skipped_count):
        self.db.sql(f"""
            UPDATE etl_runs
            SET status = 'completed',
                completed_at = NOW(),
                selected_file_count = {selected_count},
                processed_file_count = {processed_count},
                skipped_file_count = {skipped_count}
            WHERE run_id = {self._literal(self.run_id)}
        """)

    def mark_run_failed(self, exc):
        message = str(exc)
        details = {"traceback": traceback.format_exc()}
        self.db.sql(f"""
            UPDATE etl_runs
            SET status = 'failed',
                completed_at = NOW(),
                error_message = {self._literal(message)},
                error_details = {self._json_literal(details)}
            WHERE run_id = {self._literal(self.run_id)}
        """)

    def upsert_file(self, file_name, source, status, stage=None, details=None, error=None):
        stage_value = "NULL" if stage is None else self._literal(stage)
        details_value = self._json_literal(details or {})
        error_message = "NULL" if error is None else self._literal(str(error))
        error_details = "NULL" if error is None else self._json_literal({'traceback': traceback.format_exc()})
        completed_at = "NOW()" if status in ("completed", "failed", "skipped") else "NULL"
        started_at = "NOW()" if status in ("processing", "downloaded", "parsed", "promoted") else "NULL"
        self.db.sql(f"""
            INSERT INTO etl_files (
                run_id, file_name, source, status, stage, details, started_at, completed_at, error_message, error_details, updated_at
            ) VALUES (
                {self._literal(self.run_id)}, {self._literal(file_name)}, {self._literal(source)}, {self._literal(status)}, {stage_value},
                {details_value}, {started_at}, {completed_at}, {error_message}, {error_details}, NOW()
            )
            ON CONFLICT (run_id, file_name) DO UPDATE
            SET source = EXCLUDED.source,
                status = EXCLUDED.status,
                stage = EXCLUDED.stage,
                details = EXCLUDED.details,
                started_at = COALESCE(etl_files.started_at, EXCLUDED.started_at),
                completed_at = EXCLUDED.completed_at,
                error_message = EXCLUDED.error_message,
                error_details = EXCLUDED.error_details,
                updated_at = NOW()
        """)

    def upsert_step(self, step_name, status, details=None, error=None):
        details_value = self._json_literal(details or {})
        started_at = "NOW()" if status == "running" else "NULL"
        completed_at = "NOW()" if status in ("completed", "failed") else "NULL"
        error_message = "NULL" if error is None else self._literal(str(error))
        error_details = "NULL" if error is None else self._json_literal({'traceback': traceback.format_exc()})
        self.db.sql(f"""
            INSERT INTO etl_steps (
                run_id, step_name, status, started_at, completed_at, error_message, error_details, details, updated_at
            ) VALUES (
                {self._literal(self.run_id)}, {self._literal(step_name)}, {self._literal(status)}, {started_at}, {completed_at},
                {error_message}, {error_details}, {details_value}, NOW()
            )
            ON CONFLICT (run_id, step_name) DO UPDATE
            SET status = EXCLUDED.status,
                started_at = COALESCE(etl_steps.started_at, EXCLUDED.started_at),
                completed_at = EXCLUDED.completed_at,
                error_message = EXCLUDED.error_message,
                error_details = EXCLUDED.error_details,
                details = EXCLUDED.details,
                updated_at = NOW()
        """)


@contextmanager
def manifest_step(manifest, step_name, details=None):
    manifest.upsert_step(step_name, 'running', details=details)
    try:
        yield
        manifest.upsert_step(step_name, 'completed', details=details)
    except Exception as exc:
        manifest.upsert_step(step_name, 'failed', details=details, error=exc)
        raise


def completed_reprocess_files(db, reprocess_files):
    if not reprocess_files:
        return set()
    quoted_files = ",".join(["'" + f.replace("'", "''") + "'" for f in reprocess_files])
    rows = db.sql_fetch_all(f"""
        SELECT DISTINCT ef.file_name
        FROM etl_files ef
        JOIN etl_runs er ON er.run_id = ef.run_id
        WHERE ef.status = 'completed'
          AND er.status = 'completed'
          AND ef.file_name IN ({quoted_files})
    """)
    return {row[0] for row in rows}
