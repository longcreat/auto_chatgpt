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
from app.services.token_service import cleanup_token_store, replace_account_tokens


router = APIRouter(prefix="/api/tokens", tags=["Tokens"])


def _reload_active_cache() -> None:
    codex_service.reload_active_account()


@router.get("", response_model=List[TokenOut])
def list_tokens(account_id: Optional[int] = None, db: Session = Depends(get_db)):
    deleted = cleanup_token_store(db, account_id=account_id)
    if deleted:
        db.commit()

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

    replace_account_tokens(
        db,
        account,
        {body.token_type: (body.token_value, body.expires_at)},
    )
    db.commit()

    token = db.query(Token).filter(
        Token.account_id == body.account_id,
        Token.token_type == body.token_type,
    ).order_by(Token.created_at.desc(), Token.id.desc()).first()
    if not token:
        raise HTTPException(status_code=500, detail="Token 保存失败")

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
    deleted = cleanup_token_store(db)
    db.commit()

    _reload_active_cache()
    return {"message": f"已清理 {deleted} 条过期或旧 Token"}
