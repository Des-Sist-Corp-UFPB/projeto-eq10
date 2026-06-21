import os
import unittest
from unittest.mock import patch

from src.auth.email_service import (
    EMAIL_CONFIG_INCOMPLETE_MESSAGE,
    EMAIL_DISABLED_MESSAGE,
    EMAIL_PROVIDER_NOT_IMPLEMENTED_MESSAGE,
    EMAIL_UNSUPPORTED_PROVIDER_MESSAGE,
    EmailConfig,
    EmailService,
    mask_email,
)


class TestEmailService(unittest.TestCase):
    def test_default_config_usa_modo_fake_local(self):
        with patch.dict(os.environ, {}, clear=True):
            config = EmailConfig.from_environment()

        self.assertFalse(config.enabled)
        self.assertEqual(config.provider, "fake")

    def test_email_enabled_false_nao_envia_email_real(self):
        env = {
            "EMAIL_ENABLED": "false",
            "EMAIL_PROVIDER": "smtp",
            "EMAIL_SMTP_PASSWORD": "smtp-secret",
        }

        with patch.dict(os.environ, env, clear=True):
            result = EmailService.from_environment().send_email(
                "ana@example.com",
                "Assunto",
                "Mensagem",
            )

        self.assertTrue(result.success)
        self.assertFalse(result.sent)
        self.assertEqual(result.mode, "fake")
        self.assertEqual(result.error_code, "email_disabled")
        self.assertEqual(result.message, EMAIL_DISABLED_MESSAGE)
        self.assertNotIn("smtp-secret", result.message)

    def test_fake_send_retorna_resultado_seguro(self):
        service = EmailService(EmailConfig(enabled=False, provider="fake"))

        result = service.send_email("ana@example.com", "Aviso", "Conteudo")

        self.assertTrue(result.success)
        self.assertFalse(result.sent)
        self.assertEqual(result.provider, "fake")
        self.assertEqual(result.mode, "fake")
        self.assertEqual(result.message_type, "generic")
        self.assertEqual(result.recipient, "a***a@example.com")

    def test_nao_loga_token_ou_link_de_verificacao_no_modo_fake(self):
        service = EmailService(EmailConfig(enabled=False, provider="fake"))
        raw_url = "https://app.example.com/verify?token=RAW_SECRET_TOKEN"

        with self.assertLogs("src.auth.email_service", level="INFO") as captured:
            result = service.send_verification_email("ana@example.com", raw_url)

        log_output = "\n".join(captured.output)
        result_text = str(result.as_dict())

        self.assertEqual(result.message_type, "verification")
        self.assertNotIn("RAW_SECRET_TOKEN", log_output)
        self.assertNotIn(raw_url, log_output)
        self.assertNotIn("RAW_SECRET_TOKEN", result_text)
        self.assertNotIn(raw_url, result_text)

    def test_nao_loga_link_de_reset_no_modo_fake(self):
        service = EmailService(EmailConfig(enabled=False, provider="fake"))
        reset_url = "https://app.example.com/reset?token=RESET_TOKEN"

        with self.assertLogs("src.auth.email_service", level="INFO") as captured:
            result = service.send_password_reset_email("ana@example.com", reset_url)

        log_output = "\n".join(captured.output)

        self.assertEqual(result.message_type, "password_reset")
        self.assertNotIn("RESET_TOKEN", log_output)
        self.assertNotIn(reset_url, log_output)
        self.assertNotIn("RESET_TOKEN", str(result.as_dict()))

    def test_config_smtp_incompleta_falha_com_erro_seguro(self):
        env = {
            "EMAIL_ENABLED": "true",
            "EMAIL_PROVIDER": "smtp",
            "EMAIL_FROM": "noreply@example.com",
            "EMAIL_SMTP_PASSWORD": "smtp-secret",
        }

        with patch.dict(os.environ, env, clear=True):
            result = EmailService.from_environment().send_email(
                "ana@example.com",
                "Assunto",
                "Mensagem",
            )

        self.assertFalse(result.success)
        self.assertFalse(result.sent)
        self.assertEqual(result.mode, "configuration")
        self.assertEqual(result.error_code, "missing_smtp_host")
        self.assertEqual(result.message, EMAIL_CONFIG_INCOMPLETE_MESSAGE)
        self.assertNotIn("smtp-secret", result.message)

    def test_provedor_nao_suportado_falha_com_erro_seguro(self):
        env = {
            "EMAIL_ENABLED": "true",
            "EMAIL_PROVIDER": "provedor-pago-aleatorio",
            "EMAIL_API_KEY": "api-secret",
        }

        with patch.dict(os.environ, env, clear=True):
            result = EmailService.from_environment().send_email(
                "ana@example.com",
                "Assunto",
                "Mensagem",
            )

        self.assertFalse(result.success)
        self.assertFalse(result.sent)
        self.assertEqual(result.error_code, "unsupported_provider")
        self.assertEqual(result.message, EMAIL_UNSUPPORTED_PROVIDER_MESSAGE)
        self.assertNotIn("api-secret", result.message)

    def test_smtp_configurado_nao_expoe_segredo_e_ainda_nao_envia(self):
        env = {
            "EMAIL_ENABLED": "true",
            "EMAIL_PROVIDER": "smtp",
            "EMAIL_FROM": "noreply@example.com",
            "EMAIL_SMTP_HOST": "smtp.example.com",
            "EMAIL_SMTP_PORT": "587",
            "EMAIL_SMTP_USERNAME": "noreply@example.com",
            "EMAIL_SMTP_PASSWORD": "smtp-secret",
        }

        with patch.dict(os.environ, env, clear=True):
            result = EmailService.from_environment().send_email(
                "ana@example.com",
                "Assunto",
                "Mensagem",
            )

        self.assertFalse(result.success)
        self.assertFalse(result.sent)
        self.assertEqual(result.error_code, "provider_not_implemented")
        self.assertEqual(result.message, EMAIL_PROVIDER_NOT_IMPLEMENTED_MESSAGE)
        self.assertNotIn("smtp-secret", str(result.as_dict()))

    def test_api_provider_configurado_nao_expoe_chave_e_ainda_nao_envia(self):
        env = {
            "EMAIL_ENABLED": "true",
            "EMAIL_PROVIDER": "resend",
            "EMAIL_FROM": "noreply@example.com",
            "EMAIL_API_KEY": "api-secret",
        }

        with patch.dict(os.environ, env, clear=True):
            result = EmailService.from_environment().send_email(
                "ana@example.com",
                "Assunto",
                "Mensagem",
            )

        self.assertFalse(result.success)
        self.assertFalse(result.sent)
        self.assertEqual(result.error_code, "provider_not_implemented")
        self.assertEqual(result.message, EMAIL_PROVIDER_NOT_IMPLEMENTED_MESSAGE)
        self.assertNotIn("api-secret", str(result.as_dict()))

    def test_email_invalido_retorna_validacao_segura(self):
        result = EmailService(EmailConfig()).send_email(
            "email-invalido",
            "Assunto",
            "Mensagem",
        )

        self.assertFalse(result.success)
        self.assertFalse(result.sent)
        self.assertEqual(result.error_code, "invalid_recipient")

    def test_mask_email(self):
        self.assertEqual(mask_email("ana@example.com"), "a***a@example.com")
        self.assertEqual(mask_email("a@example.com"), "a***@example.com")
        self.assertEqual(mask_email("invalido"), "***")


if __name__ == "__main__":
    unittest.main()
