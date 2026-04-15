# scripts/_conda.sh
# 被 install_deps.sh / start_vllm.sh / start_litellm.sh source。
# 负责找到 conda 安装、source `conda.sh`，让调用方接着 `conda activate` 即可。
#
# 输入（均可在 /etc/llm-deploy.env 里设置）:
#   CONDA_ENV   - conda 环境名，默认 llm-deploy
#   CONDA_BASE  - conda 根目录绝对路径，留空则自动探测

CONDA_ENV=${CONDA_ENV:-llm-deploy}

if [[ -z "${CONDA_BASE:-}" && -n "${CONDA_EXE:-}" ]]; then
    CONDA_BASE="$("$CONDA_EXE" info --base 2>/dev/null || true)"
fi

if [[ -z "${CONDA_BASE:-}" || ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ]]; then
    for p in /opt/conda /opt/miniconda3 /opt/anaconda3 \
             /root/miniconda3 /root/anaconda3 \
             "$HOME/miniconda3" "$HOME/anaconda3"; do
        if [[ -f "$p/etc/profile.d/conda.sh" ]]; then
            CONDA_BASE="$p"
            break
        fi
    done
fi

if [[ -z "${CONDA_BASE:-}" || ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ]]; then
    echo "[_conda] 找不到 conda 安装。请在 ${ENV_FILE:-/etc/llm-deploy.env} 里设置 CONDA_BASE=<conda 根目录>" >&2
    return 1 2>/dev/null || exit 1
fi

# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
