# 运维手册

## 服务生命周期

```bash
# 状态
sudo systemctl status vllm-minimax litellm-gateway

# 重启（改 config/litellm.yaml 或 /etc/llm-deploy.env 后）
sudo systemctl restart vllm-minimax     # 重载 vLLM，耗时 3-10 分钟
sudo systemctl restart litellm-gateway  # 只重载网关，秒级

# 停止 / 启动
sudo systemctl stop litellm-gateway vllm-minimax
sudo systemctl start vllm-minimax litellm-gateway
```

> 注意依赖顺序：`litellm-gateway` 在 unit 里声明了 `Requires=vllm-minimax.service`，stop vLLM 会连带停网关。

## 日志

```bash
# 实时
journalctl -u vllm-minimax -f
journalctl -u litellm-gateway -f

# 最近 500 行
journalctl -u vllm-minimax -n 500 --no-pager

# 按时间段
journalctl -u litellm-gateway --since "2 hours ago"
```

## 查看用户请求记录 / 语料

所有请求都落在本机 Postgres，用 `psql` 直接查。连接串就是 `/etc/llm-deploy.env` 里的 `POSTGRES_URL`。

```bash
source /etc/llm-deploy.env
psql "$POSTGRES_URL"
```

常用查询：

```sql
-- 最近 20 条请求（含 token 用量、耗时、调用的 key）
SELECT "startTime", "user", "api_key", "model", "total_tokens",
       "spend", EXTRACT(EPOCH FROM ("endTime" - "startTime")) AS latency_s
FROM "LiteLLM_SpendLogs"
ORDER BY "startTime" DESC
LIMIT 20;

-- 某个 key 今天用了多少 token
SELECT "api_key", SUM("total_tokens") AS tokens, COUNT(*) AS requests
FROM "LiteLLM_SpendLogs"
WHERE "startTime" >= CURRENT_DATE
GROUP BY "api_key";

-- 完整 prompt + response（JSON 列）
SELECT "startTime", "messages", "response"
FROM "LiteLLM_SpendLogs"
ORDER BY "startTime" DESC
LIMIT 5;

-- 某次具体对话（按 request_id）
SELECT * FROM "LiteLLM_SpendLogs" WHERE "request_id" = '<req-id>';
```

导出语料到 JSONL：

```bash
psql "$POSTGRES_URL" -Atc \
  "SELECT row_to_json(t) FROM (
     SELECT \"startTime\", \"user\", \"model\", \"messages\", \"response\"
     FROM \"LiteLLM_SpendLogs\"
     WHERE \"startTime\" >= NOW() - INTERVAL '1 day'
   ) t" \
  > /tmp/corpus-$(date +%F).jsonl
```

## 管理 API key（多租户）

master key 不建议分发给终端用户，用它来签发子 key：

```bash
# 为用户 alice 签发一个 key，日预算 10 美元等价 token
curl -X POST http://127.0.0.1:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"alice","max_budget":10,"budget_duration":"1d","models":["minimax-m2.5"]}'

# 查所有 key
curl http://127.0.0.1:4000/key/info \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# 删除
curl -X POST http://127.0.0.1:4000/key/delete \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"keys":["sk-..."]}'
```

签发的子 key 直接就可以填到客户端（见 `clients.md`）。

## 常见故障

| 症状 | 排查 |
|------|------|
| `vllm-minimax` 反复 `Restart=on-failure` | `journalctl -u vllm-minimax -n 200`：多半是 CUDA OOM 或权重路径错。OOM 时把 `/etc/llm-deploy.env` 的 `VLLM_SAFE_MODE=1` 打开再重启 |
| `litellm-gateway` 起不来，日志报 `database ... does not exist` | 没跑 `init_postgres.sh`，或 `POSTGRES_URL` 写错 |
| 客户端报 `401 Unauthorized` | 客户端用的 key 不对；查 `LiteLLM_VerificationToken` 表或用 `/key/info` 核对 |
| `/v1/messages` 返回 404 | LiteLLM 版本太老，升级到支持 Anthropic passthrough 的版本后重装依赖 |
| `nvidia-smi` 有几张卡显存空着 | TP 没起到 8；查 vLLM 日志里的 `tensor_parallel_size` 行，以及 `NCCL_*` 错误 |
| 推理极慢 | 确认 `max_model_len` 没开过大；确认没启用 `--compilation-config PIECEWISE`（仅在 OOM 时才打开）|

## 升级 vLLM / LiteLLM

```bash
sudo systemctl stop litellm-gateway vllm-minimax
sudo -u llm ENV_FILE=/etc/llm-deploy.env bash /opt/llm-deploy/scripts/install_deps.sh
sudo systemctl start vllm-minimax litellm-gateway
```

## 备份

只需备份两样东西：

1. `/etc/llm-deploy.env`（含 master key 和 DB 密码）
2. Postgres 库 `litellm`：`pg_dump "$POSTGRES_URL" > litellm-$(date +%F).sql`
