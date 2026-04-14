#!/usr/bin/env bash
# 安装 vLLM + LiteLLM 及其运行依赖到 /opt/llm-deploy/venv
# 通过 /etc/llm-deploy.env 里的 PIP_INDEX_URL / HTTPS_PROXY 走局域网镜像。
set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/llm-deploy.env}
VENV_DIR=${VENV_DIR:-/opt/llm-deploy/venv}
PY_BIN=${PY_BIN:-python3.11}

if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

PIP_ARGS=()
if [[ -n "${PIP_INDEX_URL:-}" ]]; then
    PIP_ARGS+=(--index-url "$PIP_INDEX_URL")
    if [[ -n "${PIP_TRUSTED_HOST:-}" ]]; then
        PIP_ARGS+=(--trusted-host "$PIP_TRUSTED_HOST")
    fi
fi

if ! command -v "$PY_BIN" >/dev/null 2>&1; then
    echo "[install_deps] 找不到 $PY_BIN，先装 Python 3.10/3.11" >&2
    exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
    echo "[install_deps] 创建 venv: $VENV_DIR"
    "$PY_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "[install_deps] 升级 pip"
pip install "${PIP_ARGS[@]}" -U pip setuptools wheel

echo "[install_deps] 安装 vLLM（会顺带拉 torch / flash-attn 对应 CUDA wheel）"
pip install "${PIP_ARGS[@]}" -U vllm

echo "[install_deps] 安装 LiteLLM proxy + Postgres 驱动"
pip install "${PIP_ARGS[@]}" -U "litellm[proxy]" prisma psycopg2-binary

echo "[install_deps] 生成 LiteLLM 的 prisma client（离线机器首次会下载 prisma engine，若失败请看 docs/setup.md 的排障）"
python -m prisma generate --schema "$(python -c 'import litellm, os; print(os.path.join(os.path.dirname(litellm.__file__), "proxy", "schema.prisma"))')" || true

echo "[install_deps] 完成。vLLM 版本: $(vllm --version 2>/dev/null || echo unknown)"
echo "[install_deps] LiteLLM 版本: $(litellm --version 2>/dev/null || echo unknown)"
