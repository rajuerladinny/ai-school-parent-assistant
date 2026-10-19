"""Privacy-conscious request metrics without credentials or request payloads.

Counters are process-local diagnostics, not a replacement for centralized monitoring.
"""
import threading
import time
from collections import Counter
from uuid import uuid4

from fastapi import APIRouter, Request

router = APIRouter()
_lock = threading.Lock()
_counts = Counter()


def record(method: str, status: int, elapsed_seconds: float) -> None:
    # Never collect URLs, query strings, user identifiers, authorization headers or bodies.
    status_class = f"{status // 100}xx"
    with _lock:
        _counts[(method, status_class)] += 1


def snapshot() -> dict:
    with _lock:
        return {
            f"{method}:{status_class}": count
            for (method, status_class), count in sorted(_counts.items())
        }


def request_id() -> str:
    # Generated server-side; do not trust a client-provided correlation identifier.
    return uuid4().hex
