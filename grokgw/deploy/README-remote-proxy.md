# grokgw 远程 proxy 部署（无 SOCKS + SSH 隧道）

在 VPS 上用 **proxy 后端**直连 `api.x.ai`，**不使用** socks5。服务只绑 `127.0.0.1:8787`，本机经 SSH 隧道访问。

**不要**在远程跑仓库根目录 `install.sh` 的默认配置（会写死 `GROKGW_BACKEND=cli` 和 `ALL_PROXY=…2080`）。

## 前置

- SuperGrok 已在本机 `grok login`，有 `~/.grok/auth.json`
- 服务器 Python ≥ 3.12、git、curl
- 服务器能直连 `https://api.x.ai`（无需代理）

## 部署步骤

### 1. 认证

```bash
ssh root@SERVER 'mkdir -p /root/.grok && chmod 700 /root/.grok'
scp ~/.grok/auth.json root@SERVER:/root/.grok/auth.json
ssh root@SERVER 'chmod 600 /root/.grok/auth.json'
```

### 2. 源码与 venv

```bash
git clone --depth 1 -b main https://github.com/devwork2454/grokgw.git /opt/grokgw
cd /opt/grokgw
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e ./grokgw
```

### 3. 环境变量

```bash
mkdir -p /etc/grokgw
cp /opt/grokgw/grokgw/deploy/remote-proxy.env.example /etc/grokgw/proxy.env
# 若 clone 后布局不同，路径可能是 /opt/grokgw/deploy/...
openssl rand -hex 24   # 写入 GROKGW_API_KEY=
chmod 600 /etc/grokgw/proxy.env
```

确认：`GROKGW_BACKEND=proxy`、`GROKGW_PROXY_MODE=never`、`GROKGW_PROXY_URL=` 为空、`GROKGW_HOST=127.0.0.1`。

### 4. systemd

```bash
cp /opt/grokgw/grokgw/deploy/grokgw-proxy.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now grokgw-proxy
systemctl status grokgw-proxy
curl -sS http://127.0.0.1:8787/healthz
```

### 5. 本机隧道与调用

```bash
ssh -N -L 8787:127.0.0.1:8787 root@SERVER

curl -sS http://127.0.0.1:8787/healthz
curl -sS http://127.0.0.1:8787/v1/chat/completions \
  -H "Authorization: Bearer $GROKGW_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Hello"}]}'
```

OpenAI SDK / OpenCode：

```text
base_url = http://127.0.0.1:8787/v1
api_key  = 与 GROKGW_API_KEY 相同
```

## 故障

| 症状 | 处理 |
|------|------|
| 客户端 401 | Bearer 与 `/etc/grokgw/proxy.env` 不一致 |
| 上游 auth 过期 | 本机 `grok login` 后重 scp `auth.json` |
| 502 / 连不上 xAI | 服务器 `curl -I https://api.x.ai`；确认 `PROXY_MODE=never` |
| 8787 连不上 | `systemctl status grokgw-proxy`；隧道是否建立 |

## 范围外

- CLI 后端 / 安装 Grok Build / media 生图（阶段 B）
- 公网暴露 8787（若必须：设强 API key + ufw 限制源 IP）
