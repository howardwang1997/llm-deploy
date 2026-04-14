#!/usr/bin/env bash
# 初始化 LiteLLM 使用的 Postgres 库和用户。
# 前置: postgresql-server 已通过局域网 yum/apt 镜像装好并 systemctl start。
#       本脚本以 postgres OS 用户身份执行 psql，所以需要 sudo。
set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/llm-deploy.env}
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

: "${POSTGRES_URL:?请在 $ENV_FILE 里设置 POSTGRES_URL}"

# 从连接串里解析出 user / password / dbname
# 形如 postgresql://USER:PASS@HOST:PORT/DBNAME
python3 - <<'PY' > /tmp/pg_parts.env
import os, urllib.parse
u = urllib.parse.urlparse(os.environ["POSTGRES_URL"])
print(f"PG_USER={u.username}")
print(f"PG_PASS={u.password}")
print(f"PG_DB={u.path.lstrip('/')}")
print(f"PG_HOST={u.hostname}")
print(f"PG_PORT={u.port or 5432}")
PY
# shellcheck disable=SC1091
source /tmp/pg_parts.env
rm -f /tmp/pg_parts.env

if ! systemctl is-active --quiet postgresql; then
    echo "[init_postgres] Postgres 未启动，尝试启动..."
    sudo systemctl start postgresql
fi

echo "[init_postgres] 创建角色 $PG_USER（若已存在则更新密码）"
sudo -u postgres psql <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$PG_USER') THEN
        CREATE ROLE "$PG_USER" LOGIN PASSWORD '$PG_PASS';
    ELSE
        ALTER ROLE "$PG_USER" WITH LOGIN PASSWORD '$PG_PASS';
    END IF;
END
\$\$;
SQL

echo "[init_postgres] 创建数据库 $PG_DB（若已存在则跳过）"
sudo -u postgres psql <<SQL
SELECT 'CREATE DATABASE "$PG_DB" OWNER "$PG_USER"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$PG_DB')\gexec
SQL

sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE \"$PG_DB\" TO \"$PG_USER\";"

echo "[init_postgres] 验证连接"
PGPASSWORD="$PG_PASS" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "SELECT 1;" >/dev/null
echo "[init_postgres] 完成。LiteLLM 首次启动会自动创建 schema（LiteLLM_SpendLogs 等表）。"
