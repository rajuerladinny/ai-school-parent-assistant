"""Privacy-conscious request metrics without credentials or request payloads.

Counters are process-local diagnostics, not a replacement for centralized monitoring.
"""
import json
import logging
import threading
import time
from collections import Counter
from uuid import uuid4

from fastapi import APIRouter, Request

router = APIRouter()
_lock = threading.Lock()
_counts = Counter()
_logger = logging.getLogger('school.operations')


def record(method: str, status: int, elapsed_seconds: float, correlation_id: str | None = None) -> None:
    # Never collect URLs, query strings, user identifiers, authorization headers or bodies.
    status_class = f"{status // 100}xx"
    with _lock:
        _counts[(method, status_class)] += 1
    _logger.info(json.dumps({"event": "http_request", "method": method,
                             "status_class": status_class,
                             "latency_ms": round(max(0, elapsed_seconds) * 1000, 1),
                             "request_id": correlation_id}))


def snapshot() -> dict:
    with _lock:
        return {
            f"{method}:{status_class}": count
            for key, count in sorted(_counts.items())
            for method, status_class in ([key] if len(key) == 2 else
                                         [(f"auth:{key[1]}", key[2])])
        }


def auth_event(kind: str, outcome: str) -> None:
    """Emit bounded, identity-free authentication events for centralized log collection."""
    if kind not in ("parent", "staff") or outcome not in ("allowed", "throttled", "unavailable"):
        raise ValueError("Invalid authentication metric labels")
    with _lock:
        _counts[("auth", kind, outcome)] += 1
    _logger.info(json.dumps({"event": "auth_rate_limit", "realm": kind,
                             "outcome": outcome}))


def alert_candidates(counts: dict | None = None) -> list[dict]:
    """Evaluate local diagnostic counters; external aggregation must supply fleet totals."""
    counts = snapshot() if counts is None else counts
    rules = (("auth:parent:throttled", 10),
             ("auth:staff:throttled", 10),
             ("auth:parent:unavailable", 1),
             ("auth:staff:unavailable", 1))
    return [{"metric": metric, "count": counts.get(metric, 0), "threshold": threshold}
            for metric, threshold in rules if counts.get(metric, 0) >= threshold]


def request_id() -> str:
    # Generated server-side; do not trust a client-provided correlation identifier.
    return uuid4().hex
