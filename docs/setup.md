# 部署流程（首次安装）

面向一台 8×H20 离线机器，从零到服务可用。所有命令都在 **H20 机器上** 以 **root** 身份执行，通过局域网 PyPI 镜像 / yum(apt) 镜像拉依赖。

> 本方案默认整机独占、直接用 root 跑服务，不再单独建 `llm` 系统用户。如果你需要最小权限隔离，自己 `useradd` 一个 `llm` 用户并相应改下面的路径和 systemd unit 里的 `User=` 字段即可。

## 0. 前置条件

- `nvidia-smi` 可见 8 张 H20，驱动 ≥ 535，CUDA runtime 12.x。
- 机器可以通过局域网访问：
  - PyPI 镜像（或者配置了 HTTPS_PROXY 可访问 pypi.org）
  - 操作系统包镜像（yum / apt），用于装 `python3.11` 和 `postgresql-server`
- MiniMax-M2.5 权重已经在本机磁盘上，目录内含 `config.json`、`tokenizer*`、所有 `*.safetensors` shard。

## 1. 准备目录

仓库代码和模型权重都放在 `/AI4S/Users/` 下：

| 用途 | 路径 |
|------|------|
| 本仓库代码 | `/AI4S/Users/howardwang/llm-deploy` |
| MiniMax-M2.5 权重 | `/AI4S/Users/MiniMax-M2.5` |
| Python venv | `/AI4S/Users/howardwang/llm-deploy/venv`（`install_deps.sh` 会自动建） |

如果是第一次上这台机器，`git clone` 或 `rsync` 到上述路径即可：

```bash
mkdir -p /AI4S/Users/howardwang
git clone <repo-url> /AI4S/Users/howardwang/llm-deploy
# 或 rsync -a <source>/llm-deploy/ /AI4S/Users/howardwang/llm-deploy/
```

> 下文所有命令都用 `/AI4S/Users/howardwang/llm-deploy` 作为仓库路径。如果你把仓库放在别处，把这段路径替换成实际位置即可（systemd unit 里的 `WorkingDirectory` / `ExecStart`、脚本里的 `VENV_DIR` / `LITELLM_CONFIG` 默认值也要跟着改）。

## 2. 装系统级依赖（通过局域网镜像）

按你机器的发行版选一套装包：

```bash
# CentOS / RHEL / AlibabaLinux
yum install -y python3.11 postgresql-server postgresql-contrib

# Debian / Ubuntu
apt-get install -y python3.11 python3.11-venv postgresql
```

接下来 Postgres 的 **初始化 + 启动** 分两种环境，下面第 2.A / 2.B 二选一。

### 2.A 有 systemd 的机器（标准裸机）

```bash
# RHEL 家族
/usr/bin/postgresql-setup --initdb
systemctl enable --now postgresql

# Debian / Ubuntu: 装完包已经自动 initdb + start
systemctl enable --now postgresql
```

### 2.B 无 systemd 的机器（容器 / chroot）

表现：`systemctl ...` 报 `System has not been booted with systemd as init system (PID 1). Can't operate.`，`postgresql-setup --initdb` 也跟着报 `FATAL: no db datadir (PGDATA) configured for 'postgresql.service' unit`（因为它读的是 systemd unit 里的 PGDATA）。

绕开 `postgresql-setup`，直接调 `initdb` + `pg_ctl`：

```bash
# PGDATA 目录（RHEL 家族默认位置；Debian 系用 /var/lib/postgresql/<ver>/main 也可以）
export PGDATA=/var/lib/pgsql/data
mkdir -p "$PGDATA"
chown -R postgres:postgres /var/lib/pgsql

# 初始化数据目录
runuser -u postgres -- /usr/bin/initdb -D "$PGDATA"

# 启动（日志写到 logfile）
runuser -u postgres -- /usr/bin/pg_ctl -D "$PGDATA" -l /var/lib/pgsql/logfile start

# 验证
runuser -u postgres -- psql -c "SELECT version();"
```

> 这种环境下后面第 6 步也要走无 systemd 的替代路径（第 6.B）。

## 3. 填写环境变量文件

```bash
cp /AI4S/Users/howardwang/llm-deploy/config/env.example /etc/llm-deploy.env
chmod 600 /etc/llm-deploy.env
${EDITOR:-vi} /etc/llm-deploy.env
```

至少要设置：

- `MODEL_PATH` — MiniMax-M2.5 权重目录绝对路径（本机为 `/AI4S/Users/MiniMax-M2.5`，`env.example` 已填好）
- `LITELLM_MASTER_KEY` — `openssl rand -hex 24` 生成一个
- `POSTGRES_URL` — 例如 `postgresql://litellm:$(openssl rand -hex 16)@127.0.0.1:5432/litellm`
- `PIP_INDEX_URL` + `PIP_TRUSTED_HOST`（或 `HTTPS_PROXY`），指向局域网镜像

## 4. 初始化 Postgres

```bash
bash /AI4S/Users/howardwang/llm-deploy/scripts/init_postgres.sh
```

脚本会按 `POSTGRES_URL` 里的 user/password/dbname 建角色、建库、授权，并做一次连通性测试。

## 5. 安装 Python 依赖

```bash
ENV_FILE=/etc/llm-deploy.env bash /AI4S/Users/howardwang/llm-deploy/scripts/install_deps.sh
```

这一步最耗时（vLLM 会拉 torch、flash-attn、xformers 等大 wheel，总计几 GB）。如果卡在某个包上，通常是镜像里缺对应 CUDA 版本的 wheel —— 让运维补进镜像后重跑即可。

### 排障：prisma engine 下载失败

LiteLLM 用 prisma 做 ORM，`prisma generate` 会去 `binaries.prisma.sh` 拉 query engine 二进制。如果被墙：

```bash
# 让代理只对 prisma 的域名生效
export HTTPS_PROXY=http://<proxy>:<port>
source /AI4S/Users/howardwang/llm-deploy/venv/bin/activate
python -m prisma generate --schema "$(python -c 'import litellm,os;print(os.path.join(os.path.dirname(litellm.__file__),"proxy","schema.prisma"))')"
unset HTTPS_PROXY
```

或者提前把 prisma engine 二进制放到 `~/.cache/prisma-python/binaries/<version>/<hash>/` 下。

## 6. 拉起服务

和第 2 步一样分两种路径，按你机器情况二选一。

第一次启动 vLLM 会加载 ~460GB 权重到 8 张卡上，冷启动需要 3–10 分钟，耐心等。看到 `Uvicorn running on http://127.0.0.1:8000` 就是 vLLM 就绪；看到 `Uvicorn running on http://0.0.0.0:4000` 就是 LiteLLM 就绪。

### 6.A 有 systemd 的机器

```bash
cp /AI4S/Users/howardwang/llm-deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now vllm-minimax.service litellm-gateway.service

# watch 日志
journalctl -u vllm-minimax -f
journalctl -u litellm-gateway -f
```

### 6.B 无 systemd 的机器（容器 / chroot）

直接用 `nohup` 把两个启动脚本拉到后台，日志落盘到文件。先起 vLLM，等它就绪后再起 LiteLLM（LiteLLM 启动时会去打 `http://127.0.0.1:8000/v1/models`，空打会炸）。

```bash
mkdir -p /var/log/llm-deploy

# 1. 拉起 vLLM
ENV_FILE=/etc/llm-deploy.env nohup bash /AI4S/Users/howardwang/llm-deploy/scripts/start_vllm.sh \
    >> /var/log/llm-deploy/vllm.log 2>&1 &
echo $! > /var/run/vllm-minimax.pid

# 2. 等 vLLM 就绪（脚本会轮询 /v1/models，最多等 10 分钟）
ENV_FILE=/etc/llm-deploy.env bash /AI4S/Users/howardwang/llm-deploy/scripts/healthcheck.sh vllm

# 3. 拉起 LiteLLM 网关
ENV_FILE=/etc/llm-deploy.env nohup bash /AI4S/Users/howardwang/llm-deploy/scripts/start_litellm.sh \
    >> /var/log/llm-deploy/litellm.log 2>&1 &
echo $! > /var/run/litellm-gateway.pid

# 4. watch 日志
tail -f /var/log/llm-deploy/vllm.log
tail -f /var/log/llm-deploy/litellm.log
```

停 / 重启：

```bash
# 停（先停网关，再停 vLLM）
kill "$(cat /var/run/litellm-gateway.pid)"
kill "$(cat /var/run/vllm-minimax.pid)"

# 如果 pid 文件丢了，按进程名杀
pkill -f 'litellm --config'
pkill -f 'vllm serve'
```

如果希望重启后自动拉起，挂一个 `supervisord` / `runit` / tmux session 管生命周期，这里不展开。

## 7. 端到端验证

```bash
bash /AI4S/Users/howardwang/llm-deploy/scripts/healthcheck.sh e2e
```

应看到两条 JSON 响应（OpenAI 和 Anthropic 协议各一发）。

同时在另一台局域网机器上：

```bash
curl http://<h20-host>:4000/v1/models \
    -H "Authorization: Bearer <LITELLM_MASTER_KEY>"
```

应返回 `{"data":[{"id":"minimax-m2.5",...}]}`。

完成。接入客户端见 `docs/clients.md`，日常运维见 `docs/operate.md`。
