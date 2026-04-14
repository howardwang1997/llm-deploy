# 部署流程（首次安装）

面向一台 8×H20 离线机器，从零到服务可用。所有命令都在 **H20 机器上**执行，通过局域网 PyPI 镜像 / yum(apt) 镜像拉依赖。

## 0. 前置条件

- `nvidia-smi` 可见 8 张 H20，驱动 ≥ 535，CUDA runtime 12.x。
- 机器可以通过局域网访问：
  - PyPI 镜像（或者配置了 HTTPS_PROXY 可访问 pypi.org）
  - 操作系统包镜像（yum / apt），用于装 `python3.11` 和 `postgresql-server`
- MiniMax-M2.5 权重已经在本机磁盘上，目录内含 `config.json`、`tokenizer*`、所有 `*.safetensors` shard。

## 1. 准备系统账号和目录

```bash
# 跑服务的 OS 用户
sudo useradd -r -m -d /var/lib/llm -s /bin/bash llm

# 仓库目录（本仓库的代码放这里）
sudo mkdir -p /opt/llm-deploy
sudo chown -R llm:llm /opt/llm-deploy

# 假设你已经在本机或另一台机器 clone 了这个仓库，rsync 过来
sudo -u llm rsync -a <source>/llm-deploy/ /opt/llm-deploy/
```

## 2. 装系统级依赖（通过局域网镜像）

按你机器的发行版选一套：

```bash
# CentOS / RHEL / AlibabaLinux
sudo yum install -y python3.11 postgresql-server postgresql-contrib
sudo /usr/bin/postgresql-setup --initdb
sudo systemctl enable --now postgresql

# Debian / Ubuntu
sudo apt-get install -y python3.11 python3.11-venv postgresql
sudo systemctl enable --now postgresql
```

## 3. 填写环境变量文件

```bash
sudo cp /opt/llm-deploy/config/env.example /etc/llm-deploy.env
sudo chmod 600 /etc/llm-deploy.env
sudo chown llm:llm /etc/llm-deploy.env
sudoedit /etc/llm-deploy.env
```

至少要设置：

- `MODEL_PATH` — MiniMax-M2.5 权重目录绝对路径
- `LITELLM_MASTER_KEY` — `openssl rand -hex 24` 生成一个
- `POSTGRES_URL` — 例如 `postgresql://litellm:$(openssl rand -hex 16)@127.0.0.1:5432/litellm`
- `PIP_INDEX_URL` + `PIP_TRUSTED_HOST`（或 `HTTPS_PROXY`），指向局域网镜像

## 4. 初始化 Postgres

```bash
sudo bash /opt/llm-deploy/scripts/init_postgres.sh
```

脚本会按 `POSTGRES_URL` 里的 user/password/dbname 建角色、建库、授权，并做一次连通性测试。

## 5. 安装 Python 依赖

```bash
sudo -u llm ENV_FILE=/etc/llm-deploy.env bash /opt/llm-deploy/scripts/install_deps.sh
```

这一步最耗时（vLLM 会拉 torch、flash-attn、xformers 等大 wheel，总计几 GB）。如果卡在某个包上，通常是镜像里缺对应 CUDA 版本的 wheel —— 让运维补进镜像后重跑即可。

### 排障：prisma engine 下载失败

LiteLLM 用 prisma 做 ORM，`prisma generate` 会去 `binaries.prisma.sh` 拉 query engine 二进制。如果被墙：

```bash
# 让代理只对 prisma 的域名生效
export HTTPS_PROXY=http://<proxy>:<port>
source /opt/llm-deploy/venv/bin/activate
python -m prisma generate --schema "$(python -c 'import litellm,os;print(os.path.join(os.path.dirname(litellm.__file__),"proxy","schema.prisma"))')"
unset HTTPS_PROXY
```

或者提前把 prisma engine 二进制放到 `~/.cache/prisma-python/binaries/<version>/<hash>/` 下。

## 6. 安装 systemd unit

```bash
sudo cp /opt/llm-deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vllm-minimax.service litellm-gateway.service
```

第一次启动 vLLM 会加载 ~460GB 权重到 8 张卡上，冷启动需要 3–10 分钟；watch：

```bash
journalctl -u vllm-minimax -f
```

看到 `Uvicorn running on http://127.0.0.1:8000` 就是就绪。

## 7. 端到端验证

```bash
sudo -u llm bash /opt/llm-deploy/scripts/healthcheck.sh e2e
```

应看到两条 JSON 响应（OpenAI 和 Anthropic 协议各一发）。

同时在另一台局域网机器上：

```bash
curl http://<h20-host>:4000/v1/models \
    -H "Authorization: Bearer <LITELLM_MASTER_KEY>"
```

应返回 `{"data":[{"id":"minimax-m2.5",...}]}`。

完成。接入客户端见 `docs/clients.md`，日常运维见 `docs/operate.md`。
