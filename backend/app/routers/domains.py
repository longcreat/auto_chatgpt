"""域名邮箱管理 API（catch-all 模式：Cloudflare 已在云端配置全局转发）"""

import random
import string
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db, EmailAlias
from app.schemas import EmailAliasOut, GenerateAliasRequest, MessageResponse
from app.services.settings_service import get_config

router = APIRouter(prefix="/api/domains", tags=["Domains"])


def _random_prefix(length: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


@router.get("/verify", summary="验证域名配置")
def verify_config():
    """catch-all 模式下返回域名 + IMAP 信息"""
    cfg = get_config()
    domain = cfg.get("domain_name", "")
    imap_user = cfg.get("imap_user", "")
    forward_to = imap_user
    enabled = bool(domain and forward_to)
    return {
        "ok": enabled,
        "enabled": enabled,
        "mode": "catch-all",
        "domain": domain,
        "forward_to": forward_to,
        "imap_host": cfg.get("imap_host", ""),
        "message": "已使用 Cloudflare catch-all 转发规则" if enabled else "请先配置域名和 IMAP 信息",
    }


@router.get("/aliases", response_model=List[EmailAliasOut])
def list_aliases(db: Session = Depends(get_db)):
    return db.query(EmailAlias).order_by(EmailAlias.created_at.desc()).all()


@router.post("/aliases/generate", response_model=List[EmailAliasOut])
def generate_aliases(body: GenerateAliasRequest, db: Session = Depends(get_db)):
    """生成随机域名邮箱记录（catch-all 模式下无需调用 CF API）"""
    if body.count > 50:
        raise HTTPException(status_code=400, detail="单次最多生成 50 个")

    cfg = get_config()
    domain = cfg.get("domain_name", "")
    imap_user = cfg.get("imap_user", "")
    if not domain:
        raise HTTPException(status_code=400, detail="请先在「系统配置」中配置域名")
    if not imap_user:
        raise HTTPException(status_code=400, detail="请先在「系统配置」中配置 IMAP 收件邮箱")

    created = []
    for _ in range(body.count):
        alias = f"{_random_prefix()}@{domain}"
        row = EmailAlias(
            alias=alias,
            forward_to=imap_user,
            cf_rule_tag=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        created.append(row)
    return created


@router.post("/aliases/custom", response_model=EmailAliasOut)
def create_custom_alias(alias: str = Query(..., description="自定义邮箱别名"), db: Session = Depends(get_db)):
    """创建自定义邮箱别名（完整 user@domain 或仅前缀）"""
    cfg = get_config()
    domain = cfg.get("domain_name", "")
    imap_user = cfg.get("imap_user", "")

    if not domain:
        raise HTTPException(status_code=400, detail="请先在「系统配置」中配置域名")

    if "@" not in alias:
        alias = f"{alias}@{domain}"

    existing = db.query(EmailAlias).filter(EmailAlias.alias == alias).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"邮箱 {alias} 已存在")

    row = EmailAlias(
        alias=alias,
        forward_to=imap_user or "",
        cf_rule_tag=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/aliases/{alias_id}", response_model=MessageResponse)
def delete_alias(alias_id: int, db: Session = Depends(get_db)):
    """删除本地别名记录"""
    row = db.query(EmailAlias).filter(EmailAlias.id == alias_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="别名不存在")
    db.delete(row)
    db.commit()
    return {"message": "邮箱别名记录已删除"}
