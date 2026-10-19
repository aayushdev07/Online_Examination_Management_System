"""In-process measurements of API requests and database queries.

Everything reported here is measured from real traffic since the process
started — nothing is simulated. Percentiles are only reported once enough
samples exist to make them meaningful.
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

MIN_SAMPLES = {"p50": 1, "p95": 20, "p99": 100}
EXCLUDED_PREFIXES = ("/api/metrics", "/api/db/metrics")  # dashboard polling would skew the numbers

_ws = re.compile(r"\s+")


def preview_sql(statement: str, limit: int = 300) -> str:
    text = _ws.sub(" ", statement or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def percentile(sorted_values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile on an already sorted list."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(pct / 100 * len(sorted_values)))
    return round(sorted_values[rank - 1], 3)


def latency_summary(values: list[float]) -> dict:
    ordered = sorted(values)
    n = len(ordered)
    summary: dict = {"samples": n, "avg_ms": round(sum(ordered) / n, 3) if n else None,
                     "min_ms": ordered[0] if n else None, "max_ms": ordered[-1] if n else None}
    for name, pct in (("p50", 50), ("p95", 95), ("p99", 99)):
        summary[f"{name}_ms"] = percentile(ordered, pct) if n >= MIN_SAMPLES[name] else None
    return summary


@dataclass
class _Request:
    ts: float
    method: str
    route: str
    status: int
    duration_ms: float
    request_id: str


@dataclass
class _Query:
    ts: float
    source: str
    duration_ms: float
    statement: str
    request_id: str
    ok: bool
    error: str | None = None


@dataclass
class MetricsStore:
    window: int = 10_000
    started_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: deque[_Request] = deque(maxlen=self.window)
        self.queries: deque[_Query] = deque(maxlen=self.window)
        self.slow_queries: deque[_Query] = deque(maxlen=50)
        self.failed_queries: deque[_Query] = deque(maxlen=50)
        self.total_requests = 0
        self.status_classes: Counter[str] = Counter()
        self.total_queries = 0
        self.total_query_failures = 0

    # -- recording ---------------------------------------------------------
    def record_request(self, method: str, route: str, status: int, duration_ms: float, request_id: str) -> None:
        if route.startswith(EXCLUDED_PREFIXES):
            return
        with self._lock:
            self.total_requests += 1
            self.status_classes[f"{status // 100}xx"] += 1
            self.requests.append(_Request(time.time(), method, route, status, duration_ms, request_id))

    def record_query(self, source: str, statement: str, duration_ms: float, request_id: str,
                     ok: bool = True, error: str | None = None, slow_threshold_ms: float = 200.0) -> None:
        query = _Query(time.time(), source, round(duration_ms, 3), preview_sql(statement), request_id, ok, error)
        with self._lock:
            self.total_queries += 1
            self.queries.append(query)
            if not ok:
                self.total_query_failures += 1
                self.failed_queries.appendleft(query)
            elif duration_ms >= slow_threshold_ms:
                self.slow_queries.appendleft(query)

    # -- reporting ----------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            requests = list(self.requests)
            queries = list(self.queries)
            slow = list(self.slow_queries)
            failed = list(self.failed_queries)
            totals = (self.total_requests, dict(self.status_classes), self.total_queries, self.total_query_failures)

        total_requests, classes, total_queries, total_failures = totals
        ok = sum(1 for r in requests if r.status < 400)
        client_err = sum(1 for r in requests if 400 <= r.status < 500)
        server_err = sum(1 for r in requests if r.status >= 500)

        by_route: dict[str, list[_Request]] = {}
        for r in requests:
            by_route.setdefault(f"{r.method} {r.route}", []).append(r)
        routes = []
        for key, items in by_route.items():
            summary = latency_summary([i.duration_ms for i in items])
            routes.append({"route": key, "count": len(items),
                           "errors": sum(1 for i in items if i.status >= 400), **summary})
        routes.sort(key=lambda item: item["count"], reverse=True)

        by_source = Counter(q.source for q in queries)
        recent = [{"ts": _iso(r.ts), "method": r.method, "route": r.route, "status": r.status,
                   "duration_ms": r.duration_ms, "request_id": r.request_id} for r in requests[-25:]][::-1]

        return {
            "measured_since": _iso(self.started_at),
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "window_size": self.window,
            "excluded_routes": list(EXCLUDED_PREFIXES),
            "api": {
                "total_requests": total_requests,
                "status_classes": classes,
                "window": {"requests": len(requests), "success": ok, "client_errors": client_err,
                           "server_errors": server_err,
                           "success_rate": round(100 * ok / len(requests), 2) if requests else None},
                "latency": latency_summary([r.duration_ms for r in requests]),
                "routes": routes[:20],
                "recent": recent,
            },
            "db": {
                "total_queries": total_queries,
                "total_failures": total_failures,
                "by_source": dict(by_source),
                "latency": latency_summary([q.duration_ms for q in queries if q.ok]),
                "slow_queries": [_query_dict(q) for q in slow[:20]],
                "failed_queries": [_query_dict(q) for q in failed[:20]],
            },
        }


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _query_dict(q: _Query) -> dict:
    return {"ts": _iso(q.ts), "source": q.source, "duration_ms": q.duration_ms,
            "statement": q.statement, "request_id": q.request_id, "error": q.error}


metrics = MetricsStore()
