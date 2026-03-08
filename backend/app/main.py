import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import accounts, codex, domains, tokens
from app.routers import settings as settings_router
from app.services.codex_service import reload_active_account


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="本地 OpenAI/Codex 账号与密钥管理系统",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router)
app.include_router(tokens.router)
app.include_router(domains.router)
app.include_router(settings_router.router)
app.include_router(codex.router)


@app.on_event("startup")
def startup():
    init_db()
    reload_active_account()
    logging.info("启动完成: %s v%s", settings.APP_NAME, settings.APP_VERSION)
    logging.info("API Docs: %s/api/docs", settings.public_base_url)
    logging.info("Codex 代理: %s", settings.codex_proxy_url)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "codex_proxy_url": settings.codex_proxy_url,
    }


frontend_build = Path(__file__).resolve().parents[2] / "frontend" / "dist"
assets_dir = frontend_build / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith(("api/", "v1/")):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = frontend_build / full_path if full_path else None
        if candidate and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_build / "index.html")
