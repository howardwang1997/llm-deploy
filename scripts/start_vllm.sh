#!/usr/bin/env bash
# 前台启动 vLLM，供 systemd 直接 exec。
# 只监听 127.0.0.1；对外的入口是 LiteLLM 网关。
set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/llm-deploy.env}
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

VENV_DIR=${VENV_DIR:-/AI4S/Users/howardwang/llm-deploy/venv}
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

: "${MODEL_PATH:?MODEL_PATH 未设置，请检查 $ENV_FILE}"
if [[ ! -d "$MODEL_PATH" ]]; then
    echo "[start_vllm] MODEL_PATH 不存在: $MODEL_PATH" >&2
    exit 1
fi

export SAFETENSORS_FAST_GPU=1
# 让 NCCL 走 PCIe，避免某些实例上 InfiniBand 误探测导致卡启动
export NCCL_P2P_DISABLE=${NCCL_P2P_DISABLE:-0}
export VLLM_WORKER_MULTIPROC_METHOD=${VLLM_WORKER_MULTIPROC_METHOD:-spawn}

ARGS=(
    "$MODEL_PATH"
    --served-model-name minimax-m2.5
    --host 127.0.0.1
    --port "${VLLM_PORT:-8000}"
    --trust-remote-code
    --tensor-parallel-size 8
    --enable-expert-parallel
    --enable-auto-tool-choice
    --tool-call-parser minimax_m2
    --reasoning-parser minimax_m2_append_think
    --gpu-memory-utilization "${VLLM_GPU_MEM_UTIL:-0.90}"
    --max-model-len "${VLLM_MAX_MODEL_LEN:-196608}"
)

if [[ "${VLLM_SAFE_MODE:-0}" == "1" ]]; then
    ARGS+=(--compilation-config '{"cudagraph_mode":"PIECEWISE"}')
fi

echo "[start_vllm] exec: vllm serve ${ARGS[*]}"
exec vllm serve "${ARGS[@]}"
