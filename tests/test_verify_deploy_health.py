import io
import os
import socket
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts.verify_deploy_health import (
    DEFAULT_HEALTH_URL,
    HealthAttempt,
    check_health_once,
    main,
    safe_reason_label,
    safe_url_label,
    wait_for_health,
)


class _Response:
    def __init__(self, status: int, reason: str | None = None):
        self.status = status
        self.reason = reason or ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status


class TestVerifyDeployHealth(unittest.TestCase):
    def test_safe_url_label_remove_query_userinfo_e_fragmento(self):
        label = safe_url_label("https://user:secret@example.com:8443/ping?token=abc#x")

        self.assertEqual(label, "https://example.com:8443/ping")

    def test_check_health_once_aceita_http_200(self):
        result = check_health_once(
            "https://example.com/ping",
            opener=lambda url, timeout: _Response(200),
        )

        self.assertEqual(result, HealthAttempt(ok=True, status_code=200, reason="OK"))

    def test_check_health_once_rejeita_http_500(self):
        result = check_health_once(
            "https://example.com/ping",
            opener=lambda url, timeout: _Response(500),
        )

        self.assertEqual(result, HealthAttempt(ok=False, status_code=500, reason="HTTP 500"))

    def test_check_health_once_registra_http_error_com_status_e_reason(self):
        def opener(url, timeout):
            raise HTTPError(url, 502, "Bad Gateway", hdrs=None, fp=None)

        result = check_health_once("https://example.com/ping", opener=opener)

        self.assertEqual(
            result,
            HealthAttempt(
                ok=False,
                status_code=502,
                reason="Bad Gateway",
                error_type="HTTPError",
            ),
        )

    def test_check_health_once_registra_somente_categoria_de_erro(self):
        def opener(url, timeout):
            raise TimeoutError("contains sensitive details")

        result = check_health_once("https://example.com/ping", opener=opener)

        self.assertEqual(
            result,
            HealthAttempt(ok=False, reason="timed out", error_type="TimeoutError"),
        )

    def test_check_health_once_classifica_url_error_dns(self):
        def opener(url, timeout):
            raise URLError(socket.gaierror(-2, "Name or service not known"))

        result = check_health_once("https://example.com/ping", opener=opener)

        self.assertEqual(
            result,
            HealthAttempt(
                ok=False,
                reason="name resolution failed",
                error_type="DNSFailure",
            ),
        )

    def test_wait_for_health_para_quando_endpoint_responde(self):
        calls = []

        def opener(url, timeout):
            calls.append(url)
            return _Response(200)

        output = io.StringIO()
        healthy = wait_for_health(
            "https://example.com/ping",
            timeout_seconds=1,
            interval_seconds=1,
            request_timeout_seconds=1,
            opener=opener,
            sleeper=lambda seconds: None,
            stream=output,
        )

        self.assertTrue(healthy)
        self.assertEqual(calls, ["https://example.com/ping"])
        self.assertIn("Health check succeeded", output.getvalue())
        self.assertIn("endpoint=https://example.com/ping", output.getvalue())
        self.assertIn("status=200", output.getvalue())

    def test_wait_for_health_falha_com_status_reason_sem_url_sensivel(self):
        output = io.StringIO()
        healthy = wait_for_health(
            "https://user:secret@example.com/ping?token=abc",
            timeout_seconds=0,
            interval_seconds=1,
            request_timeout_seconds=1,
            opener=lambda url, timeout: _Response(503, reason="Service Unavailable"),
            sleeper=lambda seconds: None,
            stream=output,
        )

        self.assertFalse(healthy)
        self.assertIn("Health check failed", output.getvalue())
        self.assertIn("endpoint=https://example.com/ping", output.getvalue())
        self.assertIn("status=503", output.getvalue())
        self.assertIn("reason=Service Unavailable", output.getvalue())
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("token=abc", output.getvalue())

    def test_wait_for_health_imprime_http_error_status_reason_e_tipo(self):
        def opener(url, timeout):
            raise HTTPError(url, 502, "Bad Gateway", hdrs=None, fp=None)

        output = io.StringIO()
        healthy = wait_for_health(
            "https://eq10.dsc.rodrigor.com/ping",
            timeout_seconds=0,
            interval_seconds=1,
            request_timeout_seconds=1,
            opener=opener,
            sleeper=lambda seconds: None,
            stream=output,
        )

        self.assertFalse(healthy)
        self.assertIn("endpoint=https://eq10.dsc.rodrigor.com/ping", output.getvalue())
        self.assertIn("attempt=1", output.getvalue())
        self.assertIn("status=502", output.getvalue())
        self.assertIn("reason=Bad Gateway", output.getvalue())
        self.assertIn("type=HTTPError", output.getvalue())

    def test_safe_reason_label_remove_quebras_e_limita_tamanho(self):
        reason = safe_reason_label("Bad\nGateway\rwith details", max_length=12)

        self.assertEqual(reason, "Bad Gatew...")

    def test_main_rejeita_url_invalida_sem_contatar_rede(self):
        with patch.dict(os.environ, {"APP_HEALTH_URL": "not-a-url"}, clear=True):
            with patch.object(sys, "stderr", io.StringIO()) as stderr:
                exit_code = main()

        self.assertEqual(exit_code, 2)
        self.assertIn("Invalid application health URL", stderr.getvalue())

    def test_default_health_url_usa_ping_publico(self):
        self.assertEqual(DEFAULT_HEALTH_URL, "https://eq10.dsc.rodrigor.com/ping")


if __name__ == "__main__":
    unittest.main()
