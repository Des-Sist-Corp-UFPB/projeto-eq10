"""Utilitarios de seguranca para senhas de usuarios."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260_000
PASSWORD_SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    """Gera hash PBKDF2-SHA256 com salt aleatorio."""
    if not password:
        raise ValueError("Senha obrigatoria.")

    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii")
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii")

    return (
        f"{PASSWORD_HASH_ALGORITHM}"
        f"${PASSWORD_HASH_ITERATIONS}"
        f"${encoded_salt}"
        f"${encoded_digest}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """Valida uma senha contra o hash persistido sem expor detalhes."""
    if not password or not stored_hash:
        return False

    try:
        algorithm, iterations_text, encoded_salt, encoded_digest = stored_hash.split("$", 3)
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected_digest = base64.urlsafe_b64decode(encoded_digest.encode("ascii"))
    except (ValueError, TypeError):
        return False

    if algorithm != PASSWORD_HASH_ALGORITHM:
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_digest, expected_digest)
