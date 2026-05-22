from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from polymarket_tracker.config.settings import ApiConfig

LOGGER = logging.getLogger(__name__)


class CircuitOpenError(RuntimeError):
    pass


@dataclass
class CircuitBreaker:
    failure_threshold: int
    reset_seconds: float
    failures: int = 0
    opened_at: float | None = None

    def before_request(self) -> None:
        if self.opened_at is None:
            return
        if time.time() - self.opened_at >= self.reset_seconds:
            self.failures = 0
            self.opened_at = None
            return
        raise CircuitOpenError("circuit breaker is open")

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.time()


class HttpClient:
    def __init__(self, config: ApiConfig) -> None:
        self.config = config
        self.breakers: dict[str, CircuitBreaker] = {}

    def get_json(self, base_url: str, path: str, params: dict[str, Any] | None = None) -> Any:
        url = _build_url(base_url, path, params)
        return self._request_json("GET", url)

    def _request_json(self, method: str, url: str) -> Any:
        breaker = self.breakers.setdefault(
            _origin(url),
            CircuitBreaker(self.config.circuit_breaker_failures, self.config.circuit_breaker_reset_seconds),
        )
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                breaker.before_request()
                request = urllib.request.Request(
                    url,
                    method=method,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": self.config.user_agent,
                    },
                )
                with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                    breaker.record_success()
                    if not body:
                        return None
                    return json.loads(body)
            except CircuitOpenError:
                raise
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429 or 500 <= exc.code < 600:
                    breaker.record_failure()
                    self._sleep(attempt)
                    continue
                breaker.record_failure()
                raise
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                breaker.record_failure()
                self._sleep(attempt)
        raise RuntimeError(f"HTTP request failed after retries: {url}: {last_error}") from last_error

    def _sleep(self, attempt: int) -> None:
        if attempt >= self.config.max_retries:
            return
        base = min(self.config.backoff_max_seconds, self.config.backoff_base_seconds * (2**attempt))
        jitter = base * self.config.jitter_ratio * random.random()
        time.sleep(base + jitter)


def _build_url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    base = base_url.rstrip("/")
    full_path = "/" + path.lstrip("/")
    query = ""
    if params:
        cleaned = {key: value for key, value in params.items() if value is not None}
        query = "?" + urllib.parse.urlencode(cleaned, doseq=True) if cleaned else ""
    return f"{base}{full_path}{query}"


def _origin(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"
