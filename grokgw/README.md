# grokgw

OpenAI 兼容本地 API 网关，把 SuperGrok 订阅封装成 `/v1/chat/completions` 服务。

- **双后端**：proxy（直连 api.x.ai，~1.5s）| cli（Grok Build headless，~6s，有隐私沙箱）
- **零配置**：读 `~/.grok/auth.json`，OAuth token 自动刷新
- **一键部署**：install.sh → systemd 自启

## 快速开始

```bash
# clone + 安装
git clone https://github.com/devwork2454/grokgw.git
cd grokgw/grokgw && ./install.sh

# 启动（systemd 已自动启用）
systemctl --user status grokgw

# 测试
curl http://127.0.0.1:8787/healthz
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Hello"}]}'
```

### 前提

- 本机 `grok login` 已完成（`~/.grok/auth.json` 存在）
- Python 3.12+ / Docker
- socks5 代理在 `127.0.0.1:2080` 或设 `GROKGW_PROXY_URL`（本机 IPv6 异常时必需）

### Docker

```bash
cd grokgw
docker compose up -d
# 挂载 ~/.grok/auth.json，绑定 127.0.0.1:8787，健康检查 30s 间隔
```

## 架构

```
请求 → FastAPI(端口 8787) → 后端路由
                                ├─ proxy(默认): curl → api.x.ai/v1 (OAuth token)
                                └─ cli(fallback): grok -p → NDJSON → OpenAI
```

| 后端 | `GROKGW_BACKEND` | 延迟 | 适用场景 |
|------|-------------------|------|----------|
| proxy | `proxy` | ~1.5s | 日常使用（默认） |
| cli | `cli` | ~6s | 需要隐私沙箱（隔离空目录，规避仓库上传） |

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/chat/completions` | POST | 流式 + 非流式，OpenAI 兼容 |
| `/v1/models` | GET | 模型列表 |
| `/healthz` | GET | 健康检查 |

### OpenAI SDK

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="dummy")
resp = client.chat.completions.create(
    model="grok-4.5",
    messages=[{"role": "user", "content": "Hello"}],
)
```

### 流式

```bash
curl -N http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

### OpenCode 集成

```bash
charon add opencode --name grokgw --key dummy \
  --endpoint http://127.0.0.1:8787/v1 --model grok-4.5
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `GROKGW_BACKEND` | `proxy` | 后端：`proxy` / `cli` |
| `GROKGW_UPSTREAM_BASE` | `https://api.x.ai/v1` | 上游地址 |
| `GROKGW_AUTH_PATH` | `~/.grok/auth.json` | 认证文件 |
| `GROKGW_HOST` | `127.0.0.1` | 监听地址 |
| `GROKGW_PORT` | `8787` | 监听端口 |
| `GROKGW_PROXY_URL` | `socks5h://127.0.0.1:2080` | 上游代理；设空禁用 |
| `GROKGW_PROXY_MODE` | `auto` | `auto`:直连优先→代理回退 `always`:始终代理 `never`:禁用代理 |
| `GROKGW_API_KEY` | 无 | 客户端 Bearer 认证 |
| `GROKGW_MAX_CONCURRENT` | `3` | 最大并发 |
| `GROKGW_TIMEOUT` | `120` | 请求超时(秒) |
| `GROKGW_GROK_BIN` | `grok` | CLI 后端 grok 路径 |
| `GROKGW_EXPOSE_REASONING` | `false` | 透传 reasoning_content |

## 测试

```bash
source antibot/.venv/bin/activate   # 或自建 venv
pip install -e ./grokgw
pip install pytest pytest-asyncio
python -m pytest grokgw/tests/ -v   # 55 单测
```

## 局限

- **不支持 function calling**（CLI headless 固有局限；proxy 后端理论上支持但未实现）
- CLI 后端每请求 spawn `grok` 进程，cold start 2–5s，适合低并发
- SuperGrok token 7 天过期，需 `grok login` 刷新
- 非流式响应 usage 来自上游透传（212 prompt tokens），CLI 后端 ~12K agent prompt
- proxy 后端依赖本机 socks5 代理稳定性

## 文档

- 设计规格：`docs/superpowers/specs/2026-07-15-grok-api-gateway-design.md`
- 实现计划：`docs/superpowers/plans/2026-07-15-grok-api-gateway.md`

## 开源对比

与同类项目（grok2api / grokcli2api-go / sub2api / progrok）对比，grokgw 定位**最轻量单机方案**：

- 不依赖 PostgreSQL / Redis / Docker（直接跑也行）
- 不驱动浏览器 / 不逆向 Web 端
- SuperGrok 403 风险为零（CLI 路径不碰 api.x.ai）
- 唯一带沙箱隔离的项目（规避 Grok Build 仓库上传隐私风险）
