"""Write-once file store for uploaded originals, generated packs and report workbooks (a directory per bucket)."""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

from . import config

BUCKETS = ("originals", "packs", "reports")


class StorageError(Exception):
    pass


def _path(bucket: str, key: str) -> Path:
    if bucket not in BUCKETS:
        raise StorageError(f"unknown bucket {bucket}")
    root = (config.settings.storage_root / bucket).resolve()
    p = (root / key).resolve()
    if root not in p.parents:
        raise StorageError(f"key escapes its bucket: {key!r}")
    return p


def put(bucket: str, key: str, data: bytes) -> None:
    p = _path(bucket, key)
    if p.exists():
        if hashlib.sha256(p.read_bytes()).digest() != hashlib.sha256(data).digest():
            raise StorageError(f"{bucket}/{key} is write-once and already holds different bytes")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{threading.get_ident()}")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    os.chmod(p, 0o400)


def get(bucket: str, key: str) -> bytes:
    p = _path(bucket, key)
    if not p.exists():
        raise StorageError(f"{bucket}/{key} not found")
    return p.read_bytes()
