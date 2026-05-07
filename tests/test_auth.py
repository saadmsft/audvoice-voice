"""Auth tests."""

import time

import pytest
from audvoice import auth
from audvoice.settings import get_settings


def test_issue_and_verify(monkeypatch):
    monkeypatch.setenv("AUDVOICE_JWT_SECRET", "x" * 32)
    get_settings.cache_clear()
    token, sid = auth.issue_token("tenant-1")
    claims = auth.verify_token(token)
    assert claims.tenant_id == "tenant-1"
    assert claims.session_id == sid
    assert claims.exp > int(time.time())


def test_invalid_token_rejected(monkeypatch):
    monkeypatch.setenv("AUDVOICE_JWT_SECRET", "x" * 32)
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        auth.verify_token("not-a-jwt")


def test_api_key_map(monkeypatch):
    monkeypatch.setenv("AUDVOICE_API_KEYS", "k1:t1, k2:t2")
    get_settings.cache_clear()
    assert auth.tenant_for_api_key("k1") == "t1"
    assert auth.tenant_for_api_key("k2") == "t2"
    assert auth.tenant_for_api_key("missing") is None
