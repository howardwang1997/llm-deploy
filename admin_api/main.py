# admin-api 入口：装配 FastAPI app，启动时建表，挂载路由。
# 启动方式: python -m uvicorn admin_api.main:app --host 0.0.0.0 --port 4100
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import config, db
from .auth import admin_required, rate_limit_per_ip
from .litellm_client import LiteLLMClient
from .routes_admin import build_router as build_admin
from .routes_self import build_router as build_self
from .schemas import ErrorResponse, HealthResponse


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("admin_api")


SETTINGS = config.load()
LLM_CLIENT = LiteLLMClient(SETTINGS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_pool(SETTINGS.postgres_url)
    db.ensure_schema()
    logger.info("admin-api 启动 port=%s litellm=%s", SETTINGS.port, SETTINGS.litellm_url)
    try:
        yield
    finally:
        LLM_CLIENT.close()
        db.close_pool()


app = FastAPI(
    title="llm-deploy admin-api",
    description="LiteLLM 网关的运维自助层：名单管理 + 员工自助签发 API key。",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def _http_err(_: Request, exc: HTTPException):
    # 把 detail 统一成 {error, message} 形式
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        body = exc.detail
    else:
        body = {"error": "http_error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.get("/healthz", response_model=HealthResponse)
def healthz():
    return HealthResponse(status="ok", db="ok" if db.ping() else "down")


app.include_router(
    build_admin(LLM_CLIENT, admin_required(SETTINGS)),
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
app.include_router(
    build_self(LLM_CLIENT, rate_limit_per_ip(SETTINGS), SETTINGS.allowed_models),
    responses={
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
