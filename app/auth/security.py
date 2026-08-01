"""Password hashing — ported 1:1 from src/auth/security.py.

Argon2id preferred; verification falls back to legacy PBKDF2-SHA256 hashes so
existing accounts keep working.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

MIN_PASSWORD_LENGTH = 8

_PBKDF2_ALGORITHM = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 260_000
_PBKDF2_SALT_BYTES = 16
_ARGON2_PREFIX = "$argon2id$"


def _pbkdf2_hash(password: str) -> str:
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii")
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"{_PBKDF2_ALGORITHM}${_PBKDF2_ITERATIONS}${encoded_salt}${encoded_digest}"


def _pbkdf2_verify(password: str, stored_hash: str) -> bool:
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


def _get_argon2_hasher():
    try:
        from argon2 import PasswordHasher

        return PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)
    except ImportError:
        return None


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Senha obrigatoria.")

    hasher = _get_argon2_hasher()
    if hasher is not None:
        return hasher.hash(password)

    return _pbkdf2_hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
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

    return _pbkdf2_verify(password, stored_hash)
