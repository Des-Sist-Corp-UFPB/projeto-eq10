"""Autenticacao de usuarios para a interface SIA/DATASUS."""

from src.auth.session import (
    AUTH_SESSION_KEY,
    can_access_chat,
    get_authenticated_user,
    login_session,
    logout_session,
)
from src.auth.email_service import EmailConfig, EmailSendResult, EmailService
from src.auth.email_verification_service import (
    EmailVerificationResult,
    EmailVerificationService,
    EmailVerificationToken,
    is_email_verification_required,
)
from src.auth.password_reset_service import PasswordResetResult, PasswordResetService, PasswordResetToken
from src.auth.user_service import AuthValidationError, UserProfile, UserService

__all__ = [
    "AUTH_SESSION_KEY",
    "AuthValidationError",
    "EmailConfig",
    "EmailSendResult",
    "EmailVerificationResult",
    "EmailVerificationService",
    "EmailVerificationToken",
    "EmailService",
    "PasswordResetResult",
    "PasswordResetService",
    "PasswordResetToken",
    "UserProfile",
    "UserService",
    "can_access_chat",
    "get_authenticated_user",
    "is_email_verification_required",
    "login_session",
    "logout_session",
]
