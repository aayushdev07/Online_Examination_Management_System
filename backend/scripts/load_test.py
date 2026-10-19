"""Small, dependency-free load test for a running OEMS API.

    python scripts/load_test.py --users 10 --duration 20

Each virtual user logs in as faculty and repeatedly calls a mix of read
endpoints. Latencies are measured on the client side; the server-side
measurements appear on the Performance dashboard at the same time.
Run it only against a local/development instance.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import threading
import time
import urllib.error
import urllib.request

MIX = [
    ("GET", "/api/exams", 4),
    ("GET", "/api/results/performance", 2),
    ("GET", "/api/attempts?page_size=20", 2),
    ("GET", "/api/results?page_size=20", 2),
    ("GET", "/api/reports/subject_performance", 1),
    ("GET", "/api/health", 1),
]


def call(base: str, method: str, path: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        payload, status = exc.read(), exc.code
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, (time.perf_counter() - started) * 1000, str(exc).encode()
    return status, (time.perf_counter() - started) * 1000, payload


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--duration", type=float, default=20.0, help="seconds")
    parser.add_argument("--username", default="rdeshpande")
    parser.add_argument("--password", default="Password@123")
    args = parser.parse_args()

    status, _, body = call(args.base, "POST", "/api/auth/login", body={
        "username": args.username, "password": args.password, "account_type": "STAFF"})
    if status != 200:
        print(f"login failed ({status}): {body[:200]!r}")
        return 1
    token = json.loads(body)["access_token"]

    weighted = [(m, p) for m, p, w in MIX for _ in range(w)]
    results: list[tuple[str, int, float]] = []
    lock = threading.Lock()
    stop_at = time.perf_counter() + args.duration

    def worker(seed: int) -> None:
        rnd = random.Random(seed)
        while time.perf_counter() < stop_at:
            method, path = rnd.choice(weighted)
            code, ms, _ = call(args.base, method, path, token)
            with lock:
                results.append((path, code, ms))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.users)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - started

    latencies = [ms for _, _, ms in results]
    errors = [r for r in results if not 200 <= r[1] < 400]
    print(f"\nOEMS load test: {args.users} users x {args.duration:.0f}s against {args.base}")
    print(f"requests: {len(results)}  errors: {len(errors)}  throughput: {len(results) / elapsed:.1f} req/s")
    if latencies:
        print(f"latency ms  avg {sum(latencies) / len(latencies):.1f}  p50 {pct(latencies, 50):.1f}  "
              f"p95 {pct(latencies, 95):.1f}  p99 {pct(latencies, 99):.1f}  max {max(latencies):.1f}")
    print("\nper endpoint:")
    for path in sorted({p for p, _, _ in results}):
        vals = [ms for p, _, ms in results if p == path]
        print(f"  {path:38} n={len(vals):5}  p50 {pct(vals, 50):7.1f}  p95 {pct(vals, 95):7.1f}")
    if errors:
        print("\nfirst errors:", errors[:5])
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
