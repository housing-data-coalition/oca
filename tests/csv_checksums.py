"""CSV checksum helpers for parse/export regression tests."""

from __future__ import annotations

import hashlib
import os


def md5_dir_csvs(pub_dir: str) -> dict[str, str]:
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
