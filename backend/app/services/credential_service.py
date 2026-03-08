from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.database import Account, Token


def _token_query(db: Session, account_id: int, token_type: str):
    return db.query(Token).filter(
        Token.account_id == account_id,
        Token.token_type == token_type,
    )


def _has_token_records(db: Session, account_id: int, token_type: str) -> bool:
    return _token_query(db, account_id, token_type).first() is not None


def _latest_valid_token(db: Session, account_id: int, token_type: str) -> Optional[Token]:
    query = _token_query(db, account_id, token_type).filter(Token.is_valid.is_(True))
    if token_type == "access_token":
        now = datetime.utcnow()
        query = query.filter((Token.expires_at.is_(None)) | (Token.expires_at > now))
    return query.order_by(Token.updated_at.desc(), Token.created_at.desc(), Token.id.desc()).first()


def sync_account_credentials(db: Session, account: Account) -> bool:
    changed = False

    api_key = _latest_valid_token(db, account.id, "api_key")
    if api_key or _has_token_records(db, account.id, "api_key"):
        new_value = api_key.token_value if api_key else None
        if account.api_key != new_value:
            account.api_key = new_value
            changed = True

    access_token = _latest_valid_token(db, account.id, "access_token")
    if access_token or _has_token_records(db, account.id, "access_token"):
        new_token = access_token.token_value if access_token else None
        new_expires_at = access_token.expires_at if access_token else None
        if account.access_token != new_token:
            account.access_token = new_token
            changed = True
        if account.token_expires_at != new_expires_at:
            account.token_expires_at = new_expires_at
            changed = True

    session_token = _latest_valid_token(db, account.id, "session_token")
    if session_token or _has_token_records(db, account.id, "session_token"):
        new_value = session_token.token_value if session_token else None
        if account.session_token != new_value:
            account.session_token = new_value
            changed = True

    return changed
