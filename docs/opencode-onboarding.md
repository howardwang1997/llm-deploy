# OpenCode 接入指南

写给要在自己本机上用 OpenCode 接入内网 MiniMax-M2.5 服务的同事。从零开始，按顺序做完就能跑通。

> 如果你已经熟悉 Node / OpenCode，只想看最小配置，直接跳到第 4 节即可；更多客户端（Claude Code / Cline / SDK / curl）见 [`clients.md`](clients.md)。

---

## 0. 前置条件

- 你的机器和 H20 推理服务在**同一局域网**里，能直接访问 `<h20-host>:4000`（HTTP，**没有 TLS**）。
- 已经向管理员拿到了专属 API key（形如 `sk-...`）。没有的话先按第 2 节流程去要。
- macOS / Linux / WSL 任意一个。纯 Windows 也行，命令里的 `curl`/`bash` 需要自己替换成 PowerShell 写法。

下文用 `<h20-host>` 表示 H20 真实的主机名或局域网 IP，用 `<your-key>` 表示你自己的 API key。**请填真值，别照抄尖括号**。

---

## 1. 安装 Node.js

OpenCode 推荐通过 npm 安装，需要 Node.js 18 或以上。

### macOS

用 Homebrew：

```bash
brew install node
```

### Linux（Debian / Ubuntu）

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

### 通用（推荐：nvm 管多版本）

```bash
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
# 重开终端
nvm install 20
nvm use 20
```

### 验证

```bash
node -v    # 期望：v18.x 或更高
npm -v
```

> **嫌装 Node 麻烦？** OpenCode 也提供**免 Node** 的一行安装脚本（第 3 节有）。但后续有的小工具还是会用到 `npm`，一般建议还是装上。

---

## 2. 拿到 API Key

**不要使用 master key**，每个人应该用自己的专属子 key，方便管理员做额度和审计。

向管理员发一条消息，说明你需要 key 用来接入内网 MiniMax-M2.5。管理员会从 `/key/generate` 签发一个只有 `minimax-m2.5` 模型权限、带日预算限制的子 key 给你。

你会收到一串形如：

```
sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

的字符串。**保管好**：

- 不要提交到 git。
- 不要贴到公开聊天群或截图。
- 丢了就找管理员重发，不要追问别人借用。

> 管理员如果要**批量为多人签发**，见文末「管理员视角：批量签发 key」一节。

---

## 3. 安装 OpenCode

任选一种，推荐第 1 种：

```bash
# 1. npm（需要 Node.js）
npm install -g opencode-ai

# 2. 免 Node 的 standalone 脚本
curl -fsSL https://opencode.ai/install | bash

# 3. macOS Homebrew
brew install anomalyco/tap/opencode
```

验证：

```bash
opencode --version
```

---

## 4. 配置 OpenCode 指向内网服务

OpenCode 的配置文件是 `~/.config/opencode/opencode.json`（Linux / macOS）。新建或编辑，填入：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "minimax-lan": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "MiniMax (LAN)",
      "options": {
        "baseURL": "http://<h20-host>:4000/v1",
        "apiKey": "<your-key>"
      },
      "models": {
        "minimax-m2.5": {
          "name": "MiniMax-M2.5"
        }
      }
    }
  }
}
```

几个**常见踩坑点**：

- `baseURL` 必须以 `/v1` 结尾，走的是 OpenAI 协议。
- `<h20-host>` 建议填**主机名**而不是裸 IP——IP 改了以后不用全员改配置。如果没有内网 DNS，就填 IP。
- `apiKey` 是你自己的子 key，不是 master key。

---

## 5. 第一次跑通

**先用 curl 确认网络通**：

```bash
curl http://<h20-host>:4000/v1/chat/completions \
  -H "Authorization: Bearer <your-key>" \
  -H "Content-Type: application/json" \
  -d '{"model":"minimax-m2.5","messages":[{"role":"user","content":"用一句话介绍你自己"}]}'
```

拿到一段 JSON 就算成功。如果这步都失败，别再折腾 OpenCode 了，按第 6 节先修网络。

**再启动 OpenCode**：

```bash
opencode
```

进入 TUI 后确认左下角显示的模型是 `MiniMax-M2.5`，然后打一句 `hi` 试水。

也可以直接命令行指定模型：

```bash
opencode --model minimax-lan/minimax-m2.5
```

---

## 6. 排查常见问题

### "API Connection Not Connected" / `ConnectionRefused`

这是**网络层**问题，99% 不是配置写法问题。按顺序查：

```bash
# 1. 你配的 URL 能 curl 通吗？
curl -v http://<h20-host>:4000/health

# 2. TCP 层面能连上吗？
nc -vz <h20-host> 4000
```

如果都连不上：

- `<h20-host>` 打错了，或跟配置文件里的不一致。
- 服务那边没起来，找管理员看 `systemctl status litellm-gateway`。
- 公司防火墙 / VPN 没给你放行。

### `401 Unauthorized`

- 你的 key 过期 / 被删 / 额度超了，找管理员。
- 把 key 复制进来时多带了空格或引号。

### OpenCode 无响应但也不报错

先看日志，OpenCode 自己的日志在：

```bash
~/.local/share/opencode/log/
```

按时间戳命名，打开**最新的那一份** `.log` 文件，搜这几个关键字：

```
error | ConnectionRefused | ENOTFOUND | ETIMEDOUT | 401 | 403 | 404
```

看到的 `path=http://...` 就是 OpenCode 真正打过去的 URL，能直接对照配置找错。

想看更详细的日志，加 `--log-level DEBUG` 启动：

```bash
opencode --log-level DEBUG
```

### 模型列表里没有 minimax-m2.5

配置没读到。确认：

- `~/.config/opencode/opencode.json` 路径对，不是 `.jsonc` 也不是别的名。
- JSON 没写错（拿 `python -m json.tool ~/.config/opencode/opencode.json` 过一遍）。
- 你启动 OpenCode 的账号能读这个文件（权限别设错）。

---

## 7. 推荐采样参数

MiniMax 官方推荐：

```
temperature = 1.0
top_p       = 0.95
top_k       = 40
```

网关侧（`config/litellm.yaml`）已经把前两项作为默认值写好了；OpenCode 里一般不用再覆盖。

---

## 管理员视角：批量签发 key

> 这一节**仅管理员需要**，普通用户跳过。

LiteLLM 只有**一个 master key**（部署时写进 `/etc/llm-deploy.env` 的 `LITELLM_MASTER_KEY`），它不应该分发出去。日常要做的是用 master key 调 `/key/generate`，**为每个同事签发一个子 key**。单个签发命令见 [`operate.md`](operate.md) 的「管理 API key」一节。

下面这段脚本批量签发，一键给一组人每人一个 key，打印成 `user <TAB> key` 格式，方便复制粘贴分发：

```bash
#!/usr/bin/env bash
set -euo pipefail

# 编辑这两项：
USERS=(alice bob carol dave)
MAX_BUDGET_USD=10              # 每日预算
BUDGET_DURATION="1d"           # 1d / 1w / 30d
MODELS='["minimax-m2.5"]'

BASE="http://127.0.0.1:4000"   # 管理员在 H20 host 上执行
source /etc/llm-deploy.env     # 拿到 LITELLM_MASTER_KEY

printf "user\tkey\n"
for u in "${USERS[@]}"; do
    resp=$(curl -sS -X POST "$BASE/key/generate" \
        -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
        -H "Content-Type: application/json" \
        -d "{
            \"user_id\": \"$u\",
            \"max_budget\": $MAX_BUDGET_USD,
            \"budget_duration\": \"$BUDGET_DURATION\",
            \"models\": $MODELS,
            \"metadata\": {\"issued_for\": \"$u\"}
        }")
    key=$(python3 -c 'import sys,json; print(json.load(sys.stdin)["key"])' <<<"$resp")
    printf "%s\t%s\n" "$u" "$key"
done
```

用法：

```bash
bash issue-keys.sh > /tmp/keys.tsv
# 然后用私聊 / 密码管理器分发 /tmp/keys.tsv 里对应的行给每位同事
# 用完立刻 shred -u /tmp/keys.tsv
```

已签发的 key 后续可以：

- 改预算：`curl -X POST $BASE/key/update ...`
- 查用量：见 [`operate.md`](operate.md) 的 SQL 示例。
- 吊销：`curl -X POST $BASE/key/delete -d '{"keys":["sk-..."]}'`

> **误区澄清**：LiteLLM 只支持一个 master key；"生成多个 master key" 这种操作是不存在的。你真正需要的是「一个 master key + 很多子 key」——上面这个脚本就是干这个的。master key 如果怀疑泄漏，去改 `/etc/llm-deploy.env` 里的 `LITELLM_MASTER_KEY` 再 `systemctl restart litellm-gateway` 轮换。
