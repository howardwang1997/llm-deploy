# 运维手册

## 服务生命周期

所有命令都以 root 运行。按部署方式二选一。

### 有 systemd 的机器

```bash
# 状态
systemctl status vllm-minimax litellm-gateway

# 重启（改 config/litellm.yaml 或 /etc/llm-deploy.env 后）
systemctl restart vllm-minimax     # 重载 vLLM，耗时 3-10 分钟
systemctl restart litellm-gateway  # 只重载网关，秒级

# 停止 / 启动
systemctl stop litellm-gateway vllm-minimax
systemctl start vllm-minimax litellm-gateway
```

> 依赖顺序：`litellm-gateway` 在 unit 里声明了 `Requires=vllm-minimax.service`，stop vLLM 会连带停网关。

### 无 systemd 的机器（容器 / chroot）

走 `nohup` + pid 文件的方式，参见 `docs/setup.md` 第 6.B 节。常用命令：

```bash
# 状态
ps -ef | grep -E 'vllm serve|litellm --config' | grep -v grep

# 停（顺序：先网关，再 vLLM）
kill "$(cat /var/run/litellm-gateway.pid)" 2>/dev/null || pkill -f 'litellm --config'
kill "$(cat /var/run/vllm-minimax.pid)"    2>/dev/null || pkill -f 'vllm serve'

# 启（参照 setup.md 第 6.B 节的 nohup 命令）

# 重启网关（改完 litellm.yaml 或 env 后，只重启网关，避免动 vLLM 冷启动）
kill "$(cat /var/run/litellm-gateway.pid)" && sleep 1
ENV_FILE=/etc/llm-deploy.env nohup bash /AI4S/Users/howardwang/llm-deploy/scripts/start_litellm.sh \
    >> /var/log/llm-deploy/litellm.log 2>&1 &
echo $! > /var/run/litellm-gateway.pid
```

## 日志

### systemd

```bash
# 实时
journalctl -u vllm-minimax -f
journalctl -u litellm-gateway -f

# 最近 500 行
journalctl -u vllm-minimax -n 500 --no-pager

# 按时间段
journalctl -u litellm-gateway --since "2 hours ago"
```

### 无 systemd

日志落在 `/var/log/llm-deploy/` 下（参见 `setup.md` 第 6.B 节的 nohup 命令）：

```bash
tail -f /var/log/llm-deploy/vllm.log
tail -f /var/log/llm-deploy/litellm.log

tail -n 500 /var/log/llm-deploy/vllm.log
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

**推荐通过 admin-api（`:4100`）操作**。它把名单管理和自助签发都包住了，master key 留在服务进程内，不下发、不进 shell history。部署方式见 `setup.md` 第 8 节。

### admin-api：管理员侧

拿 `ADMIN_API_KEY`（在 `/etc/llm-deploy.env` 里）做 Bearer 鉴权。以下命令在任意内网机器上都能跑。

```bash
ADMIN=<ADMIN_API_KEY>
BASE=http://<h20-host>:4100

# 1. 批量上传工号 / 姓名白名单（UPSERT；单次最多 10000 条）
curl -sX POST "$BASE/admin/roster/bulk" \
  -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"entries":[
        {"employee_id":"E001","name":"张三"},
        {"employee_id":"E002","name":"李四"}
      ]}'
# => {"inserted":2,"updated":0,"unchanged":0}

# 2. 名单分页 / 搜索（q 工号或姓名模糊匹配）
curl -s "$BASE/admin/roster?limit=50&offset=0&q=张" \
  -H "Authorization: Bearer $ADMIN"

# 3. 单条详情（含是否已领 key、key 前缀）
curl -s "$BASE/admin/roster/E001" -H "Authorization: Bearer $ADMIN"

# 4. 删除单条（自动作废其已签发 key）
curl -sX DELETE "$BASE/admin/roster/E001" -H "Authorization: Bearer $ADMIN"

# 5. 用量汇总：工号、姓名、key 前缀、spend、max_budget、请求数、token 数
curl -s "$BASE/admin/usage" -H "Authorization: Bearer $ADMIN"
curl -s "$BASE/admin/usage?employee_id=E001" -H "Authorization: Bearer $ADMIN"
```

### admin-api：员工侧

员工不需要任何凭据，只要自己的工号 + 姓名与名单一致就能领 key。所有 `/self/*` 都按来源 IP 做滑窗频控（默认 5 次 / 10 分钟）。

```bash
BASE=http://<h20-host>:4100

# 自助领 key（幂等：已有 key 则签新的并作废旧的）
curl -sX POST "$BASE/self/register" \
  -H "Content-Type: application/json" \
  -d '{"employee_id":"E001","name":"张三"}'
# => {"api_key":"sk-...","key_prefix":"sk-...","expires":"...","max_budget":50,"models":["minimax-m2.5"]}

# key 丢了 / 怀疑泄漏：主动换新 key（效果同 /self/register）
curl -sX POST "$BASE/self/rotate" \
  -H "Content-Type: application/json" \
  -d '{"employee_id":"E001","name":"张三"}'

# 查自己登记状态（不回显 key 原文）
curl -sX POST "$BASE/self/status" \
  -H "Content-Type: application/json" \
  -d '{"employee_id":"E001","name":"张三"}'
```

拿到的 `api_key` 直接填进任何客户端（见 `clients.md`）。**注意响应只返回一次，员工自己保存好；丢了就 /rotate。**

### 应急：绕过 admin-api 直接调 LiteLLM

admin-api 挂掉或需要做奇怪参数（自定义 budget / 模型白名单）时，可以拿 master key 直接调 LiteLLM。`/key/delete` 支持两种删法：**按 key 原文用 `keys`，按 alias 用 `key_aliases`**——admin-api 内部走后者（alias 可从 `admin_employee_keys.litellm_key_alias` 查到）。

```bash
curl -X POST http://127.0.0.1:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"alice","max_budget":10,"budget_duration":"1d","models":["minimax-m2.5"]}'

curl http://127.0.0.1:4000/key/info \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# 按 key 原文删
curl -X POST http://127.0.0.1:4000/key/delete \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"keys":["sk-..."]}'

# 按 alias 删（admin-api 的内部语义）
curl -X POST http://127.0.0.1:4000/key/delete \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key_aliases":["emp-E001-1700000000"]}'
```

这么下发的 key 不会在 `admin_employee_keys` 里留记录，用量汇总看不到（但 `LiteLLM_SpendLogs` 仍有完整日志）。

### admin-api 错误码对照

所有错误响应统一形如 `{"error": "<code>", "message": "<人读文本>"}`。

| HTTP | error             | 触发条件                                              |
|------|-------------------|---------------------------------------------------|
| 400  | validation_error  | 请求体字段缺失/超长/空（FastAPI 原始错误也会出现在这里） |
| 401  | unauthorized      | `/admin/*` Bearer 缺失或错误                         |
| 403  | identity_mismatch | `/self/*` 工号或姓名不在名单里（不区分两者，防嗅探）   |
| 404  | not_found         | `/admin/roster/{id}` GET/DELETE 时工号不在名单         |
| 429  | rate_limited      | `/self/*` 同一 IP 超过 `ADMIN_RATE_LIMIT_PER_IP`      |
| 502  | litellm_unavailable | httpx 连不上 LiteLLM 或 LiteLLM 返 5xx              |
| 502  | litellm_bad_response | LiteLLM 返回里没有 `key` / `token` 字段             |

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

systemd 环境：

```bash
systemctl stop litellm-gateway vllm-minimax
ENV_FILE=/etc/llm-deploy.env bash /AI4S/Users/howardwang/llm-deploy/scripts/install_deps.sh
systemctl start vllm-minimax litellm-gateway
```

无 systemd 环境：先 `kill` 掉两个进程（参见上面"服务生命周期"），跑 `install_deps.sh`，再按 `setup.md` 第 6.B 节的 `nohup` 命令重新拉起。

## 备份

只需备份两样东西：

1. `/etc/llm-deploy.env`（含 master key 和 DB 密码）
2. Postgres 库 `litellm`：`pg_dump "$POSTGRES_URL" > litellm-$(date +%F).sql`

## 跑 admin-api 测试

测试用 `FakeDB` + `httpx.MockTransport` 打桩，**不连真实 Postgres / LiteLLM**，纯进程内。

```bash
# 1. 装测试依赖（只在第一次跑测试时做一次）
INSTALL_DEV=1 bash scripts/install_deps.sh
# 或手动：
# source scripts/_conda.sh && conda activate llm-deploy && pip install -r requirements-dev.txt

# 2. 运行全部测试
cd /AI4S/Users/howardwang/llm-deploy
pytest -q

# 3. 只跑某个模块 / 某个用例
pytest tests/test_routes_self.py -q
pytest tests/test_routes_self.py::TestSelfRegister::test_success_returns_full_key -q
```

写新测试的坑位：`admin_api.config.load()` 在 import 时就执行，`tests/conftest.py` 已经在顶部 `os.environ.setdefault` 了所需的变量；新增测试若要自定义 `Settings`，直接构造 `Settings(...)` 而不是再 import main。
