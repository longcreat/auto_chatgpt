import base64
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import Account, Token


AUTH_FILE = Path.home() / ".codex" / "auth.json"


def _resolve_auth_file(auth_file: Optional[Path] = None) -> Path:
    return (auth_file or AUTH_FILE).expanduser().resolve()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso8601(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _decode_jwt_payload(token: Optional[str]) -> dict[str, Any]:
    if not token:
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload.encode("utf-8"))
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_auth_payload(auth_file: Optional[Path] = None) -> tuple[Path, Optional[dict[str, Any]], Optional[str]]:
    path = _resolve_auth_file(auth_file)
    if not path.exists():
        return path, None, None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return path, None, str(exc)

    if not isinstance(data, dict):
        return path, None, "auth.json is not a JSON object"
    return path, data, None


def _write_auth_payload(payload: dict[str, Any], auth_file: Optional[Path] = None) -> tuple[Path, Optional[Path]]:
    path = _resolve_auth_file(auth_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    backup_path = None
    if path.exists():
        timestamp = _now_utc().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_name(f"{path.name}.auto_chatgpt.{timestamp}.bak")
        shutil.copy2(path, backup_path)

    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return path, backup_path


def _latest_valid_token(db: Session, account_id: int, token_type: str) -> Optional[str]:
    query = db.query(Token).filter(
        Token.account_id == account_id,
        Token.token_type == token_type,
        Token.is_valid.is_(True),
    )
    if token_type == "access_token":
        now = datetime.utcnow()
        query = query.filter(or_(Token.expires_at.is_(None), Token.expires_at > now))
    token = query.order_by(Token.updated_at.desc(), Token.created_at.desc(), Token.id.desc()).first()
    return token.token_value if token else None


def _build_plugin_status(path: Path, payload: Optional[dict[str, Any]], parse_error: Optional[str]) -> dict[str, Any]:
    result = {
        "auth_file": str(path),
        "exists": path.exists(),
        "auth_mode": None,
        "email": None,
        "plugin_account_id": None,
        "plan_type": None,
        "has_openai_api_key": False,
        "has_access_token": False,
        "has_refresh_token": False,
        "has_id_token": False,
        "access_token_expires_at": None,
        "last_refresh": None,
        "warning": None,
    }
    if parse_error:
        result["warning"] = f"auth.json 解析失败: {parse_error}"
        return result
    if not payload:
        result["warning"] = "未找到 Codex 本地认证文件"
        return result

    result["auth_mode"] = payload.get("auth_mode")
    result["has_openai_api_key"] = bool(payload.get("OPENAI_API_KEY") or payload.get("CODEX_API_KEY"))
    result["last_refresh"] = _parse_datetime(payload.get("last_refresh"))

    tokens = payload.get("tokens")
    if isinstance(tokens, dict):
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        id_token = tokens.get("id_token")
        result["has_access_token"] = bool(access_token)
        result["has_refresh_token"] = bool(refresh_token)
        result["has_id_token"] = bool(id_token)

        access_payload = _decode_jwt_payload(access_token)
        auth_claims = access_payload.get("https://api.openai.com/auth") or {}
        profile_claims = access_payload.get("https://api.openai.com/profile") or {}
        exp = access_payload.get("exp")

        result["email"] = profile_claims.get("email")
        result["plugin_account_id"] = tokens.get("account_id") or auth_claims.get("chatgpt_account_id")
        result["plan_type"] = auth_claims.get("chatgpt_plan_type")
        if isinstance(exp, (int, float)):
            result["access_token_expires_at"] = datetime.fromtimestamp(exp, timezone.utc)

    if result["auth_mode"] == "chatgpt" and not result["has_refresh_token"]:
        result["warning"] = "当前插件为 ChatGPT 模式，但缺少 refresh_token"
    elif result["auth_mode"] == "chatgpt" and not result["has_id_token"]:
        result["warning"] = "当前插件缺少 id_token，但通常不影响 access_token/refresh_token 登录"
    elif result["auth_mode"] != "chatgpt" and result["has_openai_api_key"]:
        result["warning"] = "当前插件使用 API Key 模式，不是 ChatGPT 登录态"

    return result


def get_plugin_status(auth_file: Optional[Path] = None) -> dict[str, Any]:
    path, payload, parse_error = _read_auth_payload(auth_file)
    return _build_plugin_status(path, payload, parse_error)


def switch_plugin_account(
    db: Session,
    account: Account,
    auth_file: Optional[Path] = None,
) -> dict[str, Any]:
    access_token = _latest_valid_token(db, account.id, "access_token") or account.access_token
    refresh_token = _latest_valid_token(db, account.id, "refresh_token")

    if not access_token:
        raise ValueError("账号缺少可用 access_token，无法写入 Codex 插件登录态")
    if not refresh_token:
        raise ValueError("账号缺少可用 refresh_token，无法写入 Codex 插件登录态")

    access_payload = _decode_jwt_payload(access_token)
    auth_claims = access_payload.get("https://api.openai.com/auth") or {}
    profile_claims = access_payload.get("https://api.openai.com/profile") or {}
    plugin_account_id = auth_claims.get("chatgpt_account_id")
    if not plugin_account_id:
        raise ValueError("access_token 中缺少 chatgpt_account_id，无法切换插件登录态")

    path, existing_payload, _ = _read_auth_payload(auth_file)
    existing_tokens = existing_payload.get("tokens") if isinstance(existing_payload, dict) else None
    current_id_token = existing_tokens.get("id_token") if isinstance(existing_tokens, dict) else None
    current_id_payload = _decode_jwt_payload(current_id_token)
    current_email = current_id_payload.get("email")

    id_token = current_id_token if current_email == account.email else None
    payload = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": id_token,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "account_id": plugin_account_id,
        },
        "last_refresh": _to_iso8601(_now_utc()),
    }

    path, backup_path = _write_auth_payload(payload, auth_file)
    warning = None
    if not id_token:
        warning = "未找到匹配账号的 id_token，已仅写入 access_token/refresh_token；如界面未立即刷新，可重载 VS Code 窗口。"

    return {
        "success": True,
        "message": f"已写入 Codex 插件登录态: {account.email}",
        "db_account_id": account.id,
        "email": profile_claims.get("email") or account.email,
        "plugin_account_id": plugin_account_id,
        "auth_file": str(path),
        "backup_file": str(backup_path) if backup_path else None,
        "requires_reload": bool(warning),
        "warning": warning,
    }
