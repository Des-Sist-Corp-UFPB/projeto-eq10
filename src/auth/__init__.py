"""Autenticacao de usuarios para a interface SIA/DATASUS."""

from src.auth.session import (
    AUTH_SESSION_KEY,
    can_access_chat,
    get_authenticated_user,
    login_session,
    logout_session,
)
from src.auth.email_service import EmailConfig, EmailSendResult, EmailService
from src.auth.email_change_service import EmailChangeResult, EmailChangeService, PendingEmailChange
from src.auth.google_oauth_service import GoogleIdentity, GoogleOAuthConfig, GoogleOAuthService
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
    "EmailChangeResult",
    "EmailChangeService",
    "EmailSendResult",
    "EmailVerificationResult",
    "EmailVerificationService",
    "EmailVerificationToken",
    "EmailService",
    "GoogleIdentity",
    "GoogleOAuthConfig",
    "GoogleOAuthService",
    "PasswordResetResult",
    "PasswordResetService",
    "PasswordResetToken",
    "PendingEmailChange",
    "UserProfile",
    "UserService",
    "can_access_chat",
    "get_authenticated_user",
    "is_email_verification_required",
    "login_session",
    "logout_session",
]
