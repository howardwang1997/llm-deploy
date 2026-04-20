# pydantic 请求/响应模型。所有字段名贴近 LiteLLM 的命名习惯。
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ===== 公共 =====

class ErrorResponse(BaseModel):
    error: str
    message: str


# ===== 管理员：名单 CRUD =====

class RosterEntry(BaseModel):
    employee_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)

    @field_validator("employee_id", "name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v


class BulkRosterRequest(BaseModel):
    entries: list[RosterEntry] = Field(min_length=1, max_length=10000)


class BulkRosterResponse(BaseModel):
    inserted: int
    updated: int
    unchanged: int


class RosterItem(BaseModel):
    employee_id: str
    name: str
    created_at: datetime
    has_key: bool
    key_prefix: Optional[str] = None
    issued_at: Optional[datetime] = None


class RosterListResponse(BaseModel):
    total: int
    items: list[RosterItem]


# ===== 管理员：用量汇总 =====

class UsageItem(BaseModel):
    employee_id: str
    name: str
    has_key: bool
    key_prefix: Optional[str] = None
    issued_at: Optional[datetime] = None
    expires: Optional[datetime] = None
    spend: Optional[float] = None
    max_budget: Optional[float] = None
    requests: int = 0
    total_tokens: int = 0


class UsageResponse(BaseModel):
    items: list[UsageItem]


# ===== 自助接口 =====

class SelfIdentity(BaseModel):
    employee_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)

    @field_validator("employee_id", "name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v


class SelfRegisterResponse(BaseModel):
    api_key: str
    key_prefix: str
    expires: Optional[datetime] = None
    max_budget: Optional[float] = None
    models: list[str]
    note: str = "请妥善保存此 key，本接口不会再次返回原文。如需新 key 请调 /self/rotate。"


class SelfStatusResponse(BaseModel):
    registered: bool
    has_key: bool
    issued_at: Optional[datetime] = None
    key_prefix: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    db: str
