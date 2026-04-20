# Postgres 访问层。和 LiteLLM 共用一个库（litellm），新增表加 admin_ 前缀避免冲突。
# 用 psycopg2 同步接口 + 线程池连接池，FastAPI 路由声明为 def，
# 由 Starlette 自动丢线程池执行，足够这个量级（每天 10^2 量级）。
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterable, Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool


_POOL: Optional[psycopg2.pool.ThreadedConnectionPool] = None


# ----------- schema -----------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admin_employee_roster (
    employee_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by  TEXT
);

CREATE TABLE IF NOT EXISTS admin_employee_keys (
    employee_id       TEXT PRIMARY KEY REFERENCES admin_employee_roster(employee_id) ON DELETE CASCADE,
    litellm_key_alias TEXT NOT NULL UNIQUE,
    key_prefix        TEXT NOT NULL,
    issued_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rotated_at        TIMESTAMPTZ
);
"""


def init_pool(dsn: str, minconn: int = 1, maxconn: int = 8) -> None:
    global _POOL
    if _POOL is not None:
        return
    _POOL = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, dsn=dsn)


def close_pool() -> None:
    global _POOL
    if _POOL is not None:
        _POOL.closeall()
        _POOL = None


@contextmanager
def _conn():
    if _POOL is None:
        raise RuntimeError("DB pool 未初始化")
    c = _POOL.getconn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        _POOL.putconn(c)


def ensure_schema() -> None:
    with _conn() as c, c.cursor() as cur:
        cur.execute(_SCHEMA_SQL)


def ping() -> bool:
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:
        return False


# ----------- roster -----------

def upsert_roster(entries: Iterable[tuple[str, str]], created_by: Optional[str] = None) -> tuple[int, int, int]:
    """返回 (inserted, updated, unchanged)。"""
    inserted = updated = unchanged = 0
    with _conn() as c, c.cursor() as cur:
        for emp, name in entries:
            cur.execute(
                'SELECT name FROM admin_employee_roster WHERE employee_id = %s',
                (emp,),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    'INSERT INTO admin_employee_roster (employee_id, name, created_by) VALUES (%s, %s, %s)',
                    (emp, name, created_by),
                )
                inserted += 1
            elif row[0] != name:
                cur.execute(
                    'UPDATE admin_employee_roster SET name = %s WHERE employee_id = %s',
                    (name, emp),
                )
                updated += 1
            else:
                unchanged += 1
    return inserted, updated, unchanged


def list_roster(limit: int, offset: int, q: Optional[str]) -> tuple[int, list[dict]]:
    where = ""
    params: list = []
    if q:
        where = "WHERE r.employee_id ILIKE %s OR r.name ILIKE %s"
        like = f"%{q}%"
        params.extend([like, like])

    with _conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM admin_employee_roster r {where}", params)
        total = cur.fetchone()["n"]

        cur.execute(
            f"""
            SELECT r.employee_id, r.name, r.created_at,
                   k.key_prefix, k.issued_at,
                   (k.litellm_key_alias IS NOT NULL) AS has_key
            FROM admin_employee_roster r
            LEFT JOIN admin_employee_keys k ON k.employee_id = r.employee_id
            {where}
            ORDER BY r.employee_id
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        )
        rows = cur.fetchall()
    return total, [dict(r) for r in rows]


def get_roster(employee_id: str) -> Optional[dict]:
    with _conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT r.employee_id, r.name, r.created_at,
                   k.key_prefix, k.issued_at,
                   (k.litellm_key_alias IS NOT NULL) AS has_key
            FROM admin_employee_roster r
            LEFT JOIN admin_employee_keys k ON k.employee_id = r.employee_id
            WHERE r.employee_id = %s
            """,
            (employee_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def match_employee(employee_id: str, name: str) -> bool:
    """精确匹配（已 strip，区分大小写）。"""
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM admin_employee_roster WHERE employee_id = %s AND name = %s",
            (employee_id, name),
        )
        return cur.fetchone() is not None


def delete_roster(employee_id: str) -> Optional[str]:
    """删名单。返回被删的 key_alias（若有），调用方据此通知 LiteLLM。"""
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT litellm_key_alias FROM admin_employee_keys WHERE employee_id = %s",
            (employee_id,),
        )
        row = cur.fetchone()
        alias = row[0] if row else None
        cur.execute(
            "DELETE FROM admin_employee_roster WHERE employee_id = %s",
            (employee_id,),
        )
        return alias


# ----------- keys -----------

def get_key(employee_id: str) -> Optional[dict]:
    with _conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT employee_id, litellm_key_alias, key_prefix, issued_at, rotated_at
            FROM admin_employee_keys WHERE employee_id = %s
            """,
            (employee_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def upsert_key(employee_id: str, key_alias: str, key_prefix: str) -> Optional[str]:
    """落新 key 记录，返回被覆盖的旧 alias（若有），调用方据此调 /key/delete。"""
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT litellm_key_alias FROM admin_employee_keys WHERE employee_id = %s",
            (employee_id,),
        )
        row = cur.fetchone()
        old_alias = row[0] if row else None

        if old_alias is None:
            cur.execute(
                """
                INSERT INTO admin_employee_keys (employee_id, litellm_key_alias, key_prefix)
                VALUES (%s, %s, %s)
                """,
                (employee_id, key_alias, key_prefix),
            )
        else:
            cur.execute(
                """
                UPDATE admin_employee_keys
                SET litellm_key_alias = %s,
                    key_prefix        = %s,
                    issued_at         = NOW(),
                    rotated_at        = NOW()
                WHERE employee_id = %s
                """,
                (key_alias, key_prefix, employee_id),
            )
        return old_alias


# ----------- usage 汇总（join LiteLLM 自家表）-----------

def usage_summary(employee_id: Optional[str]) -> list[dict]:
    where = ""
    params: list = []
    if employee_id:
        where = "WHERE r.employee_id = %s"
        params.append(employee_id)

    sql = f"""
    SELECT
        r.employee_id,
        r.name,
        (k.litellm_key_alias IS NOT NULL) AS has_key,
        k.key_prefix,
        k.issued_at,
        vt."expires"     AS expires,
        vt."spend"       AS spend,
        vt."max_budget"  AS max_budget,
        COALESCE(sl.requests, 0) AS requests,
        COALESCE(sl.total_tokens, 0) AS total_tokens
    FROM admin_employee_roster r
    LEFT JOIN admin_employee_keys k ON k.employee_id = r.employee_id
    LEFT JOIN "LiteLLM_VerificationToken" vt ON vt."key_alias" = k.litellm_key_alias
    LEFT JOIN (
        SELECT api_key,
               COUNT(*)            AS requests,
               SUM(total_tokens)   AS total_tokens
        FROM "LiteLLM_SpendLogs"
        GROUP BY api_key
    ) sl ON sl.api_key = vt."token"
    {where}
    ORDER BY r.employee_id
    """
    with _conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        try:
            cur.execute(sql, params)
            rows = cur.fetchall()
        except psycopg2.Error:
            # LiteLLM 表可能首次启动还没建好（首次请求才会建）。降级为只读 roster + admin_employee_keys。
            c.rollback()
            cur.execute(
                f"""
                SELECT r.employee_id, r.name,
                       (k.litellm_key_alias IS NOT NULL) AS has_key,
                       k.key_prefix, k.issued_at,
                       NULL::timestamptz AS expires,
                       NULL::float8       AS spend,
                       NULL::float8       AS max_budget,
                       0::bigint          AS requests,
                       0::bigint          AS total_tokens
                FROM admin_employee_roster r
                LEFT JOIN admin_employee_keys k ON k.employee_id = r.employee_id
                {where}
                ORDER BY r.employee_id
                """,
                params,
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]
