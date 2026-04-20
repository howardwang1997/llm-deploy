"""/admin/* 路由集成测试（TestClient + FakeDB + FakeLiteLLM）。"""


class TestRosterBulk:
    def test_unauthorized_without_bearer(self, client):
        r = client.post("/admin/roster/bulk", json={"entries": [{"employee_id": "E001", "name": "张三"}]})
        assert r.status_code == 401
        assert r.json()["error"] == "unauthorized"

    def test_wrong_bearer(self, client):
        r = client.post(
            "/admin/roster/bulk",
            headers={"Authorization": "Bearer wrong"},
            json={"entries": [{"employee_id": "E001", "name": "张三"}]},
        )
        assert r.status_code == 401

    def test_bulk_insert(self, client, admin_headers, fake_db):
        r = client.post(
            "/admin/roster/bulk",
            headers=admin_headers,
            json={"entries": [
                {"employee_id": "E001", "name": "张三"},
                {"employee_id": "E002", "name": "李四"},
            ]},
        )
        assert r.status_code == 200
        assert r.json() == {"inserted": 2, "updated": 0, "unchanged": 0}
        assert set(fake_db.roster.keys()) == {"E001", "E002"}

    def test_bulk_update_unchanged_mixed(self, client, admin_headers, fake_db):
        client.post(
            "/admin/roster/bulk",
            headers=admin_headers,
            json={"entries": [{"employee_id": "E001", "name": "张三"}]},
        )
        r = client.post(
            "/admin/roster/bulk",
            headers=admin_headers,
            json={"entries": [
                {"employee_id": "E001", "name": "张三"},       # unchanged
                {"employee_id": "E002", "name": "李四"},       # inserted
                {"employee_id": "E001", "name": "张三改名"},  # updated（覆盖同一次操作里的前一条）
            ]},
        )
        body = r.json()
        assert body["inserted"] == 1
        assert body["updated"] == 1
        assert body["unchanged"] == 1
        assert fake_db.roster["E001"]["name"] == "张三改名"


class TestRosterList:
    def test_empty(self, client, admin_headers):
        r = client.get("/admin/roster", headers=admin_headers)
        assert r.status_code == 200
        assert r.json() == {"total": 0, "items": []}

    def test_pagination_and_search(self, client, admin_headers):
        client.post(
            "/admin/roster/bulk",
            headers=admin_headers,
            json={"entries": [
                {"employee_id": "E001", "name": "张三"},
                {"employee_id": "E002", "name": "李四"},
                {"employee_id": "E003", "name": "王五"},
            ]},
        )
        r = client.get("/admin/roster?limit=2&offset=0", headers=admin_headers)
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2

        r = client.get("/admin/roster?q=张", headers=admin_headers)
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["employee_id"] == "E001"


class TestRosterGetOne:
    def test_found_without_key(self, client, admin_headers):
        client.post(
            "/admin/roster/bulk",
            headers=admin_headers,
            json={"entries": [{"employee_id": "E001", "name": "张三"}]},
        )
        r = client.get("/admin/roster/E001", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["employee_id"] == "E001"
        assert body["has_key"] is False
        assert body["key_prefix"] is None

    def test_not_found(self, client, admin_headers):
        r = client.get("/admin/roster/E999", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"] == "not_found"


class TestRosterDelete:
    def test_delete_without_key(self, client, admin_headers, fake_llm):
        client.post(
            "/admin/roster/bulk",
            headers=admin_headers,
            json={"entries": [{"employee_id": "E001", "name": "张三"}]},
        )
        r = client.delete("/admin/roster/E001", headers=admin_headers)
        assert r.status_code == 200
        assert r.json() == {"deleted": "E001", "key_revoked": False}
        assert fake_llm.delete_calls == []

    def test_delete_cascades_key(self, client, admin_headers, fake_llm):
        client.post(
            "/admin/roster/bulk",
            headers=admin_headers,
            json={"entries": [{"employee_id": "E001", "name": "张三"}]},
        )
        # 先通过自助接口签个 key
        client.post("/self/register", json={"employee_id": "E001", "name": "张三"})
        r = client.delete("/admin/roster/E001", headers=admin_headers)
        body = r.json()
        assert body["deleted"] == "E001"
        assert body["key_revoked"] is True
        assert len(fake_llm.delete_calls) == 1

    def test_delete_404(self, client, admin_headers):
        r = client.delete("/admin/roster/E999", headers=admin_headers)
        assert r.status_code == 404


class TestUsage:
    def test_all_employees(self, client, admin_headers):
        client.post(
            "/admin/roster/bulk",
            headers=admin_headers,
            json={"entries": [
                {"employee_id": "E001", "name": "张三"},
                {"employee_id": "E002", "name": "李四"},
            ]},
        )
        client.post("/self/register", json={"employee_id": "E001", "name": "张三"})

        r = client.get("/admin/usage", headers=admin_headers)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        by_id = {i["employee_id"]: i for i in items}
        assert by_id["E001"]["has_key"] is True
        assert by_id["E002"]["has_key"] is False

    def test_single_employee(self, client, admin_headers):
        client.post(
            "/admin/roster/bulk",
            headers=admin_headers,
            json={"entries": [
                {"employee_id": "E001", "name": "张三"},
                {"employee_id": "E002", "name": "李四"},
            ]},
        )
        r = client.get("/admin/usage?employee_id=E002", headers=admin_headers)
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["employee_id"] == "E002"


class TestHealthz:
    def test_ok(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "db": "ok"}
