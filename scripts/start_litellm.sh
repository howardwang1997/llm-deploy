#!/usr/bin/env bash
# 前台启动 LiteLLM 网关，供 systemd 直接 exec。
set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/llm-deploy.env}
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

CONFIG=${LITELLM_CONFIG:-/AI4S/Users/howardwang/llm-deploy/config/litellm.yaml}

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_conda.sh"
conda activate "$CONDA_ENV"

: "${LITELLM_MASTER_KEY:?LITELLM_MASTER_KEY 未设置}"
: "${POSTGRES_URL:?POSTGRES_URL 未设置}"
export DATABASE_URL="$POSTGRES_URL"

echo "[start_litellm] config=$CONFIG host=0.0.0.0 port=${LITELLM_PORT:-4000}"
exec litellm \
    --config "$CONFIG" \
    --host 0.0.0.0 \
    --port "${LITELLM_PORT:-4000}"
