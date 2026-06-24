"""Utilitarios de seguranca para senhas de usuarios.

Suporte a Argon2 (preferido) com fallback de verificacao para hashes
legados PBKDF2-SHA256. Novos hashes sempre usam Argon2.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

MIN_PASSWORD_LENGTH = 8

# ──────────────────────────────────────────────
# Algoritmo legado (PBKDF2-SHA256 stdlib)
# Mantido SOMENTE para verificacao de contas ja existentes.
# ──────────────────────────────────────────────
_PBKDF2_ALGORITHM = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 260_000
_PBKDF2_SALT_BYTES = 16


def _pbkdf2_hash(password: str) -> str:
    """Gera hash PBKDF2-SHA256 (legado, nao usar para novas senhas)."""
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii")
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"{_PBKDF2_ALGORITHM}${_PBKDF2_ITERATIONS}${encoded_salt}${encoded_digest}"


def _pbkdf2_verify(password: str, stored_hash: str) -> bool:
    """Verifica uma senha contra um hash PBKDF2-SHA256 legado."""
    try:
        algorithm, iterations_text, encoded_salt, encoded_digest = stored_hash.split("$", 3)
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected_digest = base64.urlsafe_b64decode(encoded_digest.encode("ascii"))
    except (ValueError, TypeError):
        return False

    if algorithm != _PBKDF2_ALGORITHM:
        return False

    actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)


# ──────────────────────────────────────────────
# Algoritmo preferido: Argon2id
# ──────────────────────────────────────────────
_ARGON2_PREFIX = "$argon2id$"


def _get_argon2_hasher():
    """Retorna o hasher Argon2, ou None se a biblioteca nao estiver instalada."""
    try:
        from argon2 import PasswordHasher
        return PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)
    except ImportError:
        return None


def hash_password(password: str) -> str:
    """Gera hash seguro da senha.

    Usa Argon2id se disponivel; caso contrario, usa PBKDF2-SHA256.
    NUNCA deve ser chamado para logs, historico de chat ou qualquer
    campo que nao seja senha de usuario.
    """
    if not password:
        raise ValueError("Senha obrigatoria.")

    hasher = _get_argon2_hasher()
    if hasher is not None:
        return hasher.hash(password)

    # Fallback: argon2-cffi nao instalado — usa PBKDF2
    return _pbkdf2_hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Valida uma senha contra o hash persistido.

    Detecta automaticamente o algoritmo pelo prefixo do hash, permitindo
    que contas com hashes PBKDF2 legados continuem funcionando.
    """
    if not password or not stored_hash:
        return False

    if stored_hash.startswith(_ARGON2_PREFIX):
        hasher = _get_argon2_hasher()
        if hasher is None:
            return False
        try:
            return hasher.verify(stored_hash, password)
        except Exception:
            return False

    # Hash legado PBKDF2
    return _pbkdf2_verify(password, stored_hash)
