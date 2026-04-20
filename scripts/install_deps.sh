#!/usr/bin/env bash
# 在 conda 环境里安装 vLLM + LiteLLM 及其运行依赖。
# 环境变量:
#   CONDA_ENV  - conda 环境名，默认 llm-deploy（见 _conda.sh）
#   CONDA_BASE - conda 根目录，留空则自动探测
#   PY_VER     - 新建环境用的 Python 版本，默认 3.11
#   PIP_INDEX_URL / PIP_TRUSTED_HOST / HTTPS_PROXY - 走局域网镜像
set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/llm-deploy.env}
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

PY_VER=${PY_VER:-3.11}

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_conda.sh"

if ! conda env list | awk 'NF && $1 !~ /^#/ {print $1}' | grep -qx "$CONDA_ENV"; then
    echo "[install_deps] 创建 conda env: $CONDA_ENV (python=$PY_VER)"
    conda create -y -n "$CONDA_ENV" "python=$PY_VER"
else
    echo "[install_deps] 复用已有 conda env: $CONDA_ENV"
fi

conda activate "$CONDA_ENV"

PIP_ARGS=()
if [[ -n "${PIP_INDEX_URL:-}" ]]; then
    PIP_ARGS+=(--index-url "$PIP_INDEX_URL")
    if [[ -n "${PIP_TRUSTED_HOST:-}" ]]; then
        PIP_ARGS+=(--trusted-host "$PIP_TRUSTED_HOST")
    fi
fi

echo "[install_deps] 升级 pip"
pip install "${PIP_ARGS[@]}" -U pip setuptools wheel

echo "[install_deps] 安装 vLLM（会顺带拉 torch / flash-attn 对应 CUDA wheel）"
pip install "${PIP_ARGS[@]}" -U vllm

echo "[install_deps] 安装 LiteLLM proxy + Postgres 驱动"
pip install "${PIP_ARGS[@]}" -U "litellm[proxy]" prisma psycopg2-binary

echo "[install_deps] 安装 admin-api 依赖（fastapi / uvicorn / httpx）"
# 这三个包 litellm[proxy] 已经间接拉进来，显式固定避免后续 litellm 升级断链
pip install "${PIP_ARGS[@]}" -U fastapi "uvicorn[standard]" httpx

if [[ "${INSTALL_DEV:-0}" == "1" ]]; then
    echo "[install_deps] INSTALL_DEV=1：额外安装测试依赖（pytest）"
    pip install "${PIP_ARGS[@]}" -U -r "$(dirname "${BASH_SOURCE[0]}")/../requirements-dev.txt"
fi

echo "[install_deps] 生成 LiteLLM 的 prisma client（离线机器首次会下载 prisma engine，若失败请看 docs/setup.md 的排障）"
python -m prisma generate --schema "$(python -c 'import litellm, os; print(os.path.join(os.path.dirname(litellm.__file__), "proxy", "schema.prisma"))')" || true

echo "[install_deps] 完成。"
echo "  conda env: $CONDA_ENV  (base=$CONDA_BASE)"
echo "  vLLM: $(vllm --version 2>/dev/null || echo unknown)"
echo "  LiteLLM: $(litellm --version 2>/dev/null || echo unknown)"
echo "  FastAPI: $(python -c 'import fastapi; print(fastapi.__version__)' 2>/dev/null || echo unknown)"
