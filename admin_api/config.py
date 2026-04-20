# admin_api 的运行期配置，全部从 /etc/llm-deploy.env（或当前进程环境）读。
# 启动脚本里已经 source 了 env file，这里直接读 os.environ。
from __future__ import annotations

import os
from dataclasses import dataclass


def _required(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"环境变量 {name} 未设置（admin-api 启动必填）")
    return val


def _csv(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [s.strip() for s in raw.split(",") if s.strip()]


def _rate(name: str, default: str) -> tuple[int, int]:
    """格式 "次数/秒数"，例如 5/600。"""
    raw = os.environ.get(name, default).strip()
    n, _, w = raw.partition("/")
    return int(n), int(w)


@dataclass(frozen=True)
class Settings:
    port: int
    admin_api_key: str
    postgres_url: str
    litellm_url: str
    litellm_master_key: str
    default_budget: float
    default_budget_duration: str
    default_key_duration: str
    allowed_models: list[str]
    rate_limit_per_ip: tuple[int, int]


def load() -> Settings:
    return Settings(
        port=int(os.environ.get("ADMIN_API_PORT", "4100")),
        admin_api_key=_required("ADMIN_API_KEY"),
        postgres_url=_required("POSTGRES_URL"),
        litellm_url=os.environ.get("LITELLM_INTERNAL_URL", "http://127.0.0.1:4000").rstrip("/"),
        litellm_master_key=_required("LITELLM_MASTER_KEY"),
        default_budget=float(os.environ.get("ADMIN_DEFAULT_BUDGET", "50")),
        default_budget_duration=os.environ.get("ADMIN_DEFAULT_BUDGET_DURATION", "30d"),
        default_key_duration=os.environ.get("ADMIN_DEFAULT_KEY_DURATION", "180d"),
        allowed_models=_csv("ADMIN_ALLOWED_MODELS", "minimax-m2.5"),
        rate_limit_per_ip=_rate("ADMIN_RATE_LIMIT_PER_IP", "5/600"),
    )
