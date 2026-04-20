# 鉴权与频控。
# - 管理员接口：Bearer ADMIN_API_KEY，常量时间比较。
# - 自助接口：内网部署 + 进程内滑窗频控（按客户端 IP），不引入额外组件。
from __future__ import annotations

import hmac
import threading
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings


_bearer = HTTPBearer(auto_error=False)


def admin_required(settings: Settings):
    """构造一个带 settings 的依赖，用于管理员路由。"""

    def _dep(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
        token = creds.credentials if creds else ""
        if not token or not hmac.compare_digest(token, settings.admin_api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "unauthorized", "message": "管理员令牌缺失或不正确"},
            )

    return _dep


# ---- 滑窗频控 ----

class _SlidingWindow:
    def __init__(self, limit: int, window_s: int) -> None:
        self.limit = limit
        self.window_s = window_s
        self._buckets: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """命中频控返回 False，正常返回 True。"""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets[key]
            cutoff = now - self.window_s
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


def rate_limit_per_ip(settings: Settings):
    """为自助接口构造一个 IP 级频控依赖。"""
    n, w = settings.rate_limit_per_ip
    win = _SlidingWindow(n, w)

    def _dep(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        if not win.hit(ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limited",
                    "message": f"请求过频，{w}s 内最多 {n} 次",
                },
            )

    return _dep
