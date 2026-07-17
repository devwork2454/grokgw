# Grok 会话纪要：xpage 方向演进与待办

> **来源**：`0715.txt`(2026-07-15 Grok CLI 会话,36 轮,~16 万字)。
> **作用**：把那段会话的结论固化为可查文档,后续不必重读原始记录即可接续。
> **性质**:research note,非产品 spec;结论反映会话当时状态,代码现状以仓库为准。

---

## 1. 项目定位演进

| 阶段 | 定位 |
|------|------|
| 早期 | `xpage` = DrissionPage 研究 + antibot 检测/加固/监测实验(检测站收口) |
| **转向(本次会话核心)** | 自有/授权环境下的**单机可运营浏览器运行时**:独立 profile + 会话持久化 + 多账号 + 多代理 + 定时任务 + 基础风控 |
| 边界 | headless-only(无显示机) |

---

## 2. 已完成(会话产出)

### 2.1 设计与计划
- 设计规格:`docs/superpowers/specs/2026-07-15-browser-ops-runtime-design.md`(定位/边界/分期/数据模型/Runtime/风控/错误矩阵/CLI/验收 V1–V8,分段批准)
- 实现计划:`docs/superpowers/plans/2026-07-15-browser-ops-runtime-p0.md`(12 Task,TDD)
- 调研文档:`docs/research/2026-07-15-apple-account-email-provider-matrix.md`(邮箱选型矩阵 + 印度区人工实测协议 §6.4–6.5 + 明确拒绝 Apple 自动开号 §7)

### 2.2 代码 `runtime/`(13 模块 + 3 内置任务 + 6 测试)
Store / Risk / BrowserRuntime / Session(含 ProfileLock) / Runner / Scheduler / CLI + tasks(healthcheck · login_probe · local_storage_mark)

### 2.3 验收 P0
- 单元测试 **14/14 PASS**
- 集成 V1–V8:V1/V2/V3/V5/V6/V7/V8 **PASS**;**V4 PARTIAL**(本机仅一条真实出口代理)
- 机器结果:`runtime/tests/acceptance_run.json`

### 2.4 实现中修的两个坑(供未来参考)
1. **仓库根 `DrissionPage/` 遮蔽 venv 安装** → `browser._import_chromium()` 清理 `sys.path`
2. **端口复用假阳性** → 去掉 `SO_REUSEADDR` 探测 + pkill 后等待 + 失败打 stderr

### 2.5 Git
- 已 `git init -b main`,提交至 `b0b5a54`(3 个 commit:initial / P0 验收 / hardened 产物)
- DrissionPage 去嵌套 `.git` 并入本仓(上游 `6957a28`,见 `DrissionPage/UPSTREAM.md`)
- 全局 git 身份 `migoachi <migoachi@gmail.com>` 已配,代理已配
- **无远程**(gh 已装但未 `gh auth login`)

---

## 3. 下一步待办(按性价比排序)

| # | 任务 | 状态 | 说明 |
|---|------|------|------|
| 1 | **`mail` P0 合规邮箱开箱** | 设计 §1 已认可,代码未写 | 见下 backlog;这是最可能的开发起点 |
| 2 | 提交 `docs/research/` | 未提交(untracked) | 一句 `git add docs/research && git commit` |
| 3 | git 远程私有仓库 | 未做 | 需 `gh auth login` 后 `gh repo create xpage --private --source=. --remote=origin --push` |
| 4 | V4 双代理验收 | PARTIAL(环境) | 需第二条真实代理才能补;非阻塞 |
| 5 | P1:自动重登钩子 / 告警 / 任务 DSL / session 探活 | 未开始 | 规格里明确延后 |

### 3.1 `mail` P0 backlog(合规版,会话末尾敲定)
> 一句话:**自动开(自有)邮箱 + 人工完成 Apple 验证 + 自动记账结果**。拆掉违规环节,保留调研目标。

| Story | 内容 |
|-------|------|
| **MAIL-001** | `MailboxProvider` 抽象 + `mock` Provider + CLI(`mail create/list/doctor`)+ `mailboxes` 表 + 审计 + 可选 `--link-account` |
| **MAIL-002** | 接 Mailcow 或 Google Workspace(用户指定后端与凭据) |
| **MAIL-003** | `probe-result` 录入 / 列表 / 导出 Markdown |

- 默认实现:**HTTP 通用适配器 + Mailcow 优先文档**,或 Workspace Admin SDK
- 无真邮局时:MVP 带 `mock` Provider,本地跑通 CLI/表结构
- 合规边界:只做邮箱侧 API 开箱 + 域名 MX/SPF 投递预检 + 结果人工录入

---

## 4. 关键结论(会话中被反复强调)

1. **Apple 不按邮箱类型白名单限制**——只要能收验证信、地址未占用、能长期访问即可;Gmail/Outlook/自有域名同属一类
2. **自建/自有域名邮箱政策上可用于 Apple 主邮箱**(场景 A,非 iCloud+ Custom Email Domain);成败看投递(SPF/DKIM/DMARC/PTR/信誉)与域名状态(未被 ABM Domain Lock)
3. **"免手机邮箱" ≠ "Apple 创建免手机"**——Apple Web/多数创建路径仍普遍要可访问手机号(中国大陆常见 +86);邮箱选型消不掉 Apple 手机门槛
4. **headless ≠ 过 Cloudflare**——stealth_min 只覆盖浅层指纹;nowsecure 仍撞 Turnstile
5. **全自动账密登 Google/Apple 不当主路径**——偶发人在环登录 + 高度自动化的会话复用与失效处理(`need_relogin`)才是设计方向

---

## 5. 安全策略

- 密钥/Cookie/代理密码落盘加密或 `0600`;审计可追溯

---

## 6. 接续工作的入口

要继续,直接从这几条任选其一(对应会话末尾留给用户的选项):

- `实现 MAIL-001 mock` — 开工 mail P0
- `commit 调研文档` — 只提交 docs/research
- `先写 mail 设计全文再开发` — 先补 spec 再编码

会话原文:`0715.txt`(根目录,untracked)。
