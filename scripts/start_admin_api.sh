#!/usr/bin/env bash
# 前台启动 admin-api（运维自助服务），供 systemd 直接 exec。
# 与 LiteLLM 同机部署，端口默认 4100。
set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/llm-deploy.env}
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_conda.sh"
conda activate "$CONDA_ENV"

: "${ADMIN_API_KEY:?ADMIN_API_KEY 未设置}"
: "${LITELLM_MASTER_KEY:?LITELLM_MASTER_KEY 未设置}"
: "${POSTGRES_URL:?POSTGRES_URL 未设置}"

# 工作目录里要有 admin_api/ 包，否则 uvicorn 找不到模块
WORKDIR=${ADMIN_API_WORKDIR:-/AI4S/Users/howardwang/llm-deploy}
cd "$WORKDIR"

PORT=${ADMIN_API_PORT:-4100}
echo "[start_admin_api] workdir=$WORKDIR host=0.0.0.0 port=$PORT litellm=${LITELLM_INTERNAL_URL:-http://127.0.0.1:4000}"

exec python -m uvicorn admin_api.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --no-access-log
