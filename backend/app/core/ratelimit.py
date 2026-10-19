"""Small in-memory sliding-window rate limiter (single-process deployment)."""

import threading
import time
from collections import defaultdict, deque

from app.core.errors import ApiError


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = max(1, int(self.window - (now - hits[0])))
                raise ApiError(429, "rate_limited",
                               f"Too many requests: limit is {self.limit} per {int(self.window)} s. "
                               f"Retry in about {retry} s.")
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
