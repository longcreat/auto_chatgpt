from typing import Any, Optional

from app.database import Account, Token


def mask_secret(value: Optional[str], prefix: int = 8, suffix: int = 4) -> Optional[str]:
    if not value:
        return None
    if len(value) <= prefix + suffix:
        return "*" * len(value)
    return f"{value[:prefix]}...{value[-suffix:]}"


def serialize_token(token: Token) -> dict[str, Any]:
    return {
        "id": token.id,
        "account_id": token.account_id,
        "token_type": token.token_type,
        "token_preview": mask_secret(token.token_value),
        "expires_at": token.expires_at,
        "is_valid": token.is_valid,
        "created_at": token.created_at,
        "updated_at": token.updated_at,
    }


def serialize_account(account: Account) -> dict[str, Any]:
    return {
        "id": account.id,
        "email": account.email,
        "username": account.username,
        "cf_email_alias": account.cf_email_alias,
        "status": account.status,
        "is_active": account.is_active,
        "has_api_key": bool(account.api_key),
        "api_key_preview": mask_secret(account.api_key),
        "has_access_token": bool(account.access_token),
        "token_expires_at": account.token_expires_at,
        "notes": account.notes,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
        "last_used_at": account.last_used_at,
    }
