"""Camada de auditoria do sistema."""

from src.audit.audit_log_service import (
    EVENT_ACCESS_GRANTED,
    EVENT_ACCESS_REVOKED,
    EVENT_ACCOUNT_CREATED,
    EVENT_ACCOUNT_DELETED,
    EVENT_CHAT_PROMPT,
    EVENT_LOGIN,
    EVENT_PROMPT_GUARD_BLOCK,
    EVENT_ROLE_CHANGED,
    AuditEntry,
    AuditLogService,
)

__all__ = [
    "AuditEntry",
    "AuditLogService",
    "EVENT_ACCESS_GRANTED",
    "EVENT_ACCESS_REVOKED",
    "EVENT_ACCOUNT_CREATED",
    "EVENT_ACCOUNT_DELETED",
    "EVENT_CHAT_PROMPT",
    "EVENT_LOGIN",
    "EVENT_PROMPT_GUARD_BLOCK",
    "EVENT_ROLE_CHANGED",
]
