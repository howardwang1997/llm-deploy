"""/self/* 路由集成测试。"""
import httpx
import pytest


def _seed(client, admin_headers, entries):
    client.post("/admin/roster/bulk", headers=admin_headers, json={"entries": entries})


class TestSelfRegister:
    def test_identity_mismatch_wrong_name(self, client, admin_headers, fake_llm):
        _seed(client, admin_headers, [{"employee_id": "E001", "name": "张三"}])
        r = client.post("/self/register", json={"employee_id": "E001", "name": "李四"})
        assert r.status_code == 403
        assert r.json()["error"] == "identity_mismatch"
        assert fake_llm.generate_calls == []  # 未匹配就不应调 LiteLLM

    def test_identity_mismatch_unknown_employee(self, client, fake_llm):
        r = client.post("/self/register", json={"employee_id": "E999", "name": "张三"})
        assert r.status_code == 403
        assert r.json()["error"] == "identity_mismatch"
        assert fake_llm.generate_calls == []

    def test_success_returns_full_key(self, client, admin_headers, fake_db, fake_llm):
        _seed(client, admin_headers, [{"employee_id": "E001", "name": "张三"}])
        r = client.post("/self/register", json={"employee_id": "E001", "name": "张三"})
        assert r.status_code == 200
        body = r.json()
        assert body["api_key"].startswith("sk-fake-E001-")
        assert body["key_prefix"] == body["api_key"][:12]
        assert body["models"] == ["minimax-m2.5"]
        assert body["max_budget"] == 50
        # pydantic v2 datetime 默认 isoformat 是 "+00:00"，不是 "Z"；只校验年份前缀
        assert body["expires"].startswith("2030-01-01T00:00:00")
        assert "请妥善保存" in body["note"]

        # 落库
        assert "E001" in fake_db.keys
        # 调了 generate，没调 delete
        assert len(fake_llm.generate_calls) == 1
        assert fake_llm.generate_calls[0]["employee_id"] == "E001"
        assert fake_llm.delete_calls == []

    def test_register_rotates_old_key(self, client, admin_headers, fake_llm):
        _seed(client, admin_headers, [{"employee_id": "E001", "name": "张三"}])
        r1 = client.post("/self/register", json={"employee_id": "E001", "name": "张三"})
        r2 = client.post("/self/register", json={"employee_id": "E001", "name": "张三"})
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["api_key"] != r2.json()["api_key"]

        assert len(fake_llm.generate_calls) == 2
        # 第二次注册时应删掉第一次的 alias
        old_alias = fake_llm.generate_calls[0]["key_alias"]
        assert fake_llm.delete_calls == [old_alias]

    def test_models_fallback_when_litellm_empty(self, client, admin_headers, fake_llm):
        _seed(client, admin_headers, [{"employee_id": "E001", "name": "张三"}])
        fake_llm.return_empty_models = True
        r = client.post("/self/register", json={"employee_id": "E001", "name": "张三"})
        assert r.status_code == 200
        assert r.json()["models"] == ["minimax-m2.5"]  # 服务端 allowed_models 兜底

    def test_litellm_http_error_502(self, client, admin_headers, fake_llm):
        _seed(client, admin_headers, [{"employee_id": "E001", "name": "张三"}])
        fake_llm.raise_on_generate = httpx.ConnectError("refused")

        r = client.post("/self/register", json={"employee_id": "E001", "name": "张三"})
        assert r.status_code == 502
        assert r.json()["error"] == "litellm_unavailable"

    def test_litellm_bad_response_502(self, client, admin_headers, fake_llm):
        _seed(client, admin_headers, [{"employee_id": "E001", "name": "张三"}])
        fake_llm.return_bad_key = True

        r = client.post("/self/register", json={"employee_id": "E001", "name": "张三"})
        assert r.status_code == 502
        assert r.json()["error"] == "litellm_bad_response"


class TestSelfRotate:
    def test_rotate_same_as_register(self, client, admin_headers, fake_llm):
        _seed(client, admin_headers, [{"employee_id": "E001", "name": "张三"}])
        r = client.post("/self/rotate", json={"employee_id": "E001", "name": "张三"})
        assert r.status_code == 200
        assert r.json()["api_key"].startswith("sk-fake-")
        assert len(fake_llm.generate_calls) == 1


class TestSelfStatus:
    def test_not_registered(self, client):
        r = client.post("/self/status", json={"employee_id": "E999", "name": "张三"})
        assert r.status_code == 200
        assert r.json() == {"registered": False, "has_key": False, "issued_at": None, "key_prefix": None}

    def test_registered_without_key(self, client, admin_headers):
        _seed(client, admin_headers, [{"employee_id": "E001", "name": "张三"}])
        r = client.post("/self/status", json={"employee_id": "E001", "name": "张三"})
        body = r.json()
        assert body["registered"] is True
        assert body["has_key"] is False

    def test_registered_with_key(self, client, admin_headers):
        _seed(client, admin_headers, [{"employee_id": "E001", "name": "张三"}])
        client.post("/self/register", json={"employee_id": "E001", "name": "张三"})
        r = client.post("/self/status", json={"employee_id": "E001", "name": "张三"})
        body = r.json()
        assert body["registered"] is True
        assert body["has_key"] is True
        assert body["key_prefix"] is not None
        assert body["issued_at"] is not None

    def test_status_does_not_leak_when_name_wrong(self, client, admin_headers):
        _seed(client, admin_headers, [{"employee_id": "E001", "name": "张三"}])
        # 姓名错：返回 registered=False，不透露该工号是否存在
        r = client.post("/self/status", json={"employee_id": "E001", "name": "李四"})
        body = r.json()
        assert body["registered"] is False
        assert body["has_key"] is False


class TestKeyAliasFormat:
    def test_alias_contains_employee_id_and_timestamp(self, client, admin_headers, fake_llm, freeze_time):
        _seed(client, admin_headers, [{"employee_id": "E001", "name": "张三"}])
        client.post("/self/register", json={"employee_id": "E001", "name": "张三"})
        alias = fake_llm.generate_calls[0]["key_alias"]
        assert alias == "emp-E001-1700000000"
