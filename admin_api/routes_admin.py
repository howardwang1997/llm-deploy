# 管理员路由：名单 CRUD + 用量汇总。全部需 Bearer ADMIN_API_KEY。
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from . import db
from .litellm_client import LiteLLMClient


logger = logging.getLogger(__name__)
from .schemas import (
    BulkRosterRequest,
    BulkRosterResponse,
    RosterItem,
    RosterListResponse,
    UsageItem,
    UsageResponse,
)


def build_router(litellm: LiteLLMClient, admin_dep) -> APIRouter:
    r = APIRouter(prefix="/admin", dependencies=[Depends(admin_dep)])

    @r.post("/roster/bulk", response_model=BulkRosterResponse)
    def bulk_upsert(body: BulkRosterRequest):
        ins, upd, unc = db.upsert_roster(
            ((e.employee_id, e.name) for e in body.entries),
            created_by="admin-api",
        )
        return BulkRosterResponse(inserted=ins, updated=upd, unchanged=unc)

    @r.get("/roster", response_model=RosterListResponse)
    def list_roster(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        q: Optional[str] = Query(None, description="工号或姓名模糊匹配"),
    ):
        total, rows = db.list_roster(limit, offset, q)
        return RosterListResponse(
            total=total,
            items=[RosterItem(**row) for row in rows],
        )

    @r.get("/roster/{employee_id}", response_model=RosterItem)
    def get_one(employee_id: str):
        row = db.get_roster(employee_id.strip())
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": f"工号 {employee_id} 不在名单"},
            )
        return RosterItem(**row)

    @r.delete("/roster/{employee_id}")
    def delete_one(employee_id: str):
        emp = employee_id.strip()
        if db.get_roster(emp) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": f"工号 {emp} 不在名单"},
            )
        old_alias = db.delete_roster(emp)  # CASCADE 已联动删 admin_employee_keys
        revoked = False
        if old_alias:
            revoked = litellm.delete_key_by_alias(old_alias)
            if not revoked:
                logger.info("旧 key 作废失败 employee=%s alias=%s", emp, old_alias)
        return {"deleted": emp, "key_revoked": revoked}

    @r.get("/usage", response_model=UsageResponse)
    def usage(
        employee_id: Optional[str] = Query(None, description="留空则返回全员"),
    ):
        rows = db.usage_summary(employee_id.strip() if employee_id else None)
        items = []
        for row in rows:
            items.append(
                UsageItem(
                    employee_id=row["employee_id"],
                    name=row["name"],
                    has_key=row["has_key"],
                    key_prefix=row["key_prefix"],
                    issued_at=row["issued_at"],
                    expires=_to_dt(row["expires"]),
                    spend=_to_float(row["spend"]),
                    max_budget=_to_float(row["max_budget"]),
                    requests=int(row["requests"] or 0),
                    total_tokens=int(row["total_tokens"] or 0),
                )
            )
        return UsageResponse(items=items)

    return r


def _to_float(v) -> Optional[float]:
    return float(v) if v is not None else None


def _to_dt(v) -> Optional[datetime]:
    if v is None or isinstance(v, datetime):
        return v
    # LiteLLM 的 expires 列可能存为 text，按 ISO 解析尝试一下；解析失败就返回 None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
