"""Low-overhead timing and counters for parse -> DuckDB -> export -> CSV preprocess."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

# Major staging table families tracked in baseline reports.
STAGING_TABLE_FAMILIES = (
    'oca_index_staging',
    'oca_causes_staging',
    'oca_addresses_staging',
    'oca_parties_staging',
    'oca_events_staging',
    'oca_appearances_staging',
    'oca_motions_staging',
    'oca_decisions_staging',
    'oca_judgments_staging',
    'oca_warrants_staging',
    'oca_metadata_staging',
)


def metrics_enabled_from_env() -> bool:
    return os.environ.get('ETL_METRICS', '').strip().lower() in ('1', 'true', 'yes', 'on')


@dataclass
class EtlStageMetrics:
    """Collects stage timings and counters without altering ETL behavior."""

    enabled: bool = True
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    row_counts: dict[str, int] = field(default_factory=dict)
    export_bytes: dict[str, int] = field(default_factory=dict)
    preprocess_rows: dict[str, int] = field(default_factory=dict)

    @classmethod
    def disabled(cls) -> EtlStageMetrics:
        return cls(enabled=False)

    def increment(self, name: str, amount: int = 1) -> None:
        if not self.enabled:
            return
        self.counters[name] = self.counters.get(name, 0) + amount

    def set_counter(self, name: str, value: int) -> None:
        if not self.enabled:
            return
        self.counters[name] = value

    def record_stage(self, name: str, duration_sec: float, **details: Any) -> None:
        if not self.enabled:
            return
        entry = {'duration_sec': round(duration_sec, 6), **details}
        self.stages[name] = entry

    @contextmanager
    def stage(self, name: str, **details: Any) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            self.record_stage(name, time.perf_counter() - start, **details)

    def to_dict(self) -> dict[str, Any]:
        return {
            'enabled': self.enabled,
            'stages': self.stages,
            'counters': self.counters,
            'row_counts': self.row_counts,
            'export_bytes': self.export_bytes,
            'preprocess_rows': self.preprocess_rows,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
