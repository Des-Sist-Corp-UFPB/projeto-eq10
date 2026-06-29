import unittest
from unittest.mock import patch

from sqlalchemy import create_engine

from src.auth.account_reactivation_service import AccountReactivationService
from src.auth.email_service import EmailConfig, EmailSendResult, EmailService, mask_email
from src.auth.pending_registration_service import PendingRegistrationService
from src.auth.user_service import UserService
from src.ui.auth_modal import (
    AUTH_UNAVAILABLE_MESSAGE,
    CONFIRM_EMAIL_STALE_MESSAGE,
    REGISTRATION_PUBLIC_EMAIL_SEND_FAILED_MESSAGE,
    REGISTRATION_PUBLIC_EMAIL_UNAVAILABLE_MESSAGE,
    REGISTRATION_PUBLIC_NEUTRAL_MESSAGE,
    handle_email_code_confirmation,
    handle_register_submit,
    resolve_registration_next_step,
)


FORBIDDEN_PUBLIC_TERMS = (
    "desativada",
    "ativa",
    "ja existe",
    "já existe",
    "nao existe",
    "não existe",
)


class SentEmailService(EmailService):
    def __init__(self):
        super().__init__(EmailConfig(enabled=True, provider="smtp"))
        self.messages = []

    def send_email(
        self,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        *,
        message_type: str = "generic",
    ) -> EmailSendResult:
        self.messages.append(
            {
                "to": to,
                "subject": subject,
                "body_text": body_text,
                "body_html": body_html,
                "message_type": message_type,
            }
        )
        return EmailSendResult(
            success=True,
            sent=True,
            provider="smtp",
            mode="smtp",
            message="sent",
            message_type=message_type,
            recipient=mask_email(to),
        )


class FailingSmtpEmailService(EmailService):
    def __init__(self):
        super().__init__(EmailConfig(enabled=True, provider="smtp"))

    def send_email(
        self,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        *,
        message_type: str = "generic",
    ) -> EmailSendResult:
        return EmailSendResult(
            success=False,
            sent=False,
            provider="smtp",
            mode="smtp",
            message="send failed",
            error_code="smtp_send_failed",
            message_type=message_type,
            recipient=mask_email(to),
        )


class TestAuthRegistrationFlow(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.email_service = SentEmailService()
        self.user_service = UserService(self.engine)
        self.pending_service = PendingRegistrationService(self.engine, email_service=self.email_service)
        self.reactivation_service = AccountReactivationService(self.engine, email_service=self.email_service)

    def _submit(self, email: str, session_state: dict | None = None):
        return handle_register_submit(
            session_state if session_state is not None else {},
            self.pending_service,
            self.reactivation_service,
            nome="Ana Silva",
            email=email,
            senha="nova-senha",
            confirmar_senha="nova-senha",
        )

    def _assert_neutral_public_message(self, message: str):
        lowered = message.lower()
        for term in FORBIDDEN_PUBLIC_TERMS:
            self.assertNotIn(term, lowered)
        self.assertEqual(message, REGISTRATION_PUBLIC_NEUTRAL_MESSAGE)
        self.assertNotEqual(message, AUTH_UNAVAILABLE_MESSAGE)

    def _pending_count(self, email="ana@example.com"):
        with self.engine.connect() as conn:
            return conn.exec_driver_sql(
                "SELECT COUNT(*) FROM pending_registrations WHERE lower(email) = lower(?)",
                (email,),
            ).scalar_one()

    def _active_pending_count(self, email="ana@example.com"):
        with self.engine.connect() as conn:
            return conn.exec_driver_sql(
                """
                SELECT COUNT(*)
                FROM pending_registrations
                WHERE lower(email) = lower(?)
                  AND usado_em IS NULL
                """,
                (email,),
            ).scalar_one()

    def _reactivation_token_count(self, email="ana@example.com"):
        with self.engine.connect() as conn:
            return conn.exec_driver_sql(
                """
                SELECT COUNT(*)
                FROM account_reactivation_tokens t
                JOIN usuarios u ON u.id = t.user_id
                WHERE lower(u.email) = lower(?)
                """,
                (email,),
            ).scalar_one()

    def _user_row(self, email="ana@example.com"):
        with self.engine.connect() as conn:
            return conn.exec_driver_sql(
                "SELECT * FROM usuarios WHERE lower(email) = lower(?) ORDER BY id DESC LIMIT 1",
                (email,),
            ).mappings().first()

    def test_resolve_registration_next_step_uses_neutral_public_message(self):
        self.user_service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        result = self.pending_service.start_registration(
            "Ana Silva",
            "ana@example.com",
            "nova-senha",
            "nova-senha",
        )
        next_step = resolve_registration_next_step(result, "ana@example.com")

        self.assertEqual(result.status, "active_email_exists")
        self.assertEqual(next_step.status, "email_instructions_available")
        self.assertEqual(next_step.panel, "confirm_email")
        self.assertEqual(next_step.flow_kind, "neutral")
        self._assert_neutral_public_message(next_step.message)

    def test_register_submit_new_active_and_deactivated_emails_have_same_public_message(self):
        self.user_service.create_user("Bia Silva", "bia@example.com", "senha-forte", "senha-forte")
        deleted = self.user_service.create_user("Caio Silva", "caio@example.com", "senha-forte", "senha-forte")
        self.user_service.soft_delete_user(deleted.id)

        new_step = self._submit("ana@example.com")
        active_step = self._submit("bia@example.com")
        deactivated_step = self._submit("caio@example.com")

        self.assertEqual(new_step.message, active_step.message)
        self.assertEqual(active_step.message, deactivated_step.message)
        self._assert_neutral_public_message(new_step.message)
        self.assertEqual(new_step.panel, "confirm_email")
        self.assertEqual(active_step.panel, "confirm_email")
        self.assertEqual(deactivated_step.panel, "confirm_email")

    def test_register_submit_for_deactivated_email_creates_reactivation_token_without_public_offer(self):
        user = self.user_service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )
        self.user_service.soft_delete_user(user.id)
        session_state = {
            "auth_global_error": AUTH_UNAVAILABLE_MESSAGE,
            "register_error": AUTH_UNAVAILABLE_MESSAGE,
            "pending_registration_id": 999,
            "pending_registration_email": "stale@example.com",
        }

        next_step = handle_register_submit(
            session_state,
            self.pending_service,
            self.reactivation_service,
            nome="Ana Silva",
            email="ana@example.com",
            senha="nova-senha",
            confirmar_senha="nova-senha",
        )

        self.assertEqual(next_step.status, "email_instructions_available")
        self.assertEqual(next_step.panel, "confirm_email")
        self.assertEqual(next_step.flow_kind, "reactivation")
        self.assertEqual(session_state["registration_flow_kind"], "reactivation")
        self.assertIn("account_reactivation_token_id", session_state)
        self.assertNotIn("pending_registration_id", session_state)
        self.assertNotIn("pending_registration_email", session_state)
        self.assertNotIn("auth_global_error", session_state)
        self.assertNotIn("register_error", session_state)
        self._assert_neutral_public_message(next_step.message)
        self.assertEqual(self._pending_count(), 0)
        self.assertEqual(self._reactivation_token_count(), 1)

    def test_register_submit_for_new_email_creates_pending_registration(self):
        session_state = {}

        next_step = handle_register_submit(
            session_state,
            self.pending_service,
            self.reactivation_service,
            nome="Ana Silva",
            email="ana@example.com",
            senha="nova-senha",
            confirmar_senha="nova-senha",
        )

        self.assertEqual(next_step.status, "email_instructions_available")
        self.assertEqual(next_step.panel, "confirm_email")
        self.assertEqual(session_state["registration_flow_kind"], "pending_registration")
        self.assertIn("pending_registration_id", session_state)
        self.assertNotIn("account_reactivation_token_id", session_state)
        self._assert_neutral_public_message(next_step.message)
        self.assertEqual(self._pending_count(), 1)

    def test_register_submit_for_active_email_does_not_create_duplicate_user(self):
        self.user_service.create_user("Ana Silva", "ana@example.com", "senha-forte", "senha-forte")
        session_state = {}

        next_step = handle_register_submit(
            session_state,
            self.pending_service,
            self.reactivation_service,
            nome="Ana Silva",
            email="ana@example.com",
            senha="nova-senha",
            confirmar_senha="nova-senha",
        )

        self.assertEqual(next_step.status, "email_instructions_available")
        self.assertEqual(next_step.panel, "confirm_email")
        self.assertEqual(session_state["registration_flow_kind"], "neutral")
        self._assert_neutral_public_message(next_step.message)
        self.assertEqual(self._pending_count(), 0)
        self.assertEqual(self._reactivation_token_count(), 0)

    def test_email_disabled_nao_revela_estado_da_conta(self):
        user = self.user_service.create_user("Ana Silva", "ana@example.com", "senha-forte", "senha-forte")
        self.user_service.soft_delete_user(user.id)
        fake_email_service = EmailService(EmailConfig(enabled=False, provider="fake"))
        pending_service = PendingRegistrationService(self.engine, email_service=fake_email_service)
        reactivation_service = AccountReactivationService(self.engine, email_service=fake_email_service)

        next_step = handle_register_submit(
            {},
            pending_service,
            reactivation_service,
            nome="Ana Silva",
            email="ana@example.com",
            senha="nova-senha",
            confirmar_senha="nova-senha",
        )

        self.assertEqual(next_step.status, "email_sending_disabled")
        self.assertIsNone(next_step.panel)
        self.assertEqual(next_step.message, REGISTRATION_PUBLIC_EMAIL_UNAVAILABLE_MESSAGE)
        for term in FORBIDDEN_PUBLIC_TERMS:
            self.assertNotIn(term, next_step.message.lower())
        self.assertEqual(self._pending_count(), 0)
        self.assertEqual(self._reactivation_token_count(), 0)

    def test_smtp_falha_mostra_mensagem_segura_sem_generico_auth(self):
        failing_email_service = FailingSmtpEmailService()
        pending_service = PendingRegistrationService(self.engine, email_service=failing_email_service)
        reactivation_service = AccountReactivationService(self.engine, email_service=failing_email_service)

        next_step = handle_register_submit(
            {},
            pending_service,
            reactivation_service,
            nome="Ana Silva",
            email="ana@example.com",
            senha="nova-senha",
            confirmar_senha="nova-senha",
        )

        self.assertEqual(next_step.status, "email_sending_failed")
        self.assertEqual(next_step.message, REGISTRATION_PUBLIC_EMAIL_SEND_FAILED_MESSAGE)
        self.assertNotEqual(next_step.message, AUTH_UNAVAILABLE_MESSAGE)
        self.assertEqual(self._active_pending_count(), 0)

    def test_confirmacao_de_codigo_de_reativacao_usa_servico_de_reativacao(self):
        user = self.user_service.create_user("Ana Silva", "ana@example.com", "senha-forte", "senha-forte")
        self.user_service.soft_delete_user(user.id)
        session_state = {}

        with patch(
            "src.auth.account_reactivation_service.generate_reactivation_code",
            return_value="123456",
        ):
            next_step = handle_register_submit(
                session_state,
                self.pending_service,
                self.reactivation_service,
                nome="Ana Silva",
                email="ana@example.com",
                senha="nova-senha",
                confirmar_senha="nova-senha",
            )

        self.assertEqual(next_step.flow_kind, "reactivation")
        result = handle_email_code_confirmation(
            session_state,
            self.pending_service,
            self.reactivation_service,
            code="123456",
        )
        user_row = self._user_row()

        self.assertTrue(result.success)
        self.assertEqual(result.flow_kind, "reactivation")
        self.assertEqual(result.status, "reactivated")
        self.assertIn("reativada", result.message.lower())
        self.assertFalse(user_row["deletado"])
        self.assertIsNone(user_row["deletado_em"])
        self.assertNotIn("pending_registration_id", session_state)
        self.assertNotIn("account_reactivation_token_id", session_state)
        self.assertNotIn("123456", " ".join(str(value) for value in session_state.values()))

    def test_confirmacao_de_codigo_de_cadastro_cria_usuario(self):
        session_state = {}

        with patch(
            "src.auth.pending_registration_service.generate_registration_code",
            return_value="654321",
        ):
            next_step = handle_register_submit(
                session_state,
                self.pending_service,
                self.reactivation_service,
                nome="Ana Silva",
                email="ana@example.com",
                senha="nova-senha",
                confirmar_senha="nova-senha",
            )

        self.assertEqual(next_step.flow_kind, "pending_registration")
        result = handle_email_code_confirmation(
            session_state,
            self.pending_service,
            self.reactivation_service,
            code="654321",
        )
        user_row = self._user_row()

        self.assertTrue(result.success)
        self.assertEqual(result.flow_kind, "pending_registration")
        self.assertEqual(result.status, "created")
        self.assertIn("criada", result.message.lower())
        self.assertFalse(user_row["deletado"])
        self.assertTrue(user_row["email_verificado"])
        self.assertNotIn("pending_registration_id", session_state)
        self.assertNotIn("account_reactivation_token_id", session_state)
        self.assertNotIn("654321", " ".join(str(value) for value in session_state.values()))

    def test_confirmacao_com_estado_ausente_mostra_mensagem_generica_segura(self):
        result = handle_email_code_confirmation(
            {},
            self.pending_service,
            self.reactivation_service,
            code="123456",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "invalid_or_expired")
        self.assertEqual(result.message, CONFIRM_EMAIL_STALE_MESSAGE)
        self.assertNotIn("Solicitacao de cadastro", result.message)


if __name__ == "__main__":
    unittest.main()
