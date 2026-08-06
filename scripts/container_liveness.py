"""Deterministic Docker liveness probe for FastAPI behind Nginx."""

from __future__ import annotations

import json
import socket


HOST = "127.0.0.1"
PORT = 8080
TIMEOUT_SECONDS = 3.0
MAX_RESPONSE_BYTES = 8192


def check_liveness() -> bool:
    request = (
        b"GET /ping HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Connection: close\r\n\r\n"
    )
    with socket.create_connection((HOST, PORT), timeout=TIMEOUT_SECONDS) as connection:
        connection.settimeout(TIMEOUT_SECONDS)
        connection.sendall(request)
        response = bytearray()
        while len(response) < MAX_RESPONSE_BYTES:
            chunk = connection.recv(min(4096, MAX_RESPONSE_BYTES - len(response)))
            if not chunk:
                break
            response.extend(chunk)

    try:
        headers, body = bytes(response).split(b"\r\n\r\n", 1)
        status_line = headers.split(b"\r\n", 1)[0]
        payload = json.loads(body)
    except (ValueError, json.JSONDecodeError):
        return False

    return status_line.startswith(b"HTTP/1.1 200 ") and payload == {"status": "ok"}


def main() -> int:
    try:
        return 0 if check_liveness() else 1
    except (ConnectionError, OSError, TimeoutError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
