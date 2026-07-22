"""Bounded post-deploy health check for the Streamlit chat service.

The script intentionally prints only status codes and exception categories. It
does not print environment variables, response bodies, headers, or credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import sys
import time
from typing import Callable, TextIO
from urllib.parse import urlsplit, urlunsplit
import urllib.request


DEFAULT_HEALTH_URL = "https://eq10.dsc.rodrigor.com/ping"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_INTERVAL_SECONDS = 5.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class HealthAttempt:
    ok: bool
    status_code: int | None = None
    error_type: str | None = None


def _positive_float_from_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if not raw_value:
        return default

    try:
        value = float(raw_value)
    except ValueError:
        return default

    return value if value > 0 else default


def _health_url_from_env() -> str:
    configured_url = (os.getenv("APP_HEALTH_URL") or "").strip()
    return configured_url or DEFAULT_HEALTH_URL


def safe_url_label(url: str) -> str:
    """Return a URL label without userinfo, query string, or fragment."""

    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"

    return urlunsplit((parsed.scheme, host, parsed.path or "/", "", ""))


def validate_health_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("health_url_invalid")


def check_health_once(
    url: str,
    *,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    opener: Callable[..., object] | None = None,
) -> HealthAttempt:
    open_url = opener or urllib.request.urlopen

    try:
        with open_url(url, timeout=request_timeout_seconds) as response:
            raw_status = getattr(response, "status", None)
            if raw_status is None:
                raw_status = response.getcode()
            status_code = int(raw_status)
    except Exception as exc:  # noqa: BLE001 - category-only diagnostics by design.
        return HealthAttempt(ok=False, error_type=type(exc).__name__)

    return HealthAttempt(ok=200 <= status_code < 300, status_code=status_code)


def wait_for_health(
    url: str,
    *,
    timeout_seconds: float,
    interval_seconds: float,
    request_timeout_seconds: float,
    opener: Callable[..., object] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    stream: TextIO = sys.stdout,
) -> bool:
    deadline = now() + timeout_seconds
    attempt = 0

    while True:
        attempt += 1
        result = check_health_once(
            url,
            request_timeout_seconds=request_timeout_seconds,
            opener=opener,
        )

        if result.ok:
            print(
                f"Application health endpoint responded with HTTP {result.status_code}.",
                file=stream,
            )
            return True

        detail = (
            f"status={result.status_code}"
            if result.status_code is not None
            else f"type={result.error_type}"
        )
        print(
            f"Waiting for application health... attempt={attempt} | {detail}",
            file=stream,
        )

        remaining = deadline - now()
        if remaining <= 0:
            break

        sleeper(min(interval_seconds, remaining))

    print("Application did not become healthy before the deploy timeout.", file=stream)
    return False


def main() -> int:
    url = _health_url_from_env()
    label = safe_url_label(url)

    try:
        validate_health_url(url)
    except ValueError:
        print(f"Invalid application health URL: {label}", file=sys.stderr)
        return 2

    timeout_seconds = _positive_float_from_env(
        "DEPLOY_HEALTH_TIMEOUT_SECONDS",
        DEFAULT_TIMEOUT_SECONDS,
    )
    interval_seconds = _positive_float_from_env(
        "DEPLOY_HEALTH_INTERVAL_SECONDS",
        DEFAULT_INTERVAL_SECONDS,
    )
    request_timeout_seconds = _positive_float_from_env(
        "DEPLOY_HEALTH_REQUEST_TIMEOUT_SECONDS",
        DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )

    print(f"Checking application health at {label}.")
    is_healthy = wait_for_health(
        url,
        timeout_seconds=timeout_seconds,
        interval_seconds=interval_seconds,
        request_timeout_seconds=request_timeout_seconds,
    )
    return 0 if is_healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
