from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AccountCreate(BaseModel):
    email: str
    password: str
    username: Optional[str] = None
    notes: Optional[str] = None


class AccountUpdate(BaseModel):
    password: Optional[str] = None
    username: Optional[str] = None
    status: Optional[str] = None
    api_key: Optional[str] = None
    notes: Optional[str] = None


class TokenOut(BaseModel):
    id: int
    account_id: int
    token_type: str
    token_preview: Optional[str]
    expires_at: Optional[datetime]
    is_valid: bool
    created_at: datetime
    updated_at: datetime


class AccountOut(BaseModel):
    id: int
    email: str
    username: Optional[str]
    cf_email_alias: Optional[str]
    status: str
    is_active: bool
    has_api_key: bool
    api_key_preview: Optional[str]
    has_access_token: bool = False
    token_expires_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    last_used_at: Optional[datetime]


class AccountSwitchRequest(BaseModel):
    account_id: int


class TokenCreate(BaseModel):
    account_id: int
    token_type: str
    token_value: str
    expires_at: Optional[datetime] = None


class TokenUpdate(BaseModel):
    token_value: Optional[str] = None
    expires_at: Optional[datetime] = None
    is_valid: Optional[bool] = None


class EmailAliasOut(BaseModel):
    id: int
    alias: str
    forward_to: str
    is_used: bool
    account_id: Optional[int]
    created_at: datetime


class GenerateAliasRequest(BaseModel):
    count: int = 1


class RegistrationRequest(BaseModel):
    email: Optional[str] = None
    use_domain_email: bool = True
    count: int = 1
    proxy: Optional[str] = None


class RegistrationTaskOut(BaseModel):
    id: int
    email: str
    status: str
    log: Optional[str]
    account_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class CodexStatusOut(BaseModel):
    active_account_id: Optional[int]
    active_email: Optional[str]
    api_key_preview: Optional[str]
    proxy_url: str
    token_valid: bool


class CodexSwitchResult(BaseModel):
    success: bool
    message: str
    account_id: Optional[int] = None
    email: Optional[str] = None


class CodexPluginStatusOut(BaseModel):
    auth_file: str
    exists: bool
    auth_mode: Optional[str] = None
    email: Optional[str] = None
    plugin_account_id: Optional[str] = None
    plan_type: Optional[str] = None
    has_openai_api_key: bool = False
    has_access_token: bool = False
    has_refresh_token: bool = False
    has_id_token: bool = False
    access_token_expires_at: Optional[datetime] = None
    last_refresh: Optional[datetime] = None
    warning: Optional[str] = None


class CodexPluginSwitchResult(BaseModel):
    success: bool
    message: str
    db_account_id: int
    email: str
    plugin_account_id: Optional[str] = None
    auth_file: str
    backup_file: Optional[str] = None
    requires_reload: bool = False
    warning: Optional[str] = None


class MessageResponse(BaseModel):
    message: str
    success: bool = True


# ─── 系统配置 ───────────────────────────────────────────────

class SystemConfigOut(BaseModel):
    domain_name: str = ""
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    proxy_host: str = ""
    proxy_port: int = 0
    proxy_user: str = ""
    proxy_pass: str = ""


class SystemConfigUpdate(BaseModel):
    domain_name: Optional[str] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    imap_user: Optional[str] = None
    imap_password: Optional[str] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_user: Optional[str] = None
    proxy_pass: Optional[str] = None
