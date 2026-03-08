"""
系统配置服务
- 从 system_config 表读取配置（单行）
- 带内存缓存，避免频繁查库
- 首次启动时自动从 .env 迁移旧配置
"""

import threading
import logging
from typing import Optional

from app.config import settings as env_settings
from app.database import SessionLocal, SystemConfig

logger = logging.getLogger(__name__)

_cache: Optional[dict] = None
_lock = threading.Lock()


def _row_to_dict(row: SystemConfig) -> dict:
    return {
        "domain_name": row.domain_name or "",
        "imap_host": row.imap_host or "",
        "imap_port": row.imap_port or 993,
        "imap_user": row.imap_user or "",
        "imap_password": row.imap_password or "",
        "proxy_host": row.proxy_host or "",
        "proxy_port": row.proxy_port or 0,
        "proxy_user": row.proxy_user or "",
        "proxy_pass": row.proxy_pass or "",
    }


def _ensure_row(db) -> SystemConfig:
    """确保 system_config 表有且仅有一行，没有则从 .env 迁移"""
    row = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if row:
        return row

    # 首次启动：从 .env 迁移
    logger.info("[Settings] 首次启动，将 .env 配置迁移到数据库...")
    row = SystemConfig(
        id=1,
        domain_name=env_settings.DOMAIN_NAME or "",
        imap_host=env_settings.IMAP_HOST or "",
        imap_port=env_settings.IMAP_PORT or 993,
        imap_user=env_settings.IMAP_USER or "",
        imap_password=env_settings.IMAP_PASSWORD or "",
        proxy_host=env_settings.PROXY_HOST or "",
        proxy_port=env_settings.PROXY_PORT or 0,
        proxy_user=env_settings.PROXY_USER or "",
        proxy_pass=env_settings.PROXY_PASS or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("[Settings] 迁移完成: domain=%s, imap=%s@%s",
                row.domain_name, row.imap_user, row.imap_host)
    return row


def get_config() -> dict:
    """获取系统配置（带缓存）"""
    global _cache
    if _cache is not None:
        return dict(_cache)

    with _lock:
        if _cache is not None:
            return dict(_cache)
        db = SessionLocal()
        try:
            row = _ensure_row(db)
            _cache = _row_to_dict(row)
            return dict(_cache)
        finally:
            db.close()


def update_config(data: dict) -> dict:
    """更新系统配置"""
    global _cache
    db = SessionLocal()
    try:
        row = _ensure_row(db)
        for key in ("domain_name", "imap_host", "imap_port", "imap_user",
                     "imap_password", "proxy_host", "proxy_port", "proxy_user", "proxy_pass"):
            if key in data:
                setattr(row, key, data[key])
        db.commit()
        db.refresh(row)
        with _lock:
            _cache = _row_to_dict(row)
        logger.info("[Settings] 配置已更新")
        return dict(_cache)
    finally:
        db.close()


def invalidate_cache():
    """清除缓存，下次调用 get_config() 重新查库"""
    global _cache
    with _lock:
        _cache = None


def get_domain_name() -> str:
    return get_config().get("domain_name", "")


def get_imap_config() -> dict:
    cfg = get_config()
    return {
        "host": cfg["imap_host"],
        "port": cfg["imap_port"],
        "user": cfg["imap_user"],
        "password": cfg["imap_password"],
    }


def get_proxy_url() -> Optional[str]:
    cfg = get_config()
    host = cfg.get("proxy_host", "")
    port = cfg.get("proxy_port", 0)
    if not host or not port:
        return None
    user = cfg.get("proxy_user", "")
    pwd = cfg.get("proxy_pass", "")
    if user:
        return f"http://{user}:{pwd}@{host}:{port}"
    return f"http://{host}:{port}"
