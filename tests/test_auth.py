import threading
import time

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from admin_api.auth import _SlidingWindow, admin_required, rate_limit_per_ip
from admin_api.config import Settings


def _settings(admin_key="test-admin", rate=(5, 600)) -> Settings:
    return Settings(
        port=4100,
        admin_api_key=admin_key,
        postgres_url="postgres://fake",
        litellm_url="http://127.0.0.1:4000",
        litellm_master_key="test-master",
        default_budget=50.0,
        default_budget_duration="30d",
        default_key_duration="180d",
        allowed_models=["minimax-m2.5"],
        rate_limit_per_ip=rate,
    )


class TestAdminRequired:
    def _app(self, settings: Settings) -> TestClient:
        app = FastAPI()

        @app.get("/ping", dependencies=[Depends(admin_required(settings))])
        def ping():
            return {"ok": True}

        return TestClient(app)

    def test_accepts_correct_bearer(self):
        c = self._app(_settings())
        r = c.get("/ping", headers={"Authorization": "Bearer test-admin"})
        assert r.status_code == 200

    def test_rejects_wrong_bearer(self):
        c = self._app(_settings())
        r = c.get("/ping", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401
        # 这里没挂 main.py 的异常处理器，detail 会原样落到 body
        assert r.json()["detail"]["error"] == "unauthorized"

    def test_rejects_missing_bearer(self):
        c = self._app(_settings())
        r = c.get("/ping")
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "unauthorized"


class TestSlidingWindow:
    def test_under_limit_passes(self):
        w = _SlidingWindow(limit=3, window_s=60)
        assert w.hit("ip1") is True
        assert w.hit("ip1") is True
        assert w.hit("ip1") is True

    def test_over_limit_rejected(self):
        w = _SlidingWindow(limit=3, window_s=60)
        for _ in range(3):
            assert w.hit("ip1") is True
        assert w.hit("ip1") is False

    def test_per_ip_independent(self):
        w = _SlidingWindow(limit=2, window_s=60)
        assert w.hit("a") is True
        assert w.hit("a") is True
        assert w.hit("a") is False
        assert w.hit("b") is True  # 另一 IP 不受影响

    def test_window_slides(self, monkeypatch):
        w = _SlidingWindow(limit=2, window_s=1)
        t = {"v": 1000.0}
        monkeypatch.setattr(time, "monotonic", lambda: t["v"])
        assert w.hit("ip") is True
        assert w.hit("ip") is True
        assert w.hit("ip") is False
        # 窗口滑过之后，老记录应被清
        t["v"] += 2.0
        assert w.hit("ip") is True

    def test_thread_safe(self):
        w = _SlidingWindow(limit=100, window_s=60)
        results = []

        def worker():
            for _ in range(50):
                results.append(w.hit("shared"))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        # 4*50 = 200 次 hit，limit=100 → 恰好 100 个 True
        assert results.count(True) == 100
        assert results.count(False) == 100


class TestRateLimitDependency:
    def test_429_after_limit(self):
        settings = _settings(rate=(2, 60))
        dep = rate_limit_per_ip(settings)

        app = FastAPI()

        @app.get("/self/ping", dependencies=[Depends(dep)])
        def ping():
            return {"ok": True}

        c = TestClient(app)
        assert c.get("/self/ping").status_code == 200
        assert c.get("/self/ping").status_code == 200
        r = c.get("/self/ping")
        assert r.status_code == 429
        assert r.json()["detail"]["error"] == "rate_limited"
