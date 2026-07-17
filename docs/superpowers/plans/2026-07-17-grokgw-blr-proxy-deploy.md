# grokgw BLR Phase A Deploy (proxy, no SOCKS, SSH tunnel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Progress snapshot (2026-07-17)

| Task | 状态 | 说明 |
|------|------|------|
| Task 1 仓库 deploy 模板 | **DONE** | `grokgw/deploy/*` 已在 main（commit `4e83d53`）；下方 checkbox 可能仍为 `[ ]`，以本表为准 |
| Task 2–7 实机部署与验收 | **TODO** | **当前 ACTIVE 主线**；见 `docs/ROADMAP.md` / `docs/STATUS.md` |

**Goal:** 在 Vultr BLR（`139.84.151.149`）部署 grokgw **proxy 后端**，**不使用 SOCKS 代理**直连 `api.x.ai`，仅本机 **SSH 隧道**访问 `127.0.0.1:8787`，把 SuperGrok 订阅封装成 OpenAI 兼容 API。

**Architecture:** BLR 上裸机 Python venv + systemd 跑 `python -m grokgw`（`GROKGW_BACKEND=proxy`、`GROKGW_PROXY_MODE=never`）。认证来自拷贝的 `~/.grok/auth.json`。对外不开放 8787；操作员本机 `ssh -L 8787:127.0.0.1:8787` 后调用。不安装 Grok Build CLI（阶段 B 另案）。不改动已有 hysteria2 / hy.achimigo.top。

**Tech Stack:** Debian 13 on BLR、Python 3.13 venv、systemd、OpenSSH 隧道、现有 `main` 上 grokgw（FastAPI + ProxyRunner + auth refresh）。

**Confirmed decisions (user):**
- D1 = 阶段 A only（proxy 聊天 API，非 CLI）
- D2 = SSH 隧道（不公网裸奔 8787）
- 无 SOCKS / 无 `ALL_PROXY=2080`
- 目标机：BLR `139.84.151.149`；**不要**动已删除的 LAX

**Out of scope:**
- `GROKGW_BACKEND=cli` / 安装 `grok` 二进制 / media 生图验收
- 修改 `install.sh` 默认行为（本计划用独立 remote unit + env，避免踩 cli+2080）
- 公网 TLS 反代、域名给 grokgw
- 升配内存、阶段 B

---

## File map (create / modify)

| Path | Responsibility |
|------|----------------|
| `grokgw/deploy/remote-proxy.env.example` | **Create.** 远程 proxy 无代理环境变量模板 |
| `grokgw/deploy/grokgw-proxy.service` | **Create.** systemd unit 模板（EnvironmentFile） |
| `grokgw/deploy/README-remote-proxy.md` | **Create.** BLR 部署与隧道用法（中文短文） |
| BLR `/opt/grokgw/` | **Remote.** git clone 或 rsync 源码 |
| BLR `/opt/grokgw/.venv/` | **Remote.** Python venv |
| BLR `/etc/grokgw/proxy.env` | **Remote.** 真实 env（含 API key，chmod 600） |
| BLR `/etc/systemd/system/grokgw-proxy.service` | **Remote.** 安装后的 unit |
| BLR `/root/.grok/auth.json` | **Remote.** SuperGrok 认证（chmod 600，可写以便 refresh） |

**Do not modify for this plan:** `install.sh`（默认错误）、hysteria / proxy-stack、LAX。

---

## Ground truth（实施前必读）

| 项 | 值 |
|----|-----|
| BLR IP | `139.84.151.149` |
| SSH | `ssh -i ~/.ssh/id_ed25519 root@139.84.151.149` |
| 本机 auth | `/home/zakza/.grok/auth.json`（存在，mode 600） |
| BLR 资源 | 1 vCPU / ~1GB RAM / swap ~2.3G；已有 Docker + hysteria2 |
| 出网 | 已测 `https://api.x.ai` 可达（无需 2080） |
| Python on BLR | 3.13.5（满足 `>=3.12`） |
| 仓库 | `https://github.com/devwork2454/grokgw.git`，分支 `main` |
| 包路径 |  monorepo 内为 `grokgw/` 子目录；clone 后 `pip install -e ./grokgw` 或 cd 到含 `pyproject.toml` 的目录 |
| 端口 | grokgw `8787` 仅 `127.0.0.1`；443 留给 hy2 |

**Repo layout note:** 公开 repo 根下是 `grokgw/pyproject.toml` + `grokgw/grokgw/`。Clone 后：

```text
/opt/grokgw/                 # clone root (repo root)
  grokgw/
    pyproject.toml
    grokgw/
    deploy/                  # 本计划新增
```

Editable install：`cd /opt/grokgw && python3 -m venv .venv && .venv/bin/pip install -e ./grokgw`

---

### Task 1: 仓库内增加 remote proxy 部署模板

**Files:**
- Create: `grokgw/deploy/remote-proxy.env.example`
- Create: `grokgw/deploy/grokgw-proxy.service`
- Create: `grokgw/deploy/README-remote-proxy.md`

- [ ] **Step 1: 写 `remote-proxy.env.example`**

```bash
# /etc/grokgw/proxy.env 的模板 — 复制后改 API_KEY，chmod 600
GROKGW_BACKEND=proxy
GROKGW_PROXY_MODE=never
GROKGW_PROXY_URL=
GROKGW_HOST=127.0.0.1
GROKGW_PORT=8787
GROKGW_AUTH_PATH=/root/.grok/auth.json
GROKGW_UPSTREAM_BASE=https://api.x.ai/v1
GROKGW_MAX_CONCURRENT=2
GROKGW_TIMEOUT=120
GROKGW_MEDIA=false
# 必填：openssl rand -hex 24
GROKGW_API_KEY=CHANGE_ME
```

- [ ] **Step 2: 写 `grokgw-proxy.service`**

```ini
[Unit]
Description=grokgw OpenAI-compatible gateway (proxy backend, no SOCKS)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/grokgw
EnvironmentFile=/etc/grokgw/proxy.env
ExecStart=/opt/grokgw/.venv/bin/python -m grokgw
Restart=on-failure
RestartSec=5
# 给 token refresh 写 auth.json
ReadWritePaths=/root/.grok

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: 写 `README-remote-proxy.md`（中文，短）**

内容必须包含：
1. 拷贝 auth → `/root/.grok/auth.json`
2. clone + venv + `pip install -e ./grokgw`
3. 安装 env + unit + `systemctl enable --now grokgw-proxy`
4. 本机隧道：`ssh -N -L 8787:127.0.0.1:8787 root@139.84.151.149`
5. 验收 curl 示例（healthz + chat + Bearer）
6. **明确禁止** 远程使用根目录 `install.sh` 默认（cli + 2080）
7. 阶段 B（CLI）不在本文范围

- [ ] **Step 4: 本地提交（可选但推荐，便于 BLR pull）**

```bash
cd /home/zakza/project/research/xpage
git add grokgw/deploy/
git commit -m "$(cat <<'EOF'
docs(grokgw): add remote proxy deploy templates for VPS

Env example and systemd unit for SOCKS-free proxy backend
bound to localhost, intended for SSH tunnel access.
EOF
)"
git push origin main
```

若暂不 push：Task 2 用 `rsync` 同步本地 `grokgw/` 到 BLR。

---

### Task 2: BLR 上放置源码与 venv

**Host:** `root@139.84.151.149`  
**From:** 操作员本机 `/home/zakza`

- [ ] **Step 1: SSH 连通性**

```bash
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519 root@139.84.151.149 'uname -a; free -h | head -2'
```

Expected: Linux vultr …；Mem total ~961Mi。

- [ ] **Step 2: 安装系统依赖**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 '
  set -euo pipefail
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates
  python3 --version
'
```

Expected: Python 3.12+（当前 3.13.x OK）。

- [ ] **Step 3: 获取源码（二选一）**

**3a — 已 push main（优先）:**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 '
  set -euo pipefail
  if [[ -d /opt/grokgw/.git ]]; then
    cd /opt/grokgw && git fetch origin && git checkout main && git pull --ff-only origin main
  else
    git clone --depth 1 -b main https://github.com/devwork2454/grokgw.git /opt/grokgw
  fi
  ls /opt/grokgw/grokgw/pyproject.toml
'
```

**3b — 未 push：rsync 本地 monorepo 的 grokgw 包**

```bash
# 本机 monorepo: xpage/grokgw → 远端构造成 repo 布局
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 'mkdir -p /opt/grokgw'
rsync -az --delete \
  -e 'ssh -i ~/.ssh/id_ed25519' \
  /home/zakza/project/research/xpage/grokgw/ \
  root@139.84.151.149:/opt/grokgw/grokgw/
# 若 deploy 在 monorepo grokgw/deploy，上面已包含
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 'test -f /opt/grokgw/grokgw/pyproject.toml && echo OK'
```

- [ ] **Step 4: 创建 venv 并安装**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 '
  set -euo pipefail
  cd /opt/grokgw
  python3 -m venv .venv
  .venv/bin/pip install -U pip -q
  .venv/bin/pip install -e ./grokgw -q
  .venv/bin/python -c "import grokgw; from grokgw.proxy_runner import ProxyRunner; print(\"import_ok\", grokgw.__file__)"
'
```

Expected: `import_ok` 且路径在 `/opt/grokgw/...`。

---

### Task 3: 拷贝 auth.json（敏感）

**Files (remote):**
- Create: `/root/.grok/auth.json`

- [ ] **Step 1: 本机确认 auth 存在且非空**

```bash
test -f /home/zakza/.grok/auth.json
stat -c '%a %s' /home/zakza/.grok/auth.json
# Expected: 600 and size > 100
```

- [ ] **Step 2: scp 到 BLR（可写，供 token refresh）**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 'mkdir -p /root/.grok && chmod 700 /root/.grok'
scp -i ~/.ssh/id_ed25519 /home/zakza/.grok/auth.json root@139.84.151.149:/root/.grok/auth.json
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 'chmod 600 /root/.grok/auth.json; ls -la /root/.grok/auth.json'
```

Expected: `-rw------- 1 root root … auth.json`

- [ ] **Step 3: 不把 auth 写入 git / 计划文档 / chat 回显 token 明文**

禁止：`cat auth.json`、commit、贴到 PR。

---

### Task 4: 配置 env + systemd 并启动

**Files (remote):**
- Create: `/etc/grokgw/proxy.env`
- Create: `/etc/systemd/system/grokgw-proxy.service`

- [ ] **Step 1: 生成 API key 并写 env**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 '
  set -euo pipefail
  mkdir -p /etc/grokgw
  KEY=$(openssl rand -hex 24)
  umask 077
  cat > /etc/grokgw/proxy.env <<EOF
GROKGW_BACKEND=proxy
GROKGW_PROXY_MODE=never
GROKGW_PROXY_URL=
GROKGW_HOST=127.0.0.1
GROKGW_PORT=8787
GROKGW_AUTH_PATH=/root/.grok/auth.json
GROKGW_UPSTREAM_BASE=https://api.x.ai/v1
GROKGW_MAX_CONCURRENT=2
GROKGW_TIMEOUT=120
GROKGW_MEDIA=false
GROKGW_API_KEY=${KEY}
EOF
  chmod 600 /etc/grokgw/proxy.env
  # 把 key 单独落到仅 root 可读的提示文件，便于本机配置（可选）
  echo "$KEY" > /root/.grokgw_api_key
  chmod 600 /root/.grokgw_api_key
  echo "API_KEY written to /root/.grokgw_api_key (not printed)"
'
```

- [ ] **Step 2: 安装 unit**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 '
  set -euo pipefail
  if [[ -f /opt/grokgw/grokgw/deploy/grokgw-proxy.service ]]; then
    cp /opt/grokgw/grokgw/deploy/grokgw-proxy.service /etc/systemd/system/grokgw-proxy.service
  elif [[ -f /opt/grokgw/deploy/grokgw-proxy.service ]]; then
    cp /opt/grokgw/deploy/grokgw-proxy.service /etc/systemd/system/grokgw-proxy.service
  else
    cat > /etc/systemd/system/grokgw-proxy.service << "UNIT"
[Unit]
Description=grokgw OpenAI-compatible gateway (proxy backend, no SOCKS)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/grokgw
EnvironmentFile=/etc/grokgw/proxy.env
ExecStart=/opt/grokgw/.venv/bin/python -m grokgw
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
  fi
  systemctl daemon-reload
  systemctl enable --now grokgw-proxy.service
  systemctl --no-pager --full status grokgw-proxy.service | head -25
'
```

Expected: `Active: active (running)`。

- [ ] **Step 3: 确认监听与防火墙**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 '
  ss -tlnp | grep 8787 || true
  # 必须是 127.0.0.1:8787，不能是 0.0.0.0:8787
  ss -tlnp | grep 8787 | grep -q 127.0.0.1 && echo BIND_OK || echo BIND_BAD
  # 不要 ufw allow 8787
  ufw status | grep -i 8787 || echo "8787 not in ufw (good)"
'
```

Expected: `BIND_OK`；ufw 无 8787。

- [ ] **Step 4: 服务端本机 healthz**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 '
  curl -sS http://127.0.0.1:8787/healthz | python3 -m json.tool
'
```

Expected JSON 含：
- `"status": "ok"`（或等价成功字段）
- `"backend": "proxy"`
- **无** 强制要求 socks；proxy_mode 应为 `never`（若 healthz 暴露该字段）

---

### Task 5: 服务端 chat 冒烟（无隧道）

- [ ] **Step 1: 用服务端 API key 调 chat**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 '
  set -euo pipefail
  KEY=$(cat /root/.grokgw_api_key)
  curl -sS http://127.0.0.1:8787/v1/chat/completions \
    -H "Authorization: Bearer ${KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"grok-4.5\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: pong\"}]}" \
    | python3 -m json.tool | head -40
'
```

Expected:
- HTTP 逻辑成功（choices[0].message.content 含文本）
- 非 401/502/504
- 若 auth 过期：明确 authentication 错误 → 回 Task 3 更新 auth

- [ ] **Step 2: 负例 — 无 key 应 401**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 '
  code=$(curl -sS -o /tmp/gw_body -w "%{http_code}" http://127.0.0.1:8787/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"grok-4.5\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}")
  echo "http=$code"
  test "$code" = "401" && echo AUTH_OK || echo AUTH_UNEXPECTED
'
```

Expected: `http=401` / `AUTH_OK`。

---

### Task 6: 本机 SSH 隧道端到端验收

**From:** `/home/zakza` 工作站

- [ ] **Step 1: 拉取 API key 到本机内存/本地仅用户可读文件（勿提交）**

```bash
scp -i ~/.ssh/id_ed25519 root@139.84.151.149:/root/.grokgw_api_key /tmp/grokgw_blr_api_key
chmod 600 /tmp/grokgw_blr_api_key
```

- [ ] **Step 2: 开隧道（后台）**

```bash
# 若 8787 已被本地占用，改用 -L 18787:127.0.0.1:8787
ssh -f -N -o ExitOnForwardFailure=yes -i ~/.ssh/id_ed25519 \
  -L 8787:127.0.0.1:8787 root@139.84.151.149
sleep 1
curl -sS http://127.0.0.1:8787/healthz | python3 -m json.tool | head -20
```

Expected: 与 BLR 上 healthz 一致。

- [ ] **Step 3: 经隧道 chat**

```bash
KEY=$(cat /tmp/grokgw_blr_api_key)
curl -sS http://127.0.0.1:8787/v1/chat/completions \
  -H "Authorization: Bearer ${KEY}" \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Say hi in one word"}]}' \
  | python3 -m json.tool | head -40
```

Expected: 正常 completion。

- [ ] **Step 4: 确认本机未走 2080 才能用（可选）**

```bash
# 健康检查不依赖 ALL_PROXY；chat 在 BLR 侧完成上游访问
# 本机可 unset ALL_PROXY 再 curl 隧道端口，应仍成功
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \
  curl -sS http://127.0.0.1:8787/healthz | head -c 200; echo
```

- [ ] **Step 5: 记录使用方式（本机笔记，非 git）**

```text
ssh -N -L 8787:127.0.0.1:8787 -i ~/.ssh/id_ed25519 root@139.84.151.149
OPENAI_BASE_URL=http://127.0.0.1:8787/v1
OPENAI_API_KEY=<contents of /tmp/grokgw_blr_api_key>
```

---

### Task 7: 运维与回归清单（收尾）

- [ ] **Step 1: 开机自启确认**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 '
  systemctl is-enabled grokgw-proxy.service
  systemctl is-active grokgw-proxy.service
'
```

Expected: `enabled` + `active`。

- [ ] **Step 2: 与 hy2 共存确认**

```bash
ssh -i ~/.ssh/id_ed25519 root@139.84.151.149 '
  docker ps --format "{{.Names}} {{.Status}}" | grep hysteria2
  systemctl is-active grokgw-proxy
'
```

Expected: hysteria2 healthy/up；grokgw-proxy active。

- [ ] **Step 3: 写失败 runbook（进 README-remote-proxy.md 一小节即可）**

| 症状 | 处理 |
|------|------|
| chat 401 from grokgw API key | 检查 Bearer 与 `/etc/grokgw/proxy.env` |
| chat 401 / auth expired from upstream | 本机 `grok login` 后重 scp `auth.json` |
| 502/upstream | BLR `curl -I https://api.x.ai`；检查 `PROXY_MODE=never` |
| 8787 连不上 | `systemctl status grokgw-proxy`；隧道是否建立 |
| OOM | 降 `MAX_CONCURRENT`；阶段 A 一般足够 |

- [ ] **Step 4: 最终验收表（全部勾选才算完成）**

| ID | 检查 | 通过 |
|----|------|------|
| V1 | `backend=proxy`，`PROXY_MODE=never`，无 2080 依赖 | [ ] |
| V2 | 仅监听 `127.0.0.1:8787` | [ ] |
| V3 | 无 key → 401；有 key → chat 成功 | [ ] |
| V4 | 本机 SSH 隧道 healthz + chat 成功 | [ ] |
| V5 | hy2 仍 running | [ ] |
| V6 | auth 权限 600；env 600 | [ ] |

---

## Self-review checklist

| 需求 | Task |
|------|------|
| BLR 部署 | 2–4 |
| 不用代理 | 1 env + 4 `PROXY_MODE=never` + `PROXY_URL=` |
| 提供 API 服务 | 4–6 chat completions |
| SSH 隧道访问 | 6 |
| 不用 install.sh 错误默认 | 全文禁止 + README |
| 不动 hy2 / 不做 CLI | Out of scope + V5 |
| 敏感信息不入库 | Task 3 Step 3 |

**Placeholder scan:** 无 TBD；命令可复制。

**风险已写明:** 1GB 仅跑 proxy；auth 7 天过期需重拷；不公网暴露 8787。

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-17-grokgw-blr-proxy-deploy.md`.

**推荐执行方式**

1. **Inline Execution（推荐本场景）** — 运维步骤多在 SSH 上，本会话按 Task 1→7 顺序执行，每 Task 验收后再下一步。  
2. **Subagent-Driven** — 适合 Task 1 仓库改动与 Task 2–6 运维拆开时；运维 Task 需本机 SSH/key 与 `auth.json` 可达。

**开始执行前确认：**
- 允许 scp 本机 `~/.grok/auth.json` → BLR `/root/.grok/auth.json`
- 允许在 BLR 安装 systemd 服务 `grokgw-proxy`
- 是否现在 `git push` deploy 模板到 `main`（可否：可用 rsync 代替）

**Which approach?** 回复 `inline` 或 `subagent` 即可开工。
