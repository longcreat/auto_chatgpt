"""账号管理 API"""

import random
import string
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import Account, RegistrationTask, get_db
from app.schemas import (
    AccountCreate,
    AccountOut,
    AccountSwitchRequest,
    AccountUpdate,
    MessageResponse,
    RegistrationRequest,
    RegistrationTaskOut,
)
from app.serializers import serialize_account
from app.services import codex_service
from app.services.registration_task_service import registration_task_manager
from app.services.settings_service import get_domain_name
from app.services.token_service import replace_account_tokens


router = APIRouter(prefix="/api/accounts", tags=["Accounts"])


def _random_domain_email() -> str:
    prefix = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    domain = get_domain_name()
    return f"{prefix}@{domain}"


def _access_token_expires_at(result: dict) -> datetime | None:
    from app.services import registration_service

    return registration_service.oauth_access_token_expires_at(result)


def _normalize_emails(body: RegistrationRequest) -> list[str]:
    emails_to_register: list[str] = []

    for email in body.emails:
        email_value = email.strip()
        if email_value:
            emails_to_register.append(email_value)

    if body.email:
        email_value = body.email.strip()
        if email_value:
            emails_to_register.append(email_value)

    if emails_to_register:
        seen: set[str] = set()
        unique_emails: list[str] = []
        for email in emails_to_register:
            if email not in seen:
                seen.add(email)
                unique_emails.append(email)
        return unique_emails

    if body.use_domain_email:
        domain = get_domain_name()
        if not domain:
            raise HTTPException(status_code=400, detail="请先在「系统配置」中配置域名")
        for _ in range(body.count):
            emails_to_register.append(_random_domain_email())
        return emails_to_register

    raise HTTPException(status_code=400, detail="请提供邮箱或启用域名邮箱")


def _create_registration_task(db: Session, email: str) -> RegistrationTask:
    existing_account = db.query(Account).filter(Account.email == email).first()
    if existing_account:
        raise HTTPException(status_code=400, detail=f"邮箱 {email} 已注册，不能重复创建任务")

    existing_task = db.query(RegistrationTask).filter(RegistrationTask.email == email).first()
    if existing_task:
        if existing_task.status in ("queued", "running"):
            return existing_task
        existing_task.status = "queued"
        existing_task.account_id = None
        existing_task.log = f"[{datetime.now().strftime('%H:%M:%S')}] 任务已重置，重新开始注册。"
        existing_task.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing_task)
        registration_task_manager.enqueue(existing_task.id)
        return existing_task

    task = RegistrationTask(email=email, status="queued")
    db.add(task)
    db.commit()
    db.refresh(task)
    registration_task_manager.enqueue(task.id)
    return task


@router.get("", response_model=List[AccountOut])
def list_accounts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    accounts = db.query(Account).offset(skip).limit(limit).all()
    return [serialize_account(account) for account in accounts]


@router.get("/tasks", response_model=List[RegistrationTaskOut])
def list_tasks(db: Session = Depends(get_db)):
    return (
        db.query(RegistrationTask)
        .order_by(RegistrationTask.updated_at.desc(), RegistrationTask.created_at.desc())
        .limit(100)
        .all()
    )


@router.get("/tasks/{task_id}", response_model=RegistrationTaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(RegistrationTask).filter(RegistrationTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    return serialize_account(account)


@router.post("", response_model=AccountOut)
def create_account(body: AccountCreate, db: Session = Depends(get_db)):
    existing = db.query(Account).filter(Account.email == body.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="邮箱已存在")

    account = Account(**body.model_dump())
    account.status = "active"
    db.add(account)
    db.commit()
    db.refresh(account)
    codex_service.reload_active_account()
    return serialize_account(account)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, body: AccountUpdate, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    payload = body.model_dump(exclude_unset=True)
    api_key = payload.pop("api_key", None) if "api_key" in body.model_fields_set else None
    for key, value in payload.items():
        setattr(account, key, value)

    if "api_key" in body.model_fields_set:
        account.api_key = api_key or None
        replace_account_tokens(db, account, {"api_key": (api_key or None, None)})

    account.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(account)
    codex_service.reload_active_account()
    return serialize_account(account)


@router.delete("/{account_id}", response_model=MessageResponse)
def delete_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    db.delete(account)
    db.commit()
    codex_service.reload_active_account()
    return {"message": "账号已删除"}


@router.post("/switch", response_model=MessageResponse)
def switch_account(body: AccountSwitchRequest):
    ok = codex_service.switch_to_account(body.account_id)
    if not ok:
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"message": f"已切换到账号 ID {body.account_id}"}


@router.post("/{account_id}/refresh-token", response_model=MessageResponse)
async def refresh_token(account_id: int, db: Session = Depends(get_db)):
    import asyncio
    from app.services import registration_service

    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    # refresh_session_token 是同步函数, 通过 to_thread 避免阻塞事件循环
    token = await asyncio.to_thread(
        registration_service.refresh_session_token, account.email, account.password
    )
    if not token:
        raise HTTPException(status_code=500, detail="Token 刷新失败")

    account.session_token = token
    account.updated_at = datetime.utcnow()
    replace_account_tokens(db, account, {"session_token": (token, None)})
    db.commit()
    codex_service.reload_active_account()
    return {"message": "Token 刷新成功"}


@router.post("/{account_id}/fetch-token", response_model=MessageResponse)
async def fetch_account_token(account_id: int, db: Session = Depends(get_db)):
    """为已注册但缺少 Token 的账号补充获取 OAuth Token"""
    import asyncio
    from app.services import registration_service

    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if not account.password:
        raise HTTPException(status_code=400, detail="账号缺少密码, 无法获取 Token")

    log_lines: list[str] = []
    result = await asyncio.to_thread(
        registration_service.fetch_tokens_for_account,
        account.email, account.password, log_lines,
    )

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error") or "Token 获取失败")

    # 更新 Account
    account.access_token = result.get("access_token")
    account.token_expires_at = _access_token_expires_at(result)
    account.updated_at = datetime.utcnow()

    replace_account_tokens(
        db,
        account,
        {
            "access_token": (result.get("access_token"), _access_token_expires_at(result)),
            "refresh_token": (result.get("refresh_token"), None),
            "id_token": (result.get("id_token"), None),
        },
    )

    db.commit()
    codex_service.reload_active_account()
    return {"message": "Token 获取成功"}


@router.post("/register", response_model=List[RegistrationTaskOut])
async def auto_register(
    body: RegistrationRequest,
    db: Session = Depends(get_db),
):
    emails_to_register = _normalize_emails(body)
    tasks = []
    for email in emails_to_register:
        tasks.append(_create_registration_task(db, email))

    return tasks


@router.post("/tasks/{task_id}/retry", response_model=RegistrationTaskOut)
def retry_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(RegistrationTask).filter(RegistrationTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "failed":
        raise HTTPException(status_code=400, detail="仅失败任务支持重试")
    existing_account = db.query(Account).filter(Account.email == task.email).first()
    if existing_account:
        raise HTTPException(status_code=400, detail=f"邮箱 {task.email} 已注册，不能重复创建任务")
    task.status = "queued"
    task.account_id = None
    task.log = f"[{datetime.now().strftime('%H:%M:%S')}] 手动重试，重新开始注册。"
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    registration_task_manager.enqueue(task.id)
    return task
