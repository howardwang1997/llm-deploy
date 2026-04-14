# 客户端接入指南

LiteLLM 网关同时暴露两套协议，客户端按自己原生协议接入即可：

- **OpenAI 协议**：`POST http://<h20-host>:4000/v1/chat/completions`
- **Anthropic 协议**：`POST http://<h20-host>:4000/v1/messages`

所有客户端都用同一个模型名 `minimax-m2.5`，同一个 API key（master key 或由 master key 签发的子 key，签发方式见 `operate.md`）。

下文把 `<h20-host>` 写成你实际的局域网 IP 或域名，把 `<key>` 替换成你的 API key。

---

## curl smoke test

```bash
# OpenAI
curl http://<h20-host>:4000/v1/chat/completions \
  -H "Authorization: Bearer <key>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "minimax-m2.5",
    "messages": [{"role":"user","content":"用一句话介绍你自己"}]
  }'

# Anthropic
curl http://<h20-host>:4000/v1/messages \
  -H "x-api-key: <key>" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "minimax-m2.5",
    "max_tokens": 256,
    "messages": [{"role":"user","content":"用一句话介绍你自己"}]
  }'
```

---

## Claude Code

Claude Code 支持把 Anthropic 端点切到任意兼容后端：

```bash
export ANTHROPIC_BASE_URL=http://<h20-host>:4000
export ANTHROPIC_AUTH_TOKEN=<key>
export ANTHROPIC_MODEL=minimax-m2.5
# 可选：把 small / haiku 模型也指到同一个，避免 Claude Code 去调未配置的模型
export ANTHROPIC_SMALL_FAST_MODEL=minimax-m2.5

claude
```

把这些写进 `~/.bashrc` 或 `~/.zshrc` 就可以常驻。

## OpenCode

```bash
export OPENAI_BASE_URL=http://<h20-host>:4000/v1
export OPENAI_API_KEY=<key>
opencode --model minimax-m2.5
```

或在 OpenCode 配置文件里把 provider 设为 `openai`，`baseUrl` 指向上面地址。

## Cline / Roo-Code / Continue（VS Code 扩展）

在扩展设置里选 **OpenAI Compatible** provider：

- Base URL: `http://<h20-host>:4000/v1`
- API Key: `<key>`
- Model: `minimax-m2.5`

## Aider

```bash
export OPENAI_API_BASE=http://<h20-host>:4000/v1
export OPENAI_API_KEY=<key>
aider --model openai/minimax-m2.5
```

## OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://<h20-host>:4000/v1",
    api_key="<key>",
)

resp = client.chat.completions.create(
    model="minimax-m2.5",
    messages=[{"role": "user", "content": "hello"}],
)
print(resp.choices[0].message.content)
```

## Anthropic Python SDK

```python
import anthropic

client = anthropic.Anthropic(
    base_url="http://<h20-host>:4000",
    api_key="<key>",
)

msg = client.messages.create(
    model="minimax-m2.5",
    max_tokens=512,
    messages=[{"role": "user", "content": "hello"}],
)
print(msg.content[0].text)
```

---

## 推荐采样参数

MiniMax 官方建议：

```
temperature = 1.0
top_p       = 0.95
top_k       = 40
```

`config/litellm.yaml` 已经把 `temperature` / `top_p` 作为默认值写进去了，客户端可以覆盖。
