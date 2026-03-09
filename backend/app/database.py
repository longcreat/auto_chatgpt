from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─── 数据模型 ──────────────────────────────────────────────

class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)
    username = Column(String(100), nullable=True)

    # 域名邮箱地址（Cloudflare 别名）
    cf_email_alias = Column(String(255), nullable=True)

    # 账号状态: pending / active / suspended / banned
    status = Column(String(50), default="pending")

    # ChatGPT 登录 session token
    session_token = Column(Text, nullable=True)
    access_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)

    # OpenAI API Key（如果升级为 Plus 或有 API 权限）
    api_key = Column(String(100), nullable=True)

    # 是否为当前激活账号（Codex 使用）
    is_active = Column(Boolean, default=False)

    # 备注
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    tokens = relationship("Token", back_populates="account", cascade="all, delete-orphan")


class Token(Base):
    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)

    # token 类型: session_token / access_token / refresh_token / id_token / api_key
    token_type = Column(String(50), nullable=False)
    token_value = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    is_valid = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", back_populates="tokens")


class EmailAlias(Base):
    __tablename__ = "email_aliases"

    id = Column(Integer, primary_key=True, index=True)
    alias = Column(String(255), unique=True, nullable=False)  # random@yourdomain.com
    forward_to = Column(String(255), nullable=False)
    cf_rule_tag = Column(String(255), nullable=True)  # Cloudflare routing rule tag
    is_used = Column(Boolean, default=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class RegistrationTask(Base):
    __tablename__ = "registration_tasks"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False)
    status = Column(String(50), default="queued")  # queued / running / done / failed
    log = Column(Text, nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemConfig(Base):
    """系统配置表 — 单行存储，运行时由服务层缓存"""
    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, default=1)

    # ─── 域名配置 ───
    domain_name = Column(String(255), nullable=True, default="")

    # ─── IMAP 收信配置 ───
    imap_host = Column(String(255), nullable=True, default="")
    imap_port = Column(Integer, nullable=True, default=993)
    imap_user = Column(String(255), nullable=True, default="")
    imap_password = Column(String(255), nullable=True, default="")

    # ─── 代理配置 ───
    proxy_host = Column(String(255), nullable=True, default="")
    proxy_port = Column(Integer, nullable=True, default=0)
    proxy_user = Column(String(255), nullable=True, default="")
    proxy_pass = Column(String(255), nullable=True, default="")

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─── DB 会话依赖 ──────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    if engine.url.get_backend_name() == "sqlite" and engine.url.database:
        Path(engine.url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _dedupe_registration_tasks()
    _ensure_registration_task_unique_index()


def _dedupe_registration_tasks():
    db = SessionLocal()
    try:
        duplicated_emails = [
            email
            for (email,) in (
                db.query(RegistrationTask.email)
                .group_by(RegistrationTask.email)
                .having(func.count(RegistrationTask.id) > 1)
                .all()
            )
        ]
        for email in duplicated_emails:
            tasks = (
                db.query(RegistrationTask)
                .filter(RegistrationTask.email == email)
                .order_by(
                    RegistrationTask.updated_at.desc(),
                    RegistrationTask.created_at.desc(),
                    RegistrationTask.id.desc(),
                )
                .all()
            )
            account = (
                db.query(Account)
                .filter(Account.email == email, Account.status == "active")
                .order_by(Account.updated_at.desc(), Account.created_at.desc(), Account.id.desc())
                .first()
            )

            keep_task = None
            if account:
                keep_task = next((task for task in tasks if task.account_id == account.id), None)
                if not keep_task:
                    keep_task = next((task for task in tasks if task.status == "done"), None)
                if not keep_task:
                    keep_task = tasks[0]
                    keep_task.status = "done"
                    keep_task.account_id = account.id
            else:
                keep_task = next((task for task in tasks if task.status != "failed"), None) or tasks[0]

            keep_task.updated_at = datetime.utcnow()
            for task in tasks:
                if task.id != keep_task.id:
                    db.delete(task)
            db.commit()
    finally:
        db.close()


def _ensure_registration_task_unique_index():
    if engine.url.get_backend_name() != "sqlite":
        return
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_registration_tasks_email ON registration_tasks(email)"
        )
