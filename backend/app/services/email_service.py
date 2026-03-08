"""
Cloudflare Email Routing 服务
- 在启用显式 routing rule 模式时创建、列出、删除规则
- catch-all 模式下不需要此服务
"""

from typing import Optional
import random
import string

import httpx

from app.config import settings


CF_API_BASE = "https://api.cloudflare.com/client/v4"


def _require_cloudflare_config() -> tuple[str, str, str]:
    token = settings.CF_API_TOKEN
    zone_id = settings.CF_ZONE_ID
    forward_to = settings.CF_EMAIL_FORWARD_TO or settings.IMAP_USER
    if token and zone_id and forward_to:
        return token, zone_id, forward_to
    raise RuntimeError("Cloudflare Email Routing API 未配置，当前项目默认使用 catch-all 模式。")


def _headers() -> dict[str, str]:
    token, _, _ = _require_cloudflare_config()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _random_alias(length: int = 10) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=length))


async def create_email_alias(custom_prefix: Optional[str] = None) -> dict:
    _, zone_id, forward_to = _require_cloudflare_config()
    prefix = custom_prefix or _random_alias()
    alias = f"{prefix}@{settings.DOMAIN_NAME}"

    payload = {
        "actions": [{"type": "forward", "value": [forward_to]}],
        "enabled": True,
        "matchers": [{"field": "to", "type": "literal", "value": alias}],
        "name": f"AutoChatGPT-{prefix}",
        "priority": 0,
    }

    url = f"{CF_API_BASE}/zones/{zone_id}/email/routing/rules"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=_headers(), json=payload)
        response.raise_for_status()
        data = response.json()

    rule = data["result"]
    return {"alias": alias, "rule_tag": rule.get("tag")}


async def delete_email_alias(rule_tag: str) -> bool:
    _, zone_id, _ = _require_cloudflare_config()
    url = f"{CF_API_BASE}/zones/{zone_id}/email/routing/rules/{rule_tag}"
    async with httpx.AsyncClient() as client:
        response = await client.delete(url, headers=_headers())
    return response.status_code == 200


async def list_email_aliases() -> list:
    _, zone_id, _ = _require_cloudflare_config()
    url = f"{CF_API_BASE}/zones/{zone_id}/email/routing/rules"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers())
        response.raise_for_status()
    return response.json().get("result", [])


async def verify_cloudflare_config() -> dict:
    try:
        _, zone_id, forward_to = _require_cloudflare_config()
        url = f"{CF_API_BASE}/zones/{zone_id}/email/routing"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=_headers())
        data = response.json()
        return {
            "ok": response.status_code == 200,
            "enabled": data.get("result", {}).get("enabled", False),
            "domain": settings.DOMAIN_NAME,
            "forward_to": forward_to,
        }
    except Exception as exc:
        return {"ok": False, "enabled": False, "error": str(exc)}
