from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from jose import JWTError, jwt

from .settings import get_settings

ALGO = "HS256"


@dataclass
class TokenClaims:
    tenant_id: str
    session_id: str
    exp: int


def issue_token(tenant_id: str, session_id: str | None = None) -> tuple[str, str]:
    """Return (jwt, session_id)."""
    s = get_settings()
    sid = session_id or f"sess_{uuid.uuid4().hex[:16]}"
    now = int(time.time())
    payload = {
        "sub": tenant_id,
        "sid": sid,
        "iat": now,
        "exp": now + s.audvoice_jwt_ttl_seconds,
    }
    return jwt.encode(payload, s.audvoice_jwt_secret, algorithm=ALGO), sid


def verify_token(token: str) -> TokenClaims:
    s = get_settings()
    try:
        data = jwt.decode(token, s.audvoice_jwt_secret, algorithms=[ALGO])
    except JWTError as exc:
        raise ValueError(f"invalid token: {exc}") from exc
    return TokenClaims(tenant_id=data["sub"], session_id=data["sid"], exp=data["exp"])


def tenant_for_api_key(api_key: str) -> str | None:
    return get_settings().api_key_map.get(api_key)
