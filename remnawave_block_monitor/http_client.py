from __future__ import annotations

import json
import random
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ExternalServiceError(RuntimeError):
    pass


class RateLimiter:
    def __init__(
        self,
        delay: float,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.delay = delay
        self.clock = clock
        self.sleeper = sleeper
        self._next_allowed = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self.clock()
            wait_for = max(0.0, self._next_allowed - now)
            if wait_for:
                self.sleeper(wait_for)
                now = self.clock()
            self._next_allowed = now + self.delay


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


class JsonHttpClient:
    def __init__(self, service_name: str, attempts: int = 3, limiter: RateLimiter | None = None):
        self.service_name = service_name
        self.attempts = attempts
        self.limiter = limiter

    def request(
        self,
        url: str,
        timeout: float,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "Remnawave-Block-Monitor/1.0 (+https://github.com/VoskovschukDM/remnawave-block-monitor)",
            **(headers or {}),
        }
        last_reason = "request failed"
        for attempt in range(1, self.attempts + 1):
            if self.limiter:
                self.limiter.wait()
            try:
                request = Request(url, data=data, headers=request_headers, method=method)
                with urlopen(request, timeout=timeout) as response:
                    raw = response.read(5 * 1024 * 1024 + 1)
                if len(raw) > 5 * 1024 * 1024:
                    raise ExternalServiceError(f"{self.service_name}: response body is too large")
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    last_reason = "invalid JSON response"
                    if attempt == self.attempts:
                        raise ExternalServiceError(f"{self.service_name}: {last_reason}") from exc
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code <= 599
                last_reason = f"HTTP {exc.code}"
                if not retryable or attempt == self.attempts:
                    raise ExternalServiceError(f"{self.service_name}: {last_reason}") from exc
                delay = _retry_after(exc.headers.get("Retry-After") if exc.headers else None)
                time.sleep(min(300.0, delay if delay is not None else 2 ** (attempt - 1) + random.random()))
            except (URLError, TimeoutError, OSError) as exc:
                last_reason = "network, DNS, or timeout error"
                if attempt == self.attempts:
                    raise ExternalServiceError(f"{self.service_name}: {last_reason}") from exc
                time.sleep(2 ** (attempt - 1) + random.random())
            except ValueError as exc:
                raise ExternalServiceError(f"{self.service_name}: invalid request configuration") from exc
        raise ExternalServiceError(f"{self.service_name}: {last_reason}")
