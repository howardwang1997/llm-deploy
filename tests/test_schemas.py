import pytest
from pydantic import ValidationError

from admin_api.schemas import (
    BulkRosterRequest,
    RosterEntry,
    SelfIdentity,
)


class TestRosterEntry:
    def test_basic(self):
        e = RosterEntry(employee_id="E001", name="张三")
        assert e.employee_id == "E001"
        assert e.name == "张三"

    def test_strip_whitespace(self):
        e = RosterEntry(employee_id="  E001  ", name="  张三  ")
        assert e.employee_id == "E001"
        assert e.name == "张三"

    def test_rejects_empty_after_strip(self):
        with pytest.raises(ValidationError):
            RosterEntry(employee_id="   ", name="张三")

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError):
            RosterEntry(employee_id="E001", name="")

    def test_rejects_too_long_employee_id(self):
        with pytest.raises(ValidationError):
            RosterEntry(employee_id="E" * 65, name="张三")

    def test_rejects_too_long_name(self):
        with pytest.raises(ValidationError):
            RosterEntry(employee_id="E001", name="张" * 129)


class TestBulkRosterRequest:
    def test_single_entry(self):
        req = BulkRosterRequest(entries=[{"employee_id": "E001", "name": "张三"}])
        assert len(req.entries) == 1

    def test_rejects_empty_list(self):
        with pytest.raises(ValidationError):
            BulkRosterRequest(entries=[])

    def test_rejects_over_10000(self):
        entries = [{"employee_id": f"E{i:05d}", "name": f"员工{i}"} for i in range(10001)]
        with pytest.raises(ValidationError):
            BulkRosterRequest(entries=entries)

    def test_exactly_10000_ok(self):
        entries = [{"employee_id": f"E{i:05d}", "name": f"员工{i}"} for i in range(10000)]
        req = BulkRosterRequest(entries=entries)
        assert len(req.entries) == 10000


class TestSelfIdentity:
    def test_basic(self):
        s = SelfIdentity(employee_id="E001", name="张三")
        assert s.employee_id == "E001"
        assert s.name == "张三"

    def test_strip(self):
        s = SelfIdentity(employee_id="\tE001\n", name=" 张三 ")
        assert s.employee_id == "E001"
        assert s.name == "张三"

    def test_rejects_blank(self):
        with pytest.raises(ValidationError):
            SelfIdentity(employee_id="", name="张三")
