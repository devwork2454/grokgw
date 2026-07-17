# xpage 规划 + 目录只读审计

- **Date:** 2026-07-17
- **Mode:** 只读（本报告不改业务代码、不挪目录）
- **方法:** Architect（模块边界/目录）+ PM（规划状态/优先级）双视角合并
- **仓库:** `/home/zakza/project/research/xpage`
- **远程:** `origin` → `https://github.com/devwork2454/grokgw.git`（见问题 P0-1）

---

## 0. 先给你一张「专业眼镜」

你说自己「只知道要什么，缺少流程」。下面这套流程就是本次审计实际用的，以后同类问题可复用：

| 步骤 | 问什么 | 本次证据来源 |
|------|--------|--------------|
| 1. 画现状地图 | 磁盘上实际有什么？各干什么？ | 顶层目录、`git ls-files`、包入口 |
| 2. 读规划声明 | 文档说仓库是什么、做到哪？ | `AGENTS.md`、specs、plans |
| 3. 对齐差距 | 声明 vs 现实差在哪？ | Status 字段、checkbox、未跟踪文件、缺失包 |
| 4. 评依赖与边界 | 谁依赖谁？能否独立演进？ | import、paths、remote |
| 5. 分级问题 | P0 伤效率/安全/发布；P1 混乱；P2 洁癖 | 见第 4 节 |
| 6. 建议动作 | 改目录 / 只改文档 / 不动 | 见第 5 节 |
| 7. 你只需拍板 | 偏好与资源，不代替专业判断细节 | 见第 6 节 |

**原则：** 研究 monorepo 允许「多产品共仓」，但必须有 **入口索引 + 状态真相 + 清晰边界**。  
多数「目录不对」的第一刀应是 **更新文档与状态**，不是立刻 `mv`。

---

## 1. 现状地图（磁盘真相）

### 1.1 顶层职责（一句话）

| 路径 | 实际职责 | 生命周期 | 与规划关系 |
|------|----------|----------|------------|
| `DrissionPage/` | 上游库 5.0.0b0 本地 vendoring（beta，非 PyPI） | 依赖 | AGENTS 核心；git 内跟踪约 90 文件 |
| `antibot/` | 反检测 **实验床**（脚本 + 报告 + 少量测试） | 研究 lab | 最早两条根之一；含遗留 `run_*` 脚本 |
| `runtime/` | **浏览器运营运行时**（CLI、profile、调度、风控、identity） | 产品 P0+ | 有 design + plan；代码已大幅落地 |
| `grokgw/` | **Grok API 网关**（可独立发布的子项目形态） | 产品 M0–媒体/部署 | 设计/计划/实现/部署最完整 |
| `data/` | 运行时数据（sqlite、profiles、secrets、logs） | 本地运行时 | **gitignore**；约 202MB（几乎全是 profiles） |
| `docs/superpowers/` | 设计规格 + 实施计划 | 规划真相源（应是） | specs×3、plans×4 |
| `docs/research/` | 调研/会话复盘/handoff | 研究笔记 | **多数未入库** |
| `AGENTS.md` | Agent/人的操作手册 | 元文档 | 内容丰富但 **开篇模型过时** |
| `session-ses_09ab.md` | 会话 dump（~251KB） | 临时 | **未跟踪**；不应进根目录长期 |
| `studio/` | XYQ 创作编排（设计已批 P0） | 规划中 | **目录不存在** |

### 1.2 依赖方向（简化）

```
                    ┌─────────────┐
                    │ DrissionPage│  (vendored lib)
                    └──────▲──────┘
                           │ import
              ┌────────────┼────────────┐
              │            │            │
         antibot/      runtime/     (studio 未来不应硬绑浏览器栈)
              │            │
              │  stealth_min.js 硬路径
              └────────────┘
                           │
                      data/ (仅 runtime 运营数据；studio 设计写 data/studio)

         grokgw/  ────────  几乎零依赖本仓其他包（独立产品）
```

**关键事实：**

- `runtime/paths.py` 固定 `DATA = ROOT/data`，并引用 `antibot/stealth_min.js` → **runtime 与 antibot 有意耦合**（合理，但是「研究床 + 运营」一体）。
- `grokgw` 不依赖 runtime/antibot → **物理共仓、逻辑独立**。
- 根目录 **无** `README.md`、**无** 根 `pyproject.toml` → 不是统一 Python monorepo 包，是 **工作区集合**。
- 共享 venv：`antibot/.venv` 被 AGENTS 规定为全局入口。

### 1.3 Git / 远程真相（规划常被忽略的一层）

| 事实 | 含义 |
|------|------|
| `origin` = `devwork2454/grokgw` | 整个 xpage 工作区推到 **grokgw 产品仓名** |
| 近期 commit 几乎全是 grokgw | 远程叙事 = 网关产品；本地叙事 = 研究+运营 monorepo |
| `runtime/identity/**` 大量 **未跟踪** | 本地有能力，远程/协作者看不到 |
| `docs/research/**`、`xyq-studio` spec、部分 plan **未跟踪** | 规划资产不完整入库 |
| `antibot/report/**` 截图/JSON **已跟踪** | 实验产物进库，噪音大 |
| plans 里 checkbox 几乎全是 `[ ]` | 实施进度 **文档未回写**（实现早已跑过） |

---

## 2. 规划 vs 现实

### 2.1 产品线清单（规划声明）

| 产品/线 | Spec 状态（文件头） | Plan | 代码现实 | 一致性 |
|---------|---------------------|------|----------|--------|
| Antibot lab | 主要在 AGENTS + `.claude/plans/antibot_test_plan.md` | 测试计划 | 脚本+报告在 | 中：文档散、有遗留脚本 |
| Browser Ops Runtime | **Draft for user review** | P0 plan 大量未勾 | 包齐全 + identity 扩展 | **状态滞后**（Draft 却已实现很多） |
| grokgw | Draft（早期）+ 后续媒体/部署 plan | 多份 plan | 实现+测试+deploy 齐全 | **实现超前于 Status 字段** |
| XYQ Studio Lite | **Approved for P0** | 无独立 plan 文件（spec 内含 P0） | **`studio/` 缺失** | **规划超前于代码** |
| 仓库总路线图 | **不存在** | — | 四条线并行 | **缺口** |

### 2.2 AGENTS.md 的叙事裂缝

- **开篇**仍写：研究仓、**Two roots**（`DrissionPage` + `antibot`），且「无 build/lint/test/CI」。
- **后半**已补充 `runtime`、`grokgw` 完整入口，且 grokgw/runtime 实际 **有 pytest**。
- **未写** `studio`（虽有 approved design）。
- **未写**「本仓是多产品工作区；git remote 可能指向 grokgw」。

→ 对人/对 agent 都容易产生 **错误默认世界模型**（以为还在「双根实验仓」）。

### 2.3 单品规划质量（PM 视角）

**做得好的（应保留的科学习惯）：**

- 多数 spec 有 one-liner、constraints、non-goals、分阶段、验收标准。
- plan 有 file map、out of scope、agent 注意事项 → 适合 agent 执行。
- runtime / grokgw 边界在设计层是清楚的（授权环境、非对抗绕过；网关不接 function calling 等）。

**薄弱点：**

1. **无 monorepo 级 Roadmap**：不知道「本周主线是 BLR 部署还是 studio P0 还是 runtime identity」。
2. **Status 字段不维护**：Draft / checkbox 与现实脱节 → 规划不可信。
3. **产品优先级未书面化**：四条线并行时，缺「资源约束下的唯一主线」。
4. **studio 已批准却无落地跟踪**：approved 无 plan 勾选、无目录 → 高风险悬空承诺。
5. **Git 边界与产品边界错位**：remote 名 grokgw，内容含 runtime/DrissionPage/antibot。

### 2.4 目录划分是否「正确」？

在 **research monorepo** 标准下（不是公司级 monorepo 洁癖标准）：

| 判断 | 结论 |
|------|------|
| 源码 / 依赖 / 运行时数据分离 | **正确**：`data/` gitignore + 大体积 profiles 不入库 |
| 实验 vs 运营分离 | **基本正确**：`antibot` vs `runtime`；且有硬路径复用 stealth |
| 独立产品可封装 | **grokgw 形态正确**（自有 pyproject/README/tests/deploy） |
| 上游依赖隔离 | **可接受的研究做法**；长期可 submodule，非紧急 |
| 文档结构 | **半对**：`docs/superpowers` 好；缺按产品分子目录或索引；research 未入库 |
| 根入口 | **偏弱**：无 README；AGENTS 开篇过时 |
| 实验产物 | **偏弱**：`antibot/report` 入库；根目录 session dump |

**结论：** 目录骨架 **大体合理**，不是乱仓。主要问题是 **「身份叙事」和「状态管理」跟不上多产品演化**，不是「必须立刻拆仓」。

---

## 3. 打分

| 维度 | 分 (1–5) | 一句话 |
|------|----------|--------|
| **规划合理度** | **3 / 5** | 单品设计专业；缺总路线图、状态回写、优先级 |
| **目录合理度** | **3.5 / 5** | 分层清晰、数据隔离好；入口文档与产物卫生拖分 |
| **规划↔目录一致性** | **2.5 / 5** | studio 缺位、AGENTS 双根叙事、remote=grokgw、计划 checkbox 失真 |
| **可继续演进潜力** | **4 / 5** | 边界已有雏形；补文档与状态即可明显变好 |

**综合：** 值得继续用此仓结构；**优先修「真相源」而不是大搬家。**

---

## 4. 问题分级

### P0（先处理：影响判断力 / 发布边界 / 协作）

| ID | 问题 | 证据 | 为何是 P0 |
|----|------|------|-----------|
| P0-1 | Git remote 产品名与 monorepo 内容错位 | `origin` → grokgw；仓内含 runtime/antibot/DrissionPage | 推送/协作/备份语义混乱；误以为整仓就是网关 |
| P0-2 | 无「当前主线」总览 | 无 root README / roadmap | 你自己也难回答「现在该推哪条线」 |
| P0-3 | 规划状态失真 | specs 仍 Draft；plans 0 checked；代码已存在 | Agent 会重复实现或忽略已完成工作 |
| P0-4 | studio 已 Approved 但无代码/无跟踪 | design 写 `studio/` + `data/studio`；目录不存在 | 悬空决策；与 runtime 争抢注意力 |

### P1（混乱源：降低认知负担）

| ID | 问题 | 证据 |
|----|------|------|
| P1-1 | AGENTS 开篇「Two roots / 无测试」过时 | 与后半 runtime/grokgw 矛盾 |
| P1-2 | 关键规划资产未入库 | `docs/research/*`、`xyq-studio` spec、`grok-api-gateway` plan、`runtime/identity` |
| P1-3 | antibot 遗留脚本与双报告目录 | `run_detect*`/`run_hardened*` 与 `run_takeover`；`report/` vs `reports/` |
| P1-4 | 实验产物进 git | `antibot/report/*.png/json` |
| P1-5 | 根目录 session dump | `session-ses_09ab.md`（未跟踪，但仍污染工作区） |

### P2（洁癖 / 可延后）

| ID | 问题 |
|----|------|
| P2-1 | DrissionPage 是否改 submodule |
| P2-2 | docs 是否按产品分子目录（`docs/runtime/`、`docs/grokgw/`） |
| P2-3 | 根级 workspace 元数据（uv/poetry workspace） |
| P2-4 | grokgw 是否物理拆仓（逻辑上已独立） |

---

## 5. 建议（改 / 不改 / 延后）

### 5.1 现在 **不该** 做的（避免假装专业）

- ❌ 大挪目录、拆 monorepo（成本高，不解决「主线不清」）。
- ❌ 为研究仓上全套 monorepo CI/build（AGENTS 明确抵制，除非你改策略）。
- ❌ 同时推进 runtime identity + studio P0 + grokgw 运维 + antibot 硬化四条线而不写优先级。

### 5.2 现在 **该** 做的（低成本、高收益）— 建议顺序

| 序 | 动作 | 类型 | 说明 |
|----|------|------|------|
| 1 | 写 **仓库身份一页纸**（root README 或 AGENTS 顶部「Workspace map」） | 只改文档 | 四条线 + 主线 + 非目标 + 入口命令 |
| 2 | 维护 **Status 真相表**（一张表：产品 / 阶段 / 状态 / 下一步） | 只改文档 | 放 `docs/ROADMAP.md` 或 AGENTS 节 |
| 3 | 回写 plan/spec Status（Done / In progress / Parked） | 只改文档 | checkbox 或文件头 Status |
| 4 | 决定 git 边界：xpage 独立 remote vs 继续挂 grokgw | **你拍板** | 见第 6 节 |
| 5 | 决定 studio：本周做 P0 scaffold / 明确 Parked | **你拍板** | 避免 approved 悬空 |
| 6 | 提交或有意忽略 `runtime/identity` 与 research docs | 卫生 | 未跟踪 ≠ 不存在 |
| 7 | antibot report 出库 / session dump 移到 docs/research 或删除 | 卫生 | P1 |

### 5.3 目录「理想态」（渐进，非一次性）

```
xpage/                          # research workspace（名字与 remote 最终应对齐）
  AGENTS.md                     # 操作真相 + Workspace map
  README.md                     # 人读：四条线与主线（建议新增）
  docs/
    ROADMAP.md                  # 建议新增：状态表
    research/                   # 调研与审计（本文件所在）
    superpowers/
      specs/   plans/           # 可先保持平铺；或日后按产品前缀
  antibot/                      # lab only
  runtime/                      # ops product
  grokgw/                       # gateway product（可继续子目录发布）
  studio/                       # 仅当 unpark 时创建
  DrissionPage/                 # vendored dep
  data/                         # gitignored runtime
```

**不必**为对齐理想态而现在就 mv。

---

## 6. 需要你拍板的决策（你只出偏好与资源）

你不需要懂「monorepo 教条」。请只回答资源与意图：

### D1 — 这个仓库的「主身份」是什么？

| 选项 | 含义 | 适合若你… |
|------|------|-----------|
| A. **研究工作区**（xpage） | remote 应叫 xpage；grokgw 是其中一子树或 submodule | 浏览器自动化研究 + 多实验长期为主 |
| B. **grokgw 产品仓** | 应逐步迁出 runtime/antibot 或别的仓 | 网关是唯一要公开/部署的东西 |
| C. **有意的多产品 monorepo** | remote 用中性名；README 写清多包 | 单人维护多工具、接受共仓 |

**审计推荐默认：** **C**（承认现实），remote 中长期改名或增加 xpage remote；短期至少文档写清。

### D2 — 当前唯一主线（选 1 个，其余 Park）

| 选项 | 已有动能 |
|------|----------|
| 1. grokgw 远程部署 / 稳定 API | BLR plan、deploy 模板、最近 commits |
| 2. runtime 运营闭环 / identity | 本地代码多、部分未提交 |
| 3. studio P0 scaffold | 仅 design approved |
| 4. antibot 指纹 hardening 收尾 | lab 成熟、非营收路径 |

没有主线时，任何「专业流程」都会变成多线程空转。

### D3 — studio 怎么处理？

| 选项 | 动作 |
|------|------|
| Park | Status 改为 Parked；从 Approved 实施队列拿掉 |
| Do P0 | 单独开 plan，建 `studio/`，范围锁死 doctor+char+project |
| Merge 叙事 | 若其实从属于「内容生产」，写进总 roadmap 再排期 |

### D4 — 未跟踪的 `runtime/identity` 与 research 文档

| 选项 | 动作 |
|------|------|
| 入库 | commit（注意 secrets 不要进） |
| 明确本地-only | 写进 AGENTS「实验未入库」 |

---

## 7. 给你用的「引导式操作手册」（下次怎么自己发起）

当你再次觉得「乱了」，对 agent 只说：

```text
请按 docs/research/2026-07-17-xpage-structure-audit.md 的流程
做一次只读复审：更新第 1–4 节差距，不要改目录。
我当前主线是：______。
```

或极简：

```text
对照 ROADMAP（若有）和 AGENTS Workspace map，
只回答：规划是否仍合理、目录是否仍匹配主线。只读。
```

你负责填空的只有：**主线是什么、愿意花多少时间、什么绝对不做**。

---

## 8. 审计结论（一页）

1. **目录骨架合格**（lab / runtime / grokgw / data / docs 分层成立）。  
2. **规划单品质量不错，仓级规划缺失** → 分数卡在 3 分档。  
3. **最大风险不是文件夹名字，而是真相源腐烂**（Status、checkbox、AGENTS 开篇、git remote、未跟踪实现）。  
4. **立即大拆仓或大挪目录：不推荐。**  
5. **下一步最高杠杆：** 你选定 D1+D2 → 我（或下一会话）只改文档落地 Workspace map + ROADMAP + 回写 Status；再谈是否 scaffold studio 或提交 identity。

---

## 9. 证据索引（便于复查）

- `AGENTS.md` L1–8（Two roots）、L119–155（runtime/grokgw）
- `runtime/paths.py`（DATA、STEALTH_MIN_JS → antibot）
- `docs/superpowers/specs/2026-07-16-xyq-studio-lite-design.md`（Approved + package `studio/`）
- `git remote -v` → grokgw
- `git status`：identity / research / studio spec 未跟踪；plans checkbox 未回写
- `du -sh data` ≈ 202M profiles（gitignore 生效）

---

## 10. 用户决策落地（2026-07-17）

| 决策 | 选择 | 已落点 |
|------|------|--------|
| D1 主身份 | 多产品研究工作区 | `docs/ROADMAP.md` + `AGENTS.md` Workspace map |
| D2 主线 | grokgw 部署/稳定 API | ROADMAP ACTIVE |
| D3 studio | 进总路线图，稍后再定 | ROADMAP **ROADMAPPED**（非 PARKED、非本周 scaffold） |

后续可选：回写各 plan checkbox / spec Status；整理 `runtime/identity` 入库；remote 中性化（非本周必须）。

---

*本报告由 2026-07-17 只读审计生成；第 10 节为同日决策回写。*
