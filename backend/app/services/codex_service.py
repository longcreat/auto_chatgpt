"""
Codex 本地代理服务
- 运行在 FastAPI 主服务下的 /v1/*
- 将所有 OpenAI API 请求转发到 api.openai.com
- 自动注入当前激活账号的 API Key / access token
- 支持在管理系统中切换账号，Codex 无感切换
"""

import logging
from datetime import datetime
from typing import Optional

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.config import settings
from app.database import Account, SessionLocal
from app.services.credential_service import sync_account_credentials

logger = logging.getLogger(__name__)


_active_cache: dict = {
    "account_id": None,
    "email": None,
    "api_key": None,
    "access_token": None,
    "token_expires_at": None,
}


UPSTREAM = settings.OPENAI_API_BASE.rstrip("/")
TIMEOUT = httpx.Timeout(120.0, connect=30.0)
HOP_BY_HOP = {
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "upgrade",
    "proxy-authorization",
}


def get_active_account_info() -> dict:
    return dict(_active_cache)


def reload_active_account():
    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.is_active.is_(True)).first()
        if not account:
            for key in _active_cache:
                _active_cache[key] = None
            return

        if sync_account_credentials(db, account):
            db.commit()
            db.refresh(account)

        _active_cache["account_id"] = account.id
        _active_cache["email"] = account.email
        _active_cache["api_key"] = account.api_key
        _active_cache["access_token"] = account.access_token
        _active_cache["token_expires_at"] = account.token_expires_at
        logger.info("已切换到账号: %s", account.email)
    finally:
        db.close()


def switch_to_account(account_id: int) -> bool:
    db = SessionLocal()
    try:
        db.query(Account).update({"is_active": False})
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            db.rollback()
            return False
        account.is_active = True
        account.last_used_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()

    reload_active_account()
    return True


def _get_auth_header() -> Optional[str]:
    if _active_cache.get("api_key"):
        return f"Bearer {_active_cache['api_key']}"
    if _active_cache.get("access_token"):
        return f"Bearer {_active_cache['access_token']}"
    return None


def _prepare_headers(request: Request) -> tuple[dict[str, str], Optional[Response]]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP
    }

    auth_header = _get_auth_header()
    if auth_header:
        headers["Authorization"] = auth_header
        return headers, None

    if "authorization" in {key.lower() for key in headers}:
        return headers, None

    return headers, JSONResponse(
        status_code=503,
        content={
            "detail": "未配置可用于 Codex 的激活凭证，请为激活账号添加 API Key 或 access token。",
        },
    )


async def proxy_request(request: Request) -> Response:
    path = request.url.path
    query = request.url.query
    url = f"{UPSTREAM}{path}"
    if query:
        url = f"{url}?{query}"

    headers, error_response = _prepare_headers(request)
    if error_response is not None:
        return error_response

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            upstream_resp = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
            )
    except httpx.HTTPError as exc:
        logger.exception("OpenAI 上游请求失败: %s", exc)
        return JSONResponse(status_code=502, content={"detail": f"OpenAI 上游请求失败: {exc}"})

    response_headers = {
        key: value
        for key, value in upstream_resp.headers.items()
        if key.lower() not in {"content-encoding", "transfer-encoding", "connection"}
    }

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=response_headers,
        media_type=upstream_resp.headers.get("content-type"),
    )


async def proxy_stream_request(request: Request) -> Response:
    path = request.url.path
    query = request.url.query
    url = f"{UPSTREAM}{path}"
    if query:
        url = f"{url}?{query}"

    headers, error_response = _prepare_headers(request)
    if error_response is not None:
        return error_response

    body = await request.body()

    async def _stream():
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                async with client.stream(
                    method=request.method,
                    url=url,
                    headers=headers,
                    content=body,
                ) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except httpx.HTTPError as exc:
            logger.exception("OpenAI 上游流式请求失败: %s", exc)
            yield (
                b'data: {"error": {"message": "OpenAI \xe4\xb8\x8a\xe6\xb8\xb8\xe6\xb5\x81\xe5\xbc\x8f\xe8\xaf\xb7\xe6\xb1\x82\xe5\xa4\xb1\xe8\xb4\xa5"}}\n\n'
            )

    return StreamingResponse(_stream(), media_type="text/event-stream")
