"""Shared pytest fixtures for the app/ (FastAPI) test suite.

Sets safe defaults before anything imports app.main (which builds the FastAPI app at
import time via `app = create_app()`), so tests never depend on unset env vars or
accidentally touch a real database during collection.
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SESSION_SECRET_KEY", "test-suite-session-secret")
os.environ.setdefault("AUTH_DB_HOST", "test-suite-unresolvable.invalid")
os.environ.setdefault("AUTH_DB_PORT", "5432")
os.environ.setdefault("AUTH_DB_NAME", "test")
os.environ.setdefault("AUTH_DB_USER", "test")
os.environ.setdefault("AUTH_DB_PASSWORD", "test")
os.environ.setdefault("AUTH_DB_SSLMODE", "disable")

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def fake_user():
    return {"id": 1, "email": "ana@example.com", "role": "user", "nome": "Ana", "can_view_audit": False}


@pytest.fixture()
def fake_admin():
    return {"id": 2, "email": "admin@example.com", "role": "admin", "nome": "Admin", "can_view_audit": True}


@pytest.fixture()
def fake_super_admin():
    return {"id": 3, "email": "root@example.com", "role": "super_admin", "nome": "Root", "can_view_audit": True}
