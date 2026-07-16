# grokgw

OpenAI 兼容本地 API 网关,封装 Grok Build CLI(`grok -p`),复用 SuperGrok 订阅认证。

## 前提

- `grok` CLI 已安装(`~/.grok/bin/grok`)且已登录(`~/.grok/auth.json` 存在)
- Python 3.12+

## 安装

```bash
source antibot/.venv/bin/activate   # 或自建 venv
pip install -e ./grokgw
pip install pytest pytest-asyncio httpx   # dev
```

## 运行

```bash
python -m grokgw
# 默认监听 127.0.0.1:8787
```

## 使用

```bash
# 非流式
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Hello"}]}'

# 流式
curl -N http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

OpenAI SDK:
```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="dummy")
resp = client.chat.completions.create(
    model="grok-4.5",
    messages=[{"role": "user", "content": "Hello"}],
)
print(resp.choices[0].message.content)
```

## 配置(环境变量)

| 变量 | 默认 | 说明 |
|------|------|------|
| `GROKGW_PORT` | 8787 | 监听端口 |
| `GROKGW_HOST` | 127.0.0.1 | 监听地址 |
| `GROKGW_MAX_CONCURRENT` | 3 | 最大并发请求数 |
| `GROKGW_API_KEY` | (无) | 可选,设置后要求客户端 Bearer 认证 |
| `GROKGW_GROK_BIN` | grok | grok 二进制路径 |
| `GROKGW_TIMEOUT` | 120 | 单请求超时(秒) |
| `GROKGW_EXPOSE_REASONING` | false | 是否透传 thought 事件为 reasoning_content |

## 测试

```bash
cd /home/zakza/project/research/xpage
source antibot/.venv/bin/activate
python -m pytest grokgw/tests/ -v
```

## 局限

- **不支持 function calling**(Grok Build headless 的 `--tools` 是内置工具,不接 OpenAI function schema)
- 非流式响应 `usage` 为 null(grok json 输出不含 token 计数)
- 每请求 spawn grok 进程,cold start ~2-5s,适合低并发自用
- SuperGrok token 7 天过期需 `grok login` 刷新

## 设计文档

`docs/superpowers/specs/2026-07-15-grok-api-gateway-design.md`
