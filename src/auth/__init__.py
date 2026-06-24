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
from src.auth.email_verification_service import (
    EmailVerificationResult,
    EmailVerificationService,
    EmailVerificationToken,
    is_email_verification_required,
)
from src.auth.password_reset_service import PasswordResetResult, PasswordResetService, PasswordResetToken
from src.auth.user_service import AuthValidationError, UserProfile, UserService
from src.auth.roles import (
    ROLE_USER,
    ROLE_SUPER_ADMIN,
    VALID_ROLES,
    is_super_admin,
    can_view_audit_log,
    role_display_name,
)

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
    "PasswordResetResult",
    "PasswordResetService",
    "PasswordResetToken",
    "PendingEmailChange",
    "UserProfile",
    "UserService",
    "can_access_chat",
    "can_view_audit_log",
    "get_authenticated_user",
    "is_email_verification_required",
    "is_super_admin",
    "login_session",
    "logout_session",
    "role_display_name",
    "ROLE_SUPER_ADMIN",
    "ROLE_USER",
    "VALID_ROLES",
]
