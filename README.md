# llm-deploy

在一台 8×NVIDIA H20（离线，仅局域网可达）机器上部署 **MiniMax-M2.5** 推理服务。

## 架构一眼

```
Client (LAN)                           H20 host
┌──────────────┐                       ┌─────────────────────────────────┐
│ Claude Code  │── Anthropic ────┐     │                                 │
│ OpenCode     │── OpenAI ───────┤     │  LiteLLM :4000 ──► vLLM :8000   │
│ OpenAI SDK   │── OpenAI ───────┘     │       │               │         │
│ curl         │── either ────────────►│       ▼               ▼         │
└──────────────┘                       │   Postgres       8× H20 GPU     │
                                       │  (全量日志)                     │
                                       └─────────────────────────────────┘
```

- **vLLM**：只监听 `127.0.0.1:8000`，TP=8 + expert-parallel 跑 MiniMax-M2.5。
- **LiteLLM**：监听 `0.0.0.0:4000`，对外入口。同时支持 OpenAI `/v1/chat/completions` 和 Anthropic `/v1/messages`，带 master key 鉴权和完整 prompt/completion 审计日志。
- **Postgres**：本机运行，存 LiteLLM 的 key、额度、完整请求/响应记录。
- **systemd**：`vllm-minimax.service` + `litellm-gateway.service` 两个 unit 管生命周期，后者依赖前者。

## 目录

```
llm-deploy/
├── config/
│   ├── env.example          # 环境变量模板（必填 MODEL_PATH / MASTER_KEY / POSTGRES_URL）
│   └── litellm.yaml         # LiteLLM 网关配置
├── scripts/
│   ├── install_deps.sh      # 通过局域网 PyPI 镜像装 vllm / litellm[proxy]
│   ├── init_postgres.sh     # 建库建用户
│   ├── start_vllm.sh        # systemd exec 的 vLLM 启动器
│   ├── start_litellm.sh     # systemd exec 的 LiteLLM 启动器
│   └── healthcheck.sh       # vllm / gateway / e2e 三种探活模式
├── systemd/
│   ├── vllm-minimax.service
│   └── litellm-gateway.service
└── docs/
    ├── setup.md             # 首次部署从零到跑通
    ├── operate.md           # 日常运维、日志、查询语料、管理 API key
    └── clients.md           # Claude Code / OpenCode / SDK / curl 接入示例
```

## 快速上手

1. 按 [`docs/setup.md`](docs/setup.md) 从零装一遍（建用户 → 建目录 → 装系统包 → 填 env → 初始化 Postgres → 装 Python 依赖 → 起 systemd → 跑 e2e 探活）。
2. 服务起来之后，在另一台局域网机器上按 [`docs/clients.md`](docs/clients.md) 配 Claude Code / OpenCode / SDK。
3. 日常运维（查日志、查语料、签发子 key、升级）见 [`docs/operate.md`](docs/operate.md)。

## 必须满足的前提

- GPU 驱动 ≥ 535，`nvidia-smi` 可见 8 张 H20。
- 局域网里有 PyPI 镜像或 HTTPS 代理，能拉 `vllm` / `litellm[proxy]`（及它们依赖的 torch / flash-attn CUDA wheel）。
- 已装好 Miniconda / Anaconda；服务跑在 conda env `llm-deploy` 里（由 `install_deps.sh` 自动创建，Python 3.11）。
- 系统包镜像里有 `postgresql-server`。
- MiniMax-M2.5 权重已在磁盘上，目录完整（`config.json` + `tokenizer*` + 所有 safetensors shard）。

## 不覆盖的场景

- TLS / HTTPS —— 只跑 HTTP，如需 TLS 自己前挂 Nginx。
- 多机 / 多副本 —— 只有这一台。
- Docker —— 选了 pip + systemd 的裸机方案。
- 模型微调 —— 仅推理服务。
