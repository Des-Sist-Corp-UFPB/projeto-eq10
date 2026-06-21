"""Autenticacao de usuarios para a interface SIA/DATASUS."""

from src.auth.session import (
    AUTH_SESSION_KEY,
    can_access_chat,
    get_authenticated_user,
    login_session,
    logout_session,
)
from src.auth.user_service import AuthValidationError, UserProfile, UserService

__all__ = [
    "AUTH_SESSION_KEY",
    "AuthValidationError",
    "UserProfile",
    "UserService",
    "can_access_chat",
    "get_authenticated_user",
    "login_session",
    "logout_session",
]
