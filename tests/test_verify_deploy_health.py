import io
import os
import sys
import unittest
from unittest.mock import patch

from scripts.verify_deploy_health import (
    DEFAULT_HEALTH_URL,
    HealthAttempt,
    check_health_once,
    main,
    safe_url_label,
    wait_for_health,
)


class _Response:
    def __init__(self, status: int):
        self.status = status

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

        self.assertEqual(result, HealthAttempt(ok=True, status_code=200))

    def test_check_health_once_rejeita_http_500(self):
        result = check_health_once(
            "https://example.com/ping",
            opener=lambda url, timeout: _Response(500),
        )

        self.assertEqual(result, HealthAttempt(ok=False, status_code=500))

    def test_check_health_once_registra_somente_categoria_de_erro(self):
        def opener(url, timeout):
            raise TimeoutError("contains sensitive details")

        result = check_health_once("https://example.com/ping", opener=opener)

        self.assertEqual(result, HealthAttempt(ok=False, error_type="TimeoutError"))

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
        self.assertIn("HTTP 200", output.getvalue())

    def test_wait_for_health_falha_sem_imprimir_resposta_ou_url_completa(self):
        output = io.StringIO()
        healthy = wait_for_health(
            "https://user:secret@example.com/ping?token=abc",
            timeout_seconds=0,
            interval_seconds=1,
            request_timeout_seconds=1,
            opener=lambda url, timeout: _Response(503),
            sleeper=lambda seconds: None,
            stream=output,
        )

        self.assertFalse(healthy)
        self.assertIn("status=503", output.getvalue())
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("token=abc", output.getvalue())

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
