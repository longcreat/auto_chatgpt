"""系统配置 API"""

import imaplib
import logging

from fastapi import APIRouter

from app.schemas import MessageResponse, SystemConfigOut, SystemConfigUpdate
from app.services import settings_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["Settings"])


@router.get("", response_model=SystemConfigOut, summary="获取系统配置")
def get_settings():
    return settings_service.get_config()


@router.put("", response_model=SystemConfigOut, summary="更新系统配置")
def update_settings(body: SystemConfigUpdate):
    data = body.model_dump(exclude_unset=True)
    return settings_service.update_config(data)


@router.post("/test-imap", response_model=MessageResponse, summary="测试 IMAP 连接")
def test_imap_connection(body: SystemConfigUpdate):
    """用提交的参数测试 IMAP 连接（不保存）"""
    cfg = settings_service.get_config()
    host = body.imap_host or cfg["imap_host"]
    port = body.imap_port or cfg["imap_port"]
    user = body.imap_user or cfg["imap_user"]
    password = body.imap_password or cfg["imap_password"]

    if not host or not user or not password:
        return {"message": "IMAP 配置不完整", "success": False}

    imap = None
    selected = False
    try:
        imap = imaplib.IMAP4_SSL(host, port)
        imap.login(user, password)

        # 163/126/yeah.net 需要在 SELECT 前发送 ID 命令
        try:
            imaplib.Commands["ID"] = ("AUTH", "SELECTED")
            imap._simple_command(
                "ID",
                '("name" "AutoChatGPT" "version" "1.0" "vendor" "AutoChatGPT")',
            )
        except Exception:
            pass

        typ, _ = imap.select("INBOX")
        selected = (typ == "OK")

        return {"message": f"IMAP 连接成功 ({user}@{host}:{port})", "success": True}
    except Exception as exc:
        logger.warning("[Settings] IMAP 测试失败: %s", exc)
        return {"message": f"IMAP 连接失败: {exc}", "success": False}
    finally:
        if imap:
            try:
                if selected:
                    imap.close()
                imap.logout()
            except Exception:
                pass


@router.post("/test-proxy", response_model=MessageResponse, summary="测试代理连接")
def test_proxy_connection(body: SystemConfigUpdate):
    """用提交的参数测试代理连通性"""
    cfg = settings_service.get_config()
    host = body.proxy_host or cfg["proxy_host"]
    port = body.proxy_port or cfg["proxy_port"]

    if not host or not port:
        return {"message": "代理未配置", "success": False}

    user = body.proxy_user if body.proxy_user is not None else cfg["proxy_user"]
    pwd = body.proxy_pass if body.proxy_pass is not None else cfg["proxy_pass"]

    proxy_url = f"http://{user}:{pwd}@{host}:{port}" if user else f"http://{host}:{port}"

    try:
        import httpx
        with httpx.Client(proxy=proxy_url, timeout=10) as client:
            resp = client.get("https://httpbin.org/ip")
            ip = resp.json().get("origin", "unknown")
        return {"message": f"代理连接成功, 出口 IP: {ip}", "success": True}
    except Exception as exc:
        logger.warning("[Settings] 代理测试失败: %s", exc)
        return {"message": f"代理连接失败: {exc}", "success": False}
