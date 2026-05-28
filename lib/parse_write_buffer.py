"""Buffered DuckDB staging writes with explicit transaction windows for parse hot paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .duckdb_database import DuckDB
    from .etl_metrics import EtlStageMetrics


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'y', 'on')


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    return max(1, int(raw))


@dataclass(frozen=True)
class ParseWriteConfig:
    """Runtime knobs for parser-to-DuckDB batching (safe production defaults)."""

    enabled: bool = True
    batch_size: int = 128
    flush_every_n_cases: int = 16

    @classmethod
    def from_env(cls) -> ParseWriteConfig:
        return cls(
            enabled=_env_bool('PARSE_WRITE_BATCH_ENABLED', True),
            batch_size=_env_int('PARSE_WRITE_BATCH_SIZE', 128),
            flush_every_n_cases=_env_int('PARSE_WRITE_FLUSH_EVERY_N_CASES', 16),
        )

    @classmethod
    def legacy(cls) -> ParseWriteConfig:
        """Per-row flush semantics (batching disabled)."""
        return cls(enabled=False, batch_size=1, flush_every_n_cases=1)


class StagingWriteBuffer:
    """
    Buffers DELETE + INSERT statements and flushes in transaction windows.

    Flush order preserves per-case child replacement: all queued DELETEs run
    before any queued INSERTs in the same transaction.
    """

    def __init__(self, db: DuckDB, config: ParseWriteConfig, metrics: EtlStageMetrics | None = None):
        self.db = db
        self.config = config
        self.metrics = metrics
        self._deletes: list[tuple[str, tuple | None]] = []
        self._inserts: dict[str, list[tuple | None]] = {}
        self._cases_in_window = 0

    def _pending_insert_count(self) -> int:
        return sum(len(rows) for rows in self._inserts.values())

    def queue_delete(self, sql: str, params: tuple | None) -> None:
        self._deletes.append((sql, params))

    def queue_insert(self, sql: str, params: tuple | None) -> None:
        self._inserts.setdefault(sql, []).append(params)
        if self._pending_insert_count() >= self.config.batch_size:
            self.flush()

    def on_case_complete(self) -> None:
        self._cases_in_window += 1
        if self._cases_in_window >= self.config.flush_every_n_cases:
            self.flush()

    def flush(self) -> None:
        if not self._deletes and not self._inserts:
            self._cases_in_window = 0
            return

        delete_count = len(self._deletes)
        insert_count = self._pending_insert_count()

        with self.db.transaction():
            for sql, params in self._deletes:
                self.db._execute_unlocked(sql, params)
            for sql, params_list in self._inserts.items():
                if not params_list:
                    continue
                if len(params_list) == 1:
                    self.db._execute_unlocked(sql, params_list[0])
                else:
                    self.db._executemany_unlocked(sql, params_list)

        if self.metrics and self.metrics.enabled:
            self.metrics.increment('parse_write_flushes', 1)
            self.metrics.increment('parse_write_buffered_deletes', delete_count)
            self.metrics.increment('parse_write_buffered_inserts', insert_count)

        self._deletes.clear()
        self._inserts.clear()
        self._cases_in_window = 0


def attach_write_buffer(db: DuckDB, metrics: EtlStageMetrics | None = None) -> StagingWriteBuffer | None:
    config = ParseWriteConfig.from_env()
    if not config.enabled:
        return None
    buffer = StagingWriteBuffer(db, config, metrics=metrics)
    db.write_buffer = buffer
    return buffer


def staging_execute(db: DuckDB, sql: str, params: tuple | None = None) -> Any:
    """Route a staging write through the optional per-connection write buffer."""
    buffer = getattr(db, 'write_buffer', None)
    if buffer is None:
        return db.execute(sql, params)
    sql_upper = sql.lstrip().upper()
    if sql_upper.startswith('DELETE'):
        buffer.queue_delete(sql, params)
        return None
    buffer.queue_insert(sql, params)
    return None


def flush_write_buffer(db: DuckDB) -> None:
    buffer = getattr(db, 'write_buffer', None)
    if buffer is not None:
        buffer.flush()
