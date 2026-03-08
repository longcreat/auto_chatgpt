"""Token 管理 API"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import Account, Token, get_db
from app.schemas import MessageResponse, TokenCreate, TokenOut, TokenUpdate
from app.serializers import serialize_token
from app.services import codex_service
from app.services.credential_service import sync_account_credentials


router = APIRouter(prefix="/api/tokens", tags=["Tokens"])


def _reload_active_cache() -> None:
    codex_service.reload_active_account()


@router.get("", response_model=List[TokenOut])
def list_tokens(account_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Token)
    if account_id is not None:
        query = query.filter(Token.account_id == account_id)
    tokens = query.order_by(Token.created_at.desc()).all()
    return [serialize_token(token) for token in tokens]


@router.post("", response_model=TokenOut)
def create_token(body: TokenCreate, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == body.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    token = Token(**body.model_dump())
    db.add(token)
    db.commit()
    db.refresh(token)

    if sync_account_credentials(db, account):
        account.updated_at = datetime.utcnow()
        db.commit()

    _reload_active_cache()
    return serialize_token(token)


@router.patch("/{token_id}", response_model=TokenOut)
def update_token(token_id: int, body: TokenUpdate, db: Session = Depends(get_db)):
    token = db.query(Token).filter(Token.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Token 不存在")

    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(token, key, value)
    token.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(token)

    account = db.query(Account).filter(Account.id == token.account_id).first()
    if account and sync_account_credentials(db, account):
        account.updated_at = datetime.utcnow()
        db.commit()

    _reload_active_cache()
    return serialize_token(token)


@router.delete("/{token_id}", response_model=MessageResponse)
def delete_token(token_id: int, db: Session = Depends(get_db)):
    token = db.query(Token).filter(Token.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Token 不存在")

    account_id = token.account_id
    db.delete(token)
    db.commit()

    account = db.query(Account).filter(Account.id == account_id).first()
    if account and sync_account_credentials(db, account):
        account.updated_at = datetime.utcnow()
        db.commit()

    _reload_active_cache()
    return {"message": "Token 已删除"}


@router.post("/invalidate-expired", response_model=MessageResponse)
def invalidate_expired(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    expired_tokens = db.query(Token).filter(
        Token.expires_at.is_not(None),
        Token.expires_at < now,
        Token.is_valid.is_(True),
    ).all()

    for token in expired_tokens:
        token.is_valid = False
        token.updated_at = now

    affected_account_ids = {token.account_id for token in expired_tokens}
    db.commit()

    changed = False
    for account_id in affected_account_ids:
        account = db.query(Account).filter(Account.id == account_id).first()
        if account and sync_account_credentials(db, account):
            account.updated_at = now
            changed = True

    if changed:
        db.commit()

    _reload_active_cache()
    return {"message": f"已标记 {len(expired_tokens)} 个过期 Token 为无效"}
