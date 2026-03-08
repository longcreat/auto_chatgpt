from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.database import Account, Token
from app.services.credential_service import sync_account_credentials


def cleanup_token_store(db: Session, account_id: Optional[int] = None) -> int:
    """
    清理 token 存储:
    - 删除过期 token
    - 删除无效 token
    - 同一账号同一类型仅保留最新一条有效 token
    """
    now = datetime.utcnow()
    query = db.query(Token)
    if account_id is not None:
        query = query.filter(Token.account_id == account_id)

    tokens = query.order_by(
        Token.account_id.asc(),
        Token.token_type.asc(),
        Token.updated_at.desc(),
        Token.created_at.desc(),
        Token.id.desc(),
    ).all()

    seen_keys: set[tuple[int, str]] = set()
    deleted = 0
    affected_account_ids: set[int] = set()

    for token in tokens:
        is_expired = bool(token.expires_at and token.expires_at < now)
        key = (token.account_id, token.token_type)
        should_keep = token.is_valid and not is_expired and key not in seen_keys
        if should_keep:
            seen_keys.add(key)
            continue

        affected_account_ids.add(token.account_id)
        db.delete(token)
        deleted += 1

    if deleted:
        db.flush()
        for current_account_id in affected_account_ids:
            account = db.query(Account).filter(Account.id == current_account_id).first()
            if account and sync_account_credentials(db, account):
                account.updated_at = now
        db.flush()

    return deleted


def replace_account_tokens(
    db: Session,
    account: Account,
    token_values: dict[str, tuple[Optional[str], Optional[datetime]]],
) -> None:
    """
    覆盖写入某个账号的一组 token 类型，只保留最新记录。
    token_values: {token_type: (token_value, expires_at)}
    """
    token_types = list(token_values.keys())
    if not token_types:
        return

    now = datetime.utcnow()
    db.query(Token).filter(
        Token.account_id == account.id,
        Token.token_type.in_(token_types),
    ).delete(synchronize_session=False)

    for token_type, (token_value, expires_at) in token_values.items():
        if not token_value:
            continue
        db.add(
            Token(
                account_id=account.id,
                token_type=token_type,
                token_value=token_value,
                expires_at=expires_at,
                is_valid=True,
            )
        )

    db.flush()
    if sync_account_credentials(db, account):
        account.updated_at = now
    db.flush()
