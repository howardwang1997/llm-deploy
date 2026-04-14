#!/usr/bin/env bash
# 用法:
#   healthcheck.sh vllm       # 轮询等待 vLLM /v1/models 就绪（systemd ExecStartPre 用）
#   healthcheck.sh gateway    # 检查 LiteLLM 网关
#   healthcheck.sh e2e        # 端到端 smoke test: OpenAI + Anthropic 各打一发
set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/llm-deploy.env}
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

VLLM_PORT=${VLLM_PORT:-8000}
LITELLM_PORT=${LITELLM_PORT:-4000}
TIMEOUT=${HEALTHCHECK_TIMEOUT:-600}

wait_for() {
    local url=$1 label=$2 deadline=$(( $(date +%s) + TIMEOUT ))
    while (( $(date +%s) < deadline )); do
        if curl -sf -o /dev/null "$url"; then
            echo "[healthcheck] $label ready: $url"
            return 0
        fi
        sleep 3
    done
    echo "[healthcheck] $label NOT ready after ${TIMEOUT}s: $url" >&2
    return 1
}

case "${1:-}" in
    vllm)
        wait_for "http://127.0.0.1:${VLLM_PORT}/v1/models" vllm
        ;;
    gateway)
        wait_for "http://127.0.0.1:${LITELLM_PORT}/health/readiness" gateway
        ;;
    e2e)
        : "${LITELLM_MASTER_KEY:?}"
        BASE="http://127.0.0.1:${LITELLM_PORT}"
        echo "[healthcheck] OpenAI /v1/chat/completions"
        curl -sf -X POST "$BASE/v1/chat/completions" \
            -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
            -H "Content-Type: application/json" \
            -d '{"model":"minimax-m2.5","messages":[{"role":"user","content":"say hi in 3 words"}],"max_tokens":32}' \
            | python3 -m json.tool

        echo "[healthcheck] Anthropic /v1/messages"
        curl -sf -X POST "$BASE/v1/messages" \
            -H "x-api-key: $LITELLM_MASTER_KEY" \
            -H "anthropic-version: 2023-06-01" \
            -H "Content-Type: application/json" \
            -d '{"model":"minimax-m2.5","max_tokens":32,"messages":[{"role":"user","content":"say hi in 3 words"}]}' \
            | python3 -m json.tool
        ;;
    *)
        echo "usage: $0 {vllm|gateway|e2e}" >&2
        exit 2
        ;;
esac
