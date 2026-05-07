"""FastAPI entrypoint: /healthz, POST /v1/sessions, WS /v1/voice."""

from __future__ import annotations

import base64
import json
import logging
import struct
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import auth
from .session import Session
from .settings import get_settings

logging.basicConfig(level=get_settings().log_level)
log = logging.getLogger("audvoice")

app = FastAPI(title="AuDesign Voice", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ─── REST: issue WS token ───────────────────────────────────────────────────


class SessionRequest(BaseModel):
    pass


class SessionResponse(BaseModel):
    session_id: str
    token: str
    ws_url: str
    expires_in: int


@app.post("/v1/sessions", response_model=SessionResponse)
async def create_session(
    body: SessionRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> SessionResponse:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key")
    tenant = auth.tenant_for_api_key(x_api_key)
    if not tenant:
        raise HTTPException(status_code=401, detail="invalid api key")
    token, sid = auth.issue_token(tenant)
    s = get_settings()
    return SessionResponse(
        session_id=sid,
        token=token,
        ws_url="/v1/voice",  # client appends to its base URL
        expires_in=s.audvoice_jwt_ttl_seconds,
    )


# ─── WebSocket handler ──────────────────────────────────────────────────────


@app.websocket("/v1/voice")
async def voice_ws(ws: WebSocket) -> None:
    # Auth: prefer Authorization: Bearer; fall back to ?token= for browsers
    auth_header = ws.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    else:
        token = ws.query_params.get("token", "")
    try:
        claims = auth.verify_token(token)
    except ValueError as exc:
        await ws.close(code=4401, reason=f"unauthorized: {exc}")
        return

    await ws.accept()

    async def send_json(payload: dict[str, Any]) -> None:
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception:
            log.debug("send_json after close")

    async def send_bytes(stream_id: int, pcm: bytes) -> None:
        # 4-byte big-endian stream id header so the client can demux
        try:
            await ws.send_bytes(struct.pack(">I", stream_id) + pcm)
        except Exception:
            log.debug("send_bytes after close")

    sess = Session(
        session_id=claims.session_id,
        tenant_id=claims.tenant_id,
        send_json=send_json,
        send_bytes=send_bytes,
    )
    try:
        await sess.start()
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if (b := msg.get("bytes")) is not None:
                # Raw PCM16 16 kHz audio frame
                sess.feed_audio(b)
            elif (t := msg.get("text")) is not None:
                try:
                    ev = json.loads(t)
                except json.JSONDecodeError:
                    await send_json(
                        {"type": "error", "code": "bad_json", "message": "invalid JSON"}
                    )
                    continue
                # Allow base64 audio in JSON for clients that can't send binary
                if ev.get("type") == "input_audio.append":
                    try:
                        sess.feed_audio(base64.b64decode(ev.get("audio", "")))
                    except Exception as exc:
                        await send_json({"type": "error", "code": "bad_audio", "message": str(exc)})
                else:
                    await sess.handle_event(ev)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws error")
    finally:
        await sess.close()
        try:
            await ws.close()
        except Exception:
            pass
