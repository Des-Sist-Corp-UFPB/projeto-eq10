import http.client
import threading
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from src.diagnostics.readiness_server import (
    ApplicationDatabaseReadiness,
    create_server,
)


@contextmanager
def running_server(checker):
    server = create_server(host="127.0.0.1", port=0, readiness_check=checker)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(address, method="GET", path="/health"):
    connection = http.client.HTTPConnection(*address, timeout=2)
    connection.request(method, path)
    response = connection.getresponse()
    body = response.read()
    headers = dict(response.getheaders())
    connection.close()
    return response.status, headers, body


def test_get_health_success_returns_minimal_safe_json():
    with running_server(lambda: True) as address:
        status, headers, body = request(address)

    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-store"
    assert body == b'{"status":"healthy","database":"connected"}'


def test_get_health_database_failure_returns_503_without_details():
    def failing_check():
        raise RuntimeError(
            "postgresql://user:password@private-host/database SELECT usuarios"
        )

    with running_server(failing_check) as address:
        status, _, body = request(address)

    assert status == 503
    assert body == b'{"status":"unhealthy","database":"unavailable"}'
    for forbidden in (b"password", b"private-host", b"usuarios", b"SELECT"):
        assert forbidden not in body


def test_head_health_has_status_and_no_body():
    with running_server(lambda: True) as address:
        status, headers, body = request(address, method="HEAD")

    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert body == b""


def test_unknown_path_and_unsupported_method():
    with running_server(lambda: True) as address:
        missing_status, _, _ = request(address, path="/unknown?token=secret")
        method_status, _, method_body = request(address, method="POST")

    assert missing_status == 404
    assert method_status == 405
    assert method_body == b'{"status":"method_not_allowed"}'


def test_timeout_returns_503_safely():
    with running_server(lambda: (_ for _ in ()).throw(TimeoutError("secret"))) as address:
        status, _, body = request(address)

    assert status == 503
    assert b"secret" not in body


def test_probe_reuses_engine_and_short_cache_without_connection_leaks():
    engine = MagicMock()
    connection = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    clock_values = iter([0.0, 1.0, 6.0])
    engine_factory = MagicMock(return_value=engine)
    readiness = ApplicationDatabaseReadiness(
        engine_factory=engine_factory,
        cache_ttl_seconds=5,
        clock=lambda: next(clock_values),
    )

    assert readiness.check()
    assert readiness.check()
    assert readiness.check()

    engine_factory.assert_called_once_with()
    assert engine.connect.call_count == 2
    assert engine.connect.return_value.__exit__.call_count == 2


def test_analytical_failure_is_not_consulted_by_readiness():
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = MagicMock()
    readiness = ApplicationDatabaseReadiness(
        engine_factory=lambda: engine,
        cache_ttl_seconds=0,
    )

    with patch(
        "src.ai.read_only_datasus.get_readonly_engine",
        side_effect=AssertionError("analytical provider must not be called"),
    ):
        assert readiness.check()


def test_application_database_failure_is_not_ready():
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("connection refused secret")
    readiness = ApplicationDatabaseReadiness(
        engine_factory=lambda: engine,
        cache_ttl_seconds=0,
    )

    assert readiness.check() is False


def test_default_probe_uses_bounded_authoritative_auth_engine():
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = MagicMock()
    with patch(
        "src.diagnostics.readiness_server.get_auth_engine",
        return_value=engine,
    ) as get_engine:
        readiness = ApplicationDatabaseReadiness(cache_ttl_seconds=0)
        assert readiness.check()

    get_engine.assert_called_once_with(
        connect_timeout_seconds=5,
        pool_timeout_seconds=5,
    )
