import json
import unittest
from unittest.mock import MagicMock, patch

from scripts import container_liveness


class _SocketContext:
    def __init__(self, response: bytes):
        self._chunks = [response, b""]
        self.sent = b""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, value):
        self.sent = value

    def recv(self, _size):
        return self._chunks.pop(0)


class TestContainerLiveness(unittest.TestCase):
    @patch.object(container_liveness.socket, "create_connection")
    def test_accepts_exact_ping_response(self, create_connection):
        sock = _SocketContext(
            b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n'
            + json.dumps({"status": "ok"}, separators=(",", ":")).encode()
        )
        create_connection.return_value = sock

        self.assertTrue(container_liveness.check_liveness())
        create_connection.assert_called_once_with(("127.0.0.1", 8080), timeout=3.0)
        self.assertIn(b"GET /ping HTTP/1.1", sock.sent)

    @patch.object(container_liveness.socket, "create_connection")
    def test_rejects_non_200_response(self, create_connection):
        create_connection.return_value = _SocketContext(
            b'HTTP/1.1 503 Service Unavailable\r\n\r\n{"status":"ok"}'
        )

        self.assertFalse(container_liveness.check_liveness())

    @patch.object(container_liveness.socket, "create_connection")
    def test_rejects_wrong_or_malformed_body(self, create_connection):
        create_connection.return_value = _SocketContext(
            b'HTTP/1.1 200 OK\r\n\r\n{"database":"connected"}'
        )

        self.assertFalse(container_liveness.check_liveness())

    @patch.object(
        container_liveness.socket,
        "create_connection",
        side_effect=TimeoutError("sensitive details"),
    )
    def test_timeout_fails_without_exposing_exception(self, _create_connection):
        self.assertEqual(container_liveness.main(), 1)


if __name__ == "__main__":
    unittest.main()
