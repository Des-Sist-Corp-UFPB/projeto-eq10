"""Servidor HTTP interno para readiness do banco principal da aplicacao."""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from src.auth.user_service import get_auth_engine
from src.diagnostics.health_service import HealthService, STATUS_OK

logger = logging.getLogger(__name__)

READINESS_HOST = "127.0.0.1"
READINESS_PORT = 8502
READINESS_TIMEOUT_SECONDS = 5
READINESS_CACHE_TTL_SECONDS = 5.0

HEALTHY_RESPONSE = {"status": "healthy", "database": "connected"}
UNHEALTHY_RESPONSE = {"status": "unhealthy", "database": "unavailable"}
NOT_FOUND_RESPONSE = {"status": "not_found"}
METHOD_NOT_ALLOWED_RESPONSE = {"status": "method_not_allowed"}


class ApplicationDatabaseReadiness:
    """Probe reutilizavel com cache curto e sem dependencia analitica."""

    def __init__(
        self,
        *,
        engine_factory: Callable[[], object] | None = None,
        cache_ttl_seconds: float = READINESS_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._engine_factory = engine_factory or (
            lambda: get_auth_engine(
                connect_timeout_seconds=READINESS_TIMEOUT_SECONDS,
                pool_timeout_seconds=READINESS_TIMEOUT_SECONDS,
            )
        )
        self._cache_ttl_seconds = max(0.0, cache_ttl_seconds)
        self._clock = clock
        self._engine: object | None = None
        self._cached_result: bool | None = None
        self._cached_at = 0.0
        self._lock = threading.Lock()

    def check(self) -> bool:
        now = self._clock()
        with self._lock:
            if (
                self._cached_result is not None
                and now - self._cached_at < self._cache_ttl_seconds
            ):
                return self._cached_result

            try:
                if self._engine is None:
                    self._engine = self._engine_factory()
                result = (
                    HealthService(auth_engine=self._engine)
                    .check_application_database_readiness()
                    .status
                    == STATUS_OK
                )
            except Exception:
                result = False

            self._cached_result = result
            self._cached_at = now
            return result


class ReadinessRequestHandler(BaseHTTPRequestHandler):
    readiness_check: Callable[[], bool] = staticmethod(lambda: False)

    def do_GET(self) -> None:
        self._handle_health(include_body=True)

    def do_HEAD(self) -> None:
        self._handle_health(include_body=False)

    def do_POST(self) -> None:
        self._write_json(405, METHOD_NOT_ALLOWED_RESPONSE, include_body=True)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST
    do_TRACE = do_POST
    do_CONNECT = do_POST

    def _handle_health(self, *, include_body: bool) -> None:
        if self.path != "/health":
            self._write_json(404, NOT_FOUND_RESPONSE, include_body=include_body)
            return
        try:
            healthy = bool(self.readiness_check())
        except Exception:
            healthy = False
        self._write_json(
            200 if healthy else 503,
            HEALTHY_RESPONSE if healthy else UNHEALTHY_RESPONSE,
            include_body=include_body,
        )

    def _write_json(
        self,
        status_code: int,
        payload: dict[str, str],
        *,
        include_body: bool,
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        # Access logs do endpoint publico nao precisam incluir valores da URL.
        return


def create_server(
    *,
    host: str = READINESS_HOST,
    port: int = READINESS_PORT,
    readiness_check: Callable[[], bool] | None = None,
) -> ThreadingHTTPServer:
    checker = readiness_check or ApplicationDatabaseReadiness().check

    class ConfiguredReadinessHandler(ReadinessRequestHandler):
        pass

    ConfiguredReadinessHandler.readiness_check = staticmethod(checker)
    return ThreadingHTTPServer((host, port), ConfiguredReadinessHandler)


def main() -> None:
    server = create_server()
    logger.info(
        "Readiness server started | address=loopback | port=%s",
        READINESS_PORT,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
