"""
OpenClaw OAuth 回调 URL 获取路由

POST /api/oauth/openclaw           → 启动 HTTP 登录流程，返回 task_id
GET  /api/oauth/openclaw/{task_id} → 轮询结果
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.openclaw_oauth_service import start_openclaw_task, get_task_result

router = APIRouter(prefix="/api/oauth", tags=["OAuth Capture"])


class OpenClawRequest(BaseModel):
    auth_url: str
    account_id: int


class OpenClawResult(BaseModel):
    status: str          # running | done | error
    callback_url: Optional[str] = None
    error: Optional[str] = None
    log: Optional[list] = None


@router.post("/openclaw")
def start_openclaw_oauth(req: OpenClawRequest):
    """
    启动 OpenClaw OAuth 流程。

    使用指定账号的邮箱 + 密码执行纯 HTTP OAuth 登录，
    捕获完整的 callback URL 后返回。
    """
    auth_url = req.auth_url.strip()
    if not auth_url.startswith("http"):
        raise HTTPException(status_code=400, detail="auth_url 格式无效")

    try:
        task_id = start_openclaw_task(auth_url=auth_url, account_id=req.account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"task_id": task_id, "message": "OAuth 流程已启动，请轮询结果"}


@router.get("/openclaw/{task_id}")
def get_openclaw_result(task_id: str) -> OpenClawResult:
    """轮询 OpenClaw OAuth 任务结果。"""
    task = get_task_result(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task 不存在或已过期")
    return OpenClawResult(
        status=task["status"],
        callback_url=task.get("callback_url"),
        error=task.get("error"),
        log=task.get("log"),
    )

