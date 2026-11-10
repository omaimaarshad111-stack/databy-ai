from threading import Lock
import time


class AuthRateLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: dict[tuple[str, str], tuple[float, int]] = {}
        self._next_cleanup = 0.0
        self._max_clients = 10_000

    def check(
        self,
        client: str,
        endpoint: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> int | None:
        now = time.monotonic()
        key = (client, endpoint)
        with self._lock:
            if now >= self._next_cleanup:
                cutoff = now - window_seconds
                self._requests = {
                    item_key: value
                    for item_key, value in self._requests.items()
                    if value[0] > cutoff
                }
                self._next_cleanup = now + min(window_seconds, 60)

            bucket = self._requests.get(key)
            if bucket is None:
                if len(self._requests) >= self._max_clients:
                    return window_seconds
                self._requests[key] = (now, 1)
                return None

            started_at, count = bucket
            if now - started_at >= window_seconds:
                self._requests[key] = (now, 1)
                return None
            if count >= limit:
                return max(1, int(started_at + window_seconds - now + 0.999))
            self._requests[key] = (started_at, count + 1)
            return None

    def clear(self) -> None:
        with self._lock:
            self._requests.clear()
            self._next_cleanup = 0.0


auth_rate_limiter = AuthRateLimiter()
