"""
Codex 集成 API
- 查看当前激活账号
- 切换激活账号
- 代理所有 OpenAI API 请求（挂载在 /v1/*）
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Account, get_db
from app.schemas import AccountSwitchRequest, CodexStatusOut, CodexSwitchResult
from app.serializers import mask_secret
from app.services import codex_service


router = APIRouter(tags=["Codex"])


@router.get("/api/codex/status", response_model=CodexStatusOut)
def codex_status():
    info = codex_service.get_active_account_info()
    return CodexStatusOut(
        active_account_id=info.get("account_id"),
        active_email=info.get("email"),
        api_key_preview=mask_secret(info.get("api_key")),
        proxy_url=settings.codex_proxy_url,
        token_valid=bool(info.get("api_key") or info.get("access_token")),
    )


@router.post("/api/codex/switch", response_model=CodexSwitchResult)
def codex_switch(body: AccountSwitchRequest, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == body.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    if not codex_service.switch_to_account(body.account_id):
        return CodexSwitchResult(success=False, message="切换失败")

    return CodexSwitchResult(
        success=True,
        message=f"已切换到 {account.email}",
        account_id=account.id,
        email=account.email,
    )


@router.post("/api/codex/reload")
def codex_reload():
    codex_service.reload_active_account()
    return {"message": "已重新加载激活账号"}


@router.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def openai_proxy(path: str, request: Request):
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return await codex_service.proxy_stream_request(request)
    return await codex_service.proxy_request(request)
