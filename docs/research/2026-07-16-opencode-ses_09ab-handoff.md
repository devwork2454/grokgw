# OpenCode → Grok Handoff

**Session:** `ses_09abad312ffebuMB2vG3Oj143X`  
**导出:** `session-ses_09ab.md`（全文很长，不必重读）  
**工作区:** `/home/zakza/project/research/xpage`  
**远程:** `https://github.com/devwork2454/grokgw`（public；整仓推的，不只是 `grokgw/` 子包）  
**中断时间:** 2026-07-16 下午；用户在等 **push + 冒烟**，agent 卡住 / 无输出

---

## 一句话现状

`grokgw` Media **Phase 1 代码和单测已做完**（分支 `feat/grokgw-media-phase1`，本地 80 tests pass），**推远程 + 完整生图冒烟没做完**。用户最后指令是「先完成推送,冒烟」，随后追问「为什么这么久?」——会话在这里断了。

---

## 项目是啥

`grokgw` = 本地 OpenAI 兼容网关，复用 SuperGrok 订阅。

| 后端 | env | 延迟 | 说明 |
|------|-----|------|------|
| **proxy**（默认） | `GROKGW_BACKEND=proxy` | ~1.5s | curl → `api.x.ai` |
| **cli** | `GROKGW_BACKEND=cli` | ~6s+ | `grok -p` headless；有 sandbox |

入口：`source antibot/.venv/bin/activate && python -m grokgw`  
本机 IPv6 坏的，**必须** socks5 `127.0.0.1:2080`（`ss -tlnp | grep 2080`）。  
详细环境坑见 `AGENTS.md`。

---

## 这次会话干了啥（按时间，粗）

1. **开源/部署：** `gh auth login`（devwork2454）、建 public repo、推 main、`install.sh` 一键装、README 重写  
2. **proxy 智能探测：** `GROKGW_PROXY_MODE=auto|always|never`（直连失败再代理）  
3. **CLI 能力：** 恢复 full tools（含 web_search）；`GROKGW_CWD` 可访问真实目录  
4. **调研 image/video：** 纠正错误前提——图不在 sandbox cwd，在  
   `~/.grok/sessions/<urlencode(cwd)>/<sessionId>/images/N.jpg`  
5. **方案：Hybrid**  
   - Phase 1：session harvest + serve + non-stream rewrite（**已实现**）  
   - Phase 2：stream rewrite  
   - Phase 3：`POST /v1/images/generations` 直连 Imagine  
   - Phase 4：video  
6. **Phase 1 按计划 TDD 落地**（subagent 任务链）

---

## Media Phase 1 — 已完成（代码）

**分支:** `feat/grokgw-media-phase1`（**未确认是否已 push / 是否 merge 进 main** —— 接手前用 git 核一次）

| Task | Commit | 内容 |
|------|--------|------|
| 1 | `c5dc386` | `grokgw/grokgw/media.py` + `tests/test_media.py` |
| 2 | `694b4c3` | Settings: `media_enabled` / `sessions_root` / `public_base`；media 开且未设 timeout → 300 |
| 3 | `3bd5f60` | `GrokRunner.complete` 改写 text 中 `images\|videos/N.ext` |
| 4 | `c31e705` | `GET /v1/media/sessions/{sid}/{kind}/{file}`；healthz 带 media 字段 |
| 5 | `82db457` | README；**80 passed** |

计划文档（checkbox 可能还是空的，别信 checkbox）：  
`docs/superpowers/plans/2026-07-16-grokgw-media-phase1.md`

### 关键 API / 行为

- **Serve:** `GET /v1/media/sessions/{session_id}/images|videos/{filename}`  
  - 文件名白名单：`^\d+\.(jpg|jpeg|png|webp|mp4)$`  
  - **不在** auth 白名单 → 与 chat 同鉴权  
- **Rewrite（仅 CLI non-stream `complete`）:**  
  `images/1.jpg` → `http://127.0.0.1:8787/v1/media/sessions/<sid>/images/1.jpg`  
- **Env:** `GROKGW_MEDIA`（默认 on）、`GROKGW_SESSIONS_ROOT`、`GROKGW_PUBLIC_BASE`  
- 图片持久在 `~/.grok/sessions`；`cleanup_sandbox()` **不会**删图

### 已知边界（刻意未做）

- ❌ stream 路径不 rewrite（Phase 2）  
- ❌ proxy 后端不走 rewrite（逻辑只在 `GrokRunner.complete`）  
- ❌ 无 `POST /v1/images/generations`（Phase 3）  
- ❌ 完整「画猫」端到端生图冒烟未跑（只对**已有** session 图做了 GET 200）

---

## 用户最后一条有效指令（未完成）

> 先完成推送,冒烟

期望动作（原会话未交付）：

1. **push** `feat/grokgw-media-phase1` → origin（可选开 PR 合并 main）  
2. **冒烟** 真机 CLI 生图：
   ```bash
   source antibot/.venv/bin/activate
   ss -tlnp | grep 2080   # 代理必须在
   # 若端口占用先杀掉旧 grokgw
   GROKGW_BACKEND=cli GROKGW_MEDIA=1 python -m grokgw
   # 另开终端，非流式，timeout 拉长
   curl -s --max-time 360 http://127.0.0.1:8787/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"grok-4.5","messages":[{"role":"user","content":"画一只猫，只要一张图"}]}'
   # 期望 content 含 http://127.0.0.1:8787/v1/media/sessions/.../images/1.jpg
   # 再 curl 该 URL → image/jpeg 200
   ```
3. 汇报：push URL / PR、冒烟 content 片段、media GET 状态码

**为什么慢：** 生图要走 grok CLI agent + Imagine，常 **1–5 分钟**；`GROKGW_TIMEOUT` 默认 media 时 300s。OpenCode 那次 500s+ 无输出，多半卡在 spawn/代理/超时，**结果没写回会话**。

---

## 接手前 30 秒检查清单

```bash
cd /home/zakza/project/research/xpage
git status -sb
git branch -vv
git log --oneline -8
# 是否已 push：
git ls-remote --heads origin 'feat/grokgw-media-phase1' 'main'
source antibot/.venv/bin/activate
python -m pytest grokgw/tests/ -q   # 期望 80 passed
ss -tlnp | grep 2080
```

若分支已推且 main 已含 media：只补冒烟。  
若未推：先 push，再冒烟。  
**不要**重做 Phase 1 实现。

---

## 刻意不要做的事

- 不要重写 media.py / 重跑 TDD 任务链  
- 不要默认开 Phase 2/3（用户先要 push+冒烟）  
- 不要 `rmtree` 任何 `data/profiles/*`（那是 runtime 运营数据，另一条线）  
- 不要假设 headless Chrome / 有显示（本机无显示；grokgw 不依赖 Chrome）  
- Docker pull 在本机经常挂（IPv6），本地 venv 跑即可  

---

## 其它仓状态（背景，非当前阻塞）

| 组件 | 状态 |
|------|------|
| `runtime/` Browser Ops P0 | 已验收 V1–V8（V4 双代理 PARTIAL）；下一步曾是 mail P0，**不是本会话焦点** |
| `antibot/` | 指纹 lab，稳定；与 grokgw 无关 |
| `DrissionPage/` | 本地 5.0.0b0 editable |
| gh | 已登录 `devwork2454`，token 持久 `~/.config/gh` |
| git identity | `devwork2454` / `dev.work2454@gmail.com`（会话中设过） |

---

## 相关文件

| 路径 | 用途 |
|------|------|
| `grokgw/grokgw/media.py` | find / resolve / rewrite |
| `grokgw/grokgw/config.py` | media settings + timeout 300 |
| `grokgw/grokgw/grok_runner.py` | complete 内 rewrite |
| `grokgw/grokgw/server.py` | media GET + healthz |
| `grokgw/README.md` | 已写 media 用法 |
| `docs/superpowers/plans/2026-07-16-grokgw-media-phase1.md` | 实施计划 |
| `session-ses_09ab.md` | OpenCode 全文导出（备用） |
| `AGENTS.md` | 仓级约定 |

---

## 建议 Grok 第一动作

1. 核对 git：分支 / 是否已 push / 与 main 差多少  
2. 若未 push：`git push -u origin feat/grokgw-media-phase1`（必要时 `gh pr create`）  
3. 跑完整生图冒烟，贴结果  
4. 停下来等用户：merge？还是 Phase 2？
