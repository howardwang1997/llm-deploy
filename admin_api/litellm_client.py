# 调 LiteLLM 内置管理 API（/key/generate、/key/delete）的薄封装。
# 全部用 master key 鉴权，调用走 loopback（默认 127.0.0.1:4000），master key 不出网。
from __future__ import annotations

import logging
from typing import Optional

import httpx

from .config import Settings


logger = logging.getLogger(__name__)


class LiteLLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.Client(
            base_url=settings.litellm_url,
            headers={"Authorization": f"Bearer {settings.litellm_master_key}"},
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def generate_key(self, employee_id: str, name: str, key_alias: str) -> dict:
        """签发一个绑定到工号的子 key。返回 LiteLLM 原始响应。"""
        payload = {
            "user_id": employee_id,
            "key_alias": key_alias,
            "models": list(self._settings.allowed_models),
            "max_budget": self._settings.default_budget,
            "budget_duration": self._settings.default_budget_duration,
            "duration": self._settings.default_key_duration,
            "metadata": {"name": name, "issued_by": "admin-api"},
        }
        r = self._client.post("/key/generate", json=payload)
        r.raise_for_status()
        return r.json()

    def delete_key_by_alias(self, key_alias: str) -> bool:
        """按 alias 删 key。失败只记 warning，不抛——旧 key 仍受预算约束，不阻塞用户。"""
        try:
            r = self._client.post("/key/delete", json={"key_aliases": [key_alias]})
            r.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.warning("删除旧 key 失败 alias=%s err=%s", key_alias, exc)
            return False


def extract_key_text(resp: dict) -> Optional[str]:
    """LiteLLM 不同版本字段略有差异，按优先级取。"""
    for k in ("key", "token"):
        v = resp.get(k)
        if isinstance(v, str) and v.startswith("sk-"):
            return v
    return None
