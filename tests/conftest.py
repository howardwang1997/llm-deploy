# 测试环境装配。
# 关键点：
# 1. admin_api.config.load() 在模块 import 时就执行；必须先塞好环境变量，再 import。
# 2. 用内存 FakeDB 替换 admin_api.db 的所有导出函数，不启真实 Postgres。
# 3. 用 FakeLiteLLM 替换 main.LLM_CLIENT 的三个方法，不起真实 httpx。
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Iterable, Optional

import pytest


# 必须在 import admin_api.* 前塞好环境变量
os.environ.setdefault("ADMIN_API_KEY", "test-admin")
os.environ.setdefault("LITELLM_MASTER_KEY", "test-master")
os.environ.setdefault("POSTGRES_URL", "postgres://fake/fake")
os.environ.setdefault("ADMIN_ALLOWED_MODELS", "minimax-m2.5")
os.environ.setdefault("LITELLM_INTERNAL_URL", "http://127.0.0.1:4000")


# ---------- Fake DB ----------

class FakeDB:
    """内存实现，语义对齐 admin_api.db 里的导出函数。"""

    def __init__(self) -> None:
        self.roster: dict[str, dict] = {}  # employee_id -> {name, created_at, created_by}
        self.keys: dict[str, dict] = {}    # employee_id -> {litellm_key_alias, key_prefix, issued_at, rotated_at}
        self.used_aliases: set[str] = set()

    # schema / pool
    def init_pool(self, *_args, **_kwargs) -> None:
        pass

    def ensure_schema(self) -> None:
        pass

    def close_pool(self) -> None:
        pass

    def ping(self) -> bool:
        return True

    # roster
    def upsert_roster(self, entries: Iterable[tuple[str, str]], created_by: Optional[str] = None):
        ins = upd = unc = 0
        for emp, name in entries:
            existing = self.roster.get(emp)
            if existing is None:
                self.roster[emp] = {
                    "name": name,
                    "created_at": datetime.now(timezone.utc),
                    "created_by": created_by,
                }
                ins += 1
            elif existing["name"] != name:
                existing["name"] = name
                upd += 1
            else:
                unc += 1
        return ins, upd, unc

    def list_roster(self, limit: int, offset: int, q: Optional[str]):
        items = sorted(self.roster.items(), key=lambda kv: kv[0])
        if q:
            needle = q.lower()
            items = [(e, r) for e, r in items if needle in e.lower() or needle in r["name"].lower()]
        total = len(items)
        rows = []
        for emp, rec in items[offset:offset + limit]:
            k = self.keys.get(emp)
            rows.append({
                "employee_id": emp,
                "name": rec["name"],
                "created_at": rec["created_at"],
                "key_prefix": k["key_prefix"] if k else None,
                "issued_at": k["issued_at"] if k else None,
                "has_key": k is not None,
            })
        return total, rows

    def get_roster(self, employee_id: str):
        rec = self.roster.get(employee_id)
        if rec is None:
            return None
        k = self.keys.get(employee_id)
        return {
            "employee_id": employee_id,
            "name": rec["name"],
            "created_at": rec["created_at"],
            "key_prefix": k["key_prefix"] if k else None,
            "issued_at": k["issued_at"] if k else None,
            "has_key": k is not None,
        }

    def match_employee(self, employee_id: str, name: str) -> bool:
        rec = self.roster.get(employee_id)
        return rec is not None and rec["name"] == name

    def delete_roster(self, employee_id: str) -> Optional[str]:
        k = self.keys.pop(employee_id, None)
        self.roster.pop(employee_id, None)
        return k["litellm_key_alias"] if k else None

    # keys
    def get_key(self, employee_id: str):
        return dict(self.keys[employee_id]) if employee_id in self.keys else None

    def upsert_key(self, employee_id: str, key_alias: str, key_prefix: str) -> Optional[str]:
        old = self.keys.get(employee_id)
        old_alias = old["litellm_key_alias"] if old else None
        now = datetime.now(timezone.utc)
        if old is None:
            self.keys[employee_id] = {
                "employee_id": employee_id,
                "litellm_key_alias": key_alias,
                "key_prefix": key_prefix,
                "issued_at": now,
                "rotated_at": None,
            }
        else:
            old["litellm_key_alias"] = key_alias
            old["key_prefix"] = key_prefix
            old["issued_at"] = now
            old["rotated_at"] = now
        return old_alias

    def usage_summary(self, employee_id: Optional[str]):
        emps = [employee_id] if employee_id else sorted(self.roster.keys())
        out = []
        for emp in emps:
            rec = self.roster.get(emp)
            if rec is None:
                continue
            k = self.keys.get(emp)
            out.append({
                "employee_id": emp,
                "name": rec["name"],
                "has_key": k is not None,
                "key_prefix": k["key_prefix"] if k else None,
                "issued_at": k["issued_at"] if k else None,
                "expires": None,
                "spend": None,
                "max_budget": None,
                "requests": 0,
                "total_tokens": 0,
            })
        return out


# ---------- Fake LiteLLM ----------

class FakeLiteLLM:
    """默认成功，可通过设置 raise_on_generate/return_bad_key/delete_should_fail 触发异常路径。"""

    def __init__(self) -> None:
        self.generate_calls: list[dict] = []
        self.delete_calls: list[str] = []
        self.raise_on_generate: Optional[Exception] = None
        self.return_bad_key: bool = False   # 返回缺 key 字段的响应
        self.return_empty_models: bool = False  # 返回空 models 字段
        self.delete_should_fail: bool = False
        self._counter = 0

    def generate_key(self, employee_id: str, name: str, key_alias: str) -> dict:
        self.generate_calls.append({
            "employee_id": employee_id,
            "name": name,
            "key_alias": key_alias,
        })
        if self.raise_on_generate is not None:
            raise self.raise_on_generate
        if self.return_bad_key:
            return {"models": ["minimax-m2.5"]}
        self._counter += 1
        return {
            "key": f"sk-fake-{employee_id}-{self._counter}-xxxxxxxxxxxxxx",
            "expires": "2030-01-01T00:00:00Z",
            "max_budget": 50,
            "models": [] if self.return_empty_models else ["minimax-m2.5"],
        }

    def delete_key_by_alias(self, key_alias: str) -> bool:
        self.delete_calls.append(key_alias)
        return not self.delete_should_fail

    def close(self) -> None:
        pass


# ---------- pytest fixtures ----------

@pytest.fixture
def fake_db(monkeypatch) -> FakeDB:
    fake = FakeDB()
    # 把 admin_api.db 模块上的每个函数替换成 fake 的方法
    from admin_api import db as real_db
    for name in (
        "init_pool", "ensure_schema", "close_pool", "ping",
        "upsert_roster", "list_roster", "get_roster", "match_employee",
        "delete_roster", "get_key", "upsert_key", "usage_summary",
    ):
        monkeypatch.setattr(real_db, name, getattr(fake, name))
    return fake


@pytest.fixture
def fake_llm(monkeypatch) -> FakeLiteLLM:
    fake = FakeLiteLLM()
    from admin_api import main as main_mod
    monkeypatch.setattr(main_mod.LLM_CLIENT, "generate_key", fake.generate_key)
    monkeypatch.setattr(main_mod.LLM_CLIENT, "delete_key_by_alias", fake.delete_key_by_alias)
    monkeypatch.setattr(main_mod.LLM_CLIENT, "close", fake.close)
    return fake


@pytest.fixture
def client(fake_db, fake_llm):
    """FastAPI TestClient，已 monkeypatch 掉 DB 和 LiteLLM。"""
    from fastapi.testclient import TestClient
    from admin_api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_headers():
    return {"Authorization": "Bearer test-admin"}


@pytest.fixture
def freeze_time(monkeypatch):
    """把 time.time() 固定为可控值，用于断言 key_alias 后缀。"""
    now = {"t": 1_700_000_000.0}

    def _time():
        return now["t"]

    monkeypatch.setattr(time, "time", _time)
    return now
