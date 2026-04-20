# 员工自助路由：register / rotate / status。
# 鉴权方式：(工号, 姓名) 双字段精确匹配 + IP 滑窗频控。
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, status

from . import db
from .litellm_client import LiteLLMClient, extract_key_text
from .schemas import SelfIdentity, SelfRegisterResponse, SelfStatusResponse


logger = logging.getLogger(__name__)


def _expires_to_dt(v) -> Optional[datetime]:
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def build_router(
    litellm: LiteLLMClient,
    rate_dep,
    allowed_models: Sequence[str],
) -> APIRouter:
    r = APIRouter(prefix="/self", dependencies=[Depends(rate_dep)])
    fallback_models = list(allowed_models)

    def _issue(body: SelfIdentity) -> SelfRegisterResponse:
        if not db.match_employee(body.employee_id, body.name):
            # 姓名/工号对不上：不区分"工号不存在"和"姓名不匹配"，避免名单嗅探
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "identity_mismatch",
                    "message": "工号或姓名与名单不一致，请联系管理员",
                },
            )

        # 用 unix 秒做 alias 后缀，保证轮换时新 alias 不会和旧的撞 UNIQUE 约束
        alias = f"emp-{body.employee_id}-{int(time.time())}"
        try:
            resp = litellm.generate_key(body.employee_id, body.name, alias)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "litellm_unavailable",
                    "message": f"LiteLLM 网关签发 key 失败: {exc}",
                },
            )

        key_text = extract_key_text(resp)
        if not key_text:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "litellm_bad_response",
                    "message": "LiteLLM 返回里没有 key 字段",
                },
            )

        # 先把新 key 落库，再删旧 key——失败时旧 key 至少还能用
        old_alias = db.upsert_key(body.employee_id, alias, key_text[:12])
        if old_alias:
            deleted = litellm.delete_key_by_alias(old_alias)
            if not deleted:
                logger.info(
                    "旧 key 删除未成功，仍受预算约束 employee=%s alias=%s",
                    body.employee_id, old_alias,
                )

        # LiteLLM 某些版本不回显 models 字段，用服务端的白名单兜底
        resp_models = list(resp.get("models") or [])
        return SelfRegisterResponse(
            api_key=key_text,
            key_prefix=key_text[:12],
            expires=_expires_to_dt(resp.get("expires")),
            max_budget=resp.get("max_budget"),
            models=resp_models or list(fallback_models),
        )

    @r.post("/register", response_model=SelfRegisterResponse)
    def register(body: SelfIdentity):
        return _issue(body)

    @r.post("/rotate", response_model=SelfRegisterResponse)
    def rotate(body: SelfIdentity):
        return _issue(body)

    @r.post("/status", response_model=SelfStatusResponse)
    def status_(body: SelfIdentity):
        if not db.match_employee(body.employee_id, body.name):
            return SelfStatusResponse(registered=False, has_key=False)
        rec = db.get_key(body.employee_id)
        if rec is None:
            return SelfStatusResponse(registered=True, has_key=False)
        return SelfStatusResponse(
            registered=True,
            has_key=True,
            issued_at=rec["issued_at"],
            key_prefix=rec["key_prefix"],
        )

    return r
