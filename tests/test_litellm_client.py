import httpx
import pytest

from admin_api.config import Settings
from admin_api.litellm_client import LiteLLMClient, extract_key_text


def _settings() -> Settings:
    return Settings(
        port=4100,
        admin_api_key="x",
        postgres_url="postgres://fake",
        litellm_url="http://litellm.test",
        litellm_master_key="master-123",
        default_budget=50.0,
        default_budget_duration="30d",
        default_key_duration="180d",
        allowed_models=["minimax-m2.5"],
        rate_limit_per_ip=(5, 600),
    )


def _client_with_transport(transport: httpx.MockTransport, settings: Settings) -> LiteLLMClient:
    c = LiteLLMClient(settings)
    c.close()
    c._client = httpx.Client(
        base_url=settings.litellm_url,
        headers={"Authorization": f"Bearer {settings.litellm_master_key}"},
        transport=transport,
    )
    return c


class TestGenerateKey:
    def test_payload_and_success(self):
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["url"] = str(req.url)
            seen["auth"] = req.headers.get("authorization")
            import json
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={
                "key": "sk-new-key-abc",
                "expires": "2030-01-01T00:00:00Z",
                "max_budget": 50,
                "models": ["minimax-m2.5"],
            })

        settings = _settings()
        c = _client_with_transport(httpx.MockTransport(handler), settings)
        try:
            resp = c.generate_key("E001", "张三", "emp-E001-1700000000")
        finally:
            c.close()

        assert seen["url"].endswith("/key/generate")
        assert seen["auth"] == "Bearer master-123"
        body = seen["body"]
        assert body["user_id"] == "E001"
        assert body["key_alias"] == "emp-E001-1700000000"
        assert body["models"] == ["minimax-m2.5"]
        assert body["max_budget"] == 50.0
        assert body["budget_duration"] == "30d"
        assert body["duration"] == "180d"
        assert body["metadata"] == {"name": "张三", "issued_by": "admin-api"}
        assert resp["key"] == "sk-new-key-abc"

    def test_raises_on_5xx(self):
        def handler(req):
            return httpx.Response(500, json={"error": "boom"})

        c = _client_with_transport(httpx.MockTransport(handler), _settings())
        try:
            with pytest.raises(httpx.HTTPError):
                c.generate_key("E001", "张三", "emp-E001-1")
        finally:
            c.close()


class TestDeleteKey:
    def test_success(self):
        calls = []

        def handler(req):
            import json
            calls.append(json.loads(req.content))
            return httpx.Response(200, json={"deleted": 1})

        c = _client_with_transport(httpx.MockTransport(handler), _settings())
        try:
            ok = c.delete_key_by_alias("emp-E001-1700000000")
        finally:
            c.close()
        assert ok is True
        assert calls == [{"key_aliases": ["emp-E001-1700000000"]}]

    def test_swallows_error_returns_false(self):
        def handler(req):
            return httpx.Response(500, json={"error": "boom"})

        c = _client_with_transport(httpx.MockTransport(handler), _settings())
        try:
            ok = c.delete_key_by_alias("emp-E001-1")
        finally:
            c.close()
        assert ok is False


class TestExtractKeyText:
    def test_prefers_key_field(self):
        assert extract_key_text({"key": "sk-abc", "token": "sk-xyz"}) == "sk-abc"

    def test_falls_back_to_token(self):
        assert extract_key_text({"token": "sk-xyz"}) == "sk-xyz"

    def test_rejects_non_sk_prefix(self):
        assert extract_key_text({"key": "bad-key"}) is None

    def test_none_when_missing(self):
        assert extract_key_text({"models": []}) is None

    def test_ignores_non_string(self):
        assert extract_key_text({"key": 12345}) is None
