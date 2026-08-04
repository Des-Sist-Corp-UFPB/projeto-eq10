"""app/auth/security.py — password hashing (Argon2 preferred, PBKDF2 legacy fallback)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.auth.security import (
    MIN_PASSWORD_LENGTH,
    _pbkdf2_hash,
    _pbkdf2_verify,
    hash_password,
    verify_password,
)


def test_hash_password_uses_argon2_by_default():
    hashed = hash_password("senha12345")
    assert hashed.startswith("$argon2id$")


def test_hash_password_rejects_empty_password():
    with pytest.raises(ValueError):
        hash_password("")


def test_verify_password_argon2_roundtrip():
    hashed = hash_password("senha12345")
    assert verify_password("senha12345", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_verify_password_empty_inputs():
    assert verify_password("", "somehash") is False
    assert verify_password("pw", "") is False


def test_pbkdf2_hash_and_verify_roundtrip():
    hashed = _pbkdf2_hash("senha12345")
    assert hashed.startswith("pbkdf2_sha256$")
    assert _pbkdf2_verify("senha12345", hashed) is True
    assert _pbkdf2_verify("wrong", hashed) is False


def test_pbkdf2_verify_rejects_malformed_hash():
    assert _pbkdf2_verify("senha12345", "not-a-valid-hash") is False
    assert _pbkdf2_verify("senha12345", "wrongalgo$1$salt$digest") is False


def test_verify_password_detects_legacy_pbkdf2_hash():
    legacy_hash = _pbkdf2_hash("senha12345")
    assert verify_password("senha12345", legacy_hash) is True


def test_hash_password_falls_back_to_pbkdf2_when_argon2_missing():
    with patch("app.auth.security._get_argon2_hasher", return_value=None):
        hashed = hash_password("senha12345")
    assert hashed.startswith("pbkdf2_sha256$")


def test_verify_password_argon2_hash_but_hasher_unavailable():
    hashed = hash_password("senha12345")
    with patch("app.auth.security._get_argon2_hasher", return_value=None):
        assert verify_password("senha12345", hashed) is False


def test_verify_password_argon2_exception_returns_false():
    hashed = hash_password("senha12345")
    with patch("app.auth.security._get_argon2_hasher") as fake_hasher_getter:
        fake_hasher_getter.return_value.verify.side_effect = Exception("boom")
        assert verify_password("senha12345", hashed) is False


def test_min_password_length_constant():
    assert MIN_PASSWORD_LENGTH == 8
