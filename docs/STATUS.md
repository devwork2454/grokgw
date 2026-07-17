# xpage 现状收敛（单一快照）

- **As of:** 2026-07-17
- **身份:** 多产品研究工作区（research monorepo）
- **本周期主线:** grokgw BLR Phase A 部署（proxy + SSH 隧道）
- **导航:** 本文件 = **现在是什么**；`ROADMAP.md` = **接下来做什么**；`AGENTS.md` = **怎么操作**
- **结构审计:** `docs/research/2026-07-17-xpage-structure-audit.md`

> 读完本页应能回答：有几条线、各自成熟到哪、什么在动、什么冻结、git 里藏了什么坑。

---

## 0. 一句话总览

| | |
|--|--|
| **是什么** | 浏览器研究床 + 运营运行时 + Grok API 网关 共仓；创作编排仅有设计 |
| **主线** | 只推进 **grokgw 远程 proxy 部署验收** |
| **代码健康** | grokgw **80** tests PASS；runtime **103** tests PASS（2026-07-17 本机） |
| **最大缺口** | BLR 上 **尚未** 完成端到端部署验收；规划 Status/checkbox 长期失真（本快照已回写） |
| **不要做** | 本周期不扩 runtime/antibot/studio；不大挪目录；不拆仓 |

---

## 1. 产品线成熟度矩阵（收敛后）

| 线 | 目录 | 设计 | 实现 | 测试 | 部署/运营 | 本周期 | 收敛结论 |
|----|------|------|------|------|-----------|--------|----------|
| **grokgw** | `grokgw/` | 有（应标 Implemented） | 双后端 + media + deploy 模板 | 80 pass | **模板已提交；BLR 实机待 Task2–7** | **ACTIVE** | 代码成熟；**收敛焦点=远程验收** |
| **runtime** | `runtime/` | 有（P0 已验收记录） | P0 核心 + identity 扩展 | 103 pass | 本机 `data/` 有 profiles/db | **PARKED** | 功能已可用；**冻结扩 scope**；identity 未全部入库 |
| **antibot** | `antibot/` | AGENTS + 旧 test plan | 多脚本 + stealth | 有少量 tests | lab 报告在 `report/` | **PARKED** | 保留为回归床；不扩矩阵 |
| **studio** | *无* | Approved P0 design | **0** | — | — | **ROADMAPPED** | 仅文档；启动前再开 plan |
| **DrissionPage** | `DrissionPage/` | 上游 beta | vendored | 间接 | 依赖 | 依赖 | 钉死 5.0.0b0；不主动升 |

---

## 2. 文档地图（读哪里）

### 2.1 仓级（优先）

| 文件 | 职责 |
|------|------|
| **`docs/STATUS.md`**（本文件） | 现状快照、成熟度、git 卫生、冻结范围 |
| **`docs/ROADMAP.md`** | 主线 / PARKED / DoD / 决策日志 |
| **`AGENTS.md`** | Workspace map + 操作约束（代理、接管、venv） |

### 2.2 规格与计划（按线）

| 线 | Spec | Plan(s) | 现实进度（收敛表述） |
|----|------|---------|----------------------|
| grokgw 核心 | `specs/2026-07-15-grok-api-gateway-design.md` | `plans/2026-07-15-grok-api-gateway.md` | **代码已落地**（远超文件头 Draft）；plan checkbox 未维护 → 以 STATUS 为准 |
| grokgw media | （设计演进写在实现/README） | `plans/2026-07-16-grokgw-media-phase1.md` | **已 merge**（PR #1 系 commits） |
| grokgw BLR | — | `plans/2026-07-17-grokgw-blr-proxy-deploy.md` | **Task1 仓库模板 DONE**（`grokgw/deploy/*` 在 main）；**Task2–7 未做** → **ACTIVE** |
| runtime | `specs/2026-07-15-browser-ops-runtime-design.md` | `plans/2026-07-15-browser-ops-runtime-p0.md` | P0 有 `runtime/tests/ACCEPTANCE.md` 通过记录；identity 为 P0 后扩展 |
| studio | `specs/2026-07-16-xyq-studio-lite-design.md` | （无独立 plan） | 未实现 |
| antibot | `.claude/plans/antibot_test_plan.md` | — | lab 基线见 `antibot/reports/summary.md` |

### 2.3 研究笔记（非产品承诺）

| 文件 | 内容 |
|------|------|
| `docs/research/2026-07-17-xpage-structure-audit.md` | 规划+目录审计 |
| `docs/research/2026-07-15-apple-account-email-provider-matrix.md` | 邮箱供应商调研 |
| `docs/research/2026-07-15-grok-session-recap.md` | 会话复盘 |
| `docs/research/2026-07-16-opencode-ses_09ab-handoff.md` | agent handoff |
| `docs/research/session-ses_09ab.md` | 大会话 dump（从根目录迁入，便于收敛） |

---

## 3. 实现真相（按线压缩）

### 3.1 grokgw — 最完整产品线

**已有能力（代码在仓）：**

- OpenAI 兼容 `/v1/chat/completions` + `healthz` + models
- 后端：`proxy`（默认，直连 api.x.ai）| `cli`（Grok Build 沙箱）
- media Phase1：session 图片路径 rewrite + HTTP 提供
- 部署：`install.sh` / Docker；**远程 proxy** 模板在 `grokgw/deploy/`
- 公开 remote 名：`github.com/devwork2454/grokgw`（与 monorepo 内容不完全同名）

**本周期唯一开放工作：**

```
BLR plan Task 2 → 7：源码上机 → auth → systemd → 本机冒烟 → SSH 隧道 E2E → 运维清单
```

**本周期明确不做：** CLI 上 BLR、media 远程、公网裸奔 8787、改 hy2。

### 3.2 runtime — 已可用，本周期冻结

**已有：** Store / Risk / BrowserRuntime / Session / Scheduler / CLI / 内置 tasks；  
**验收：** `runtime/tests/ACCEPTANCE.md`（V1–V8 多数 PASS，V4 部分）。  
**扩展（工作区未全部 git 跟踪）：** `runtime/identity/*`（Apple 注册、验证码、邮箱探测、identity-gen）+ 对应 tests。  
**数据：** `data/` ≈ profiles 为主（gitignore）；`xpage.db` 存在。

**收敛策略：** PARKED = 不新功能；需要时只允许「修阻塞 / 提交已有代码」级，且不抢 grokgw 部署。

### 3.3 antibot — lab，冻结扩面

- 主路径：`run_takeover.py` / `run_monitor.py` + `stealth_min.js`
- 遗留：`run_detect*` / `run_hardened*`（历史脚本，不必删，不扩展）
- 产物：`report/`（部分已入库截图）vs `reports/summary.md`
- 被 runtime 引用：`stealth_min.js`（硬路径，合理耦合）

### 3.4 studio — 仅设计

- Spec Approved；**无 `studio/` 目录**
- 状态词：**ROADMAPPED**（承认未来要做，未排期）

---

## 4. Git / 工作区卫生（收敛视图）

### 4.1 已跟踪 vs 本地增量（审计日）

| 类别 | 状态 | 收敛建议 |
|------|------|----------|
| grokgw 主代码 + deploy 模板 | 已在 main | 保持；主线用 pull/rsync 上 BLR |
| AGENTS / ROADMAP / STATUS / research | 新增或改动 | **应入库**（无 secret） |
| runtime/identity + 新测试 | 未跟踪 | PARKED 期可「整包待提交」；不在本周期强制 merge 逻辑 |
| runtime 核心 cli/models/schema/store | 有本地修改 | 与 identity 一并择期整理；非主线 |
| session dump | 迁入 `docs/research/` | 勿放仓库根 |
| `data/` | gitignore | 永不提交 |
| `antibot/report` 截图 | 已跟踪 | 中期可出库；非主线不强制 |

### 4.2 Remote 语义

- `origin` = **grokgw** 产品名仓库，但内容含 runtime / antibot / DrissionPage。  
- **短期：** 文档消歧（本 STATUS + ROADMAP）即可。  
- **中期：** 中性名 xpage remote 或拆发布面——**非本周期**。

---

## 5. 收敛规则（以后怎么保持不散）

1. **只认三个入口：** STATUS（现状）→ ROADMAP（优先级）→ 当前 ACTIVE 的那一份 plan。  
2. **改主线 = 改 ROADMAP**，并在 STATUS 顶部日期刷新。  
3. **实现完成 = 先改 STATUS 成熟度 / plan 顶部 Progress**，不要依赖上百个 checkbox 手工勾。  
4. **PARKED 线** 默认拒绝新 scope；agent 看到 PARKED 应提示用户而非开做。  
5. **研究笔记** 只进 `docs/research/`，不进产品承诺。  
6. **运行时与密钥** 只在 `data/` 与宿主机 `~/.grok/`，不进 git、不进 chat 回显。

---

## 6. 本周期行动边界（给执行 agent 的硬约束）

| 允许 | 禁止 |
|------|------|
| 执行 BLR deploy plan Task 2–7 | 实现 studio/ |
| 修 grokgw 部署 blocker | 新开 runtime 大功能 |
| 更新 STATUS/ROADMAP 进度 | 重构 monorepo 目录 |
| 文档澄清与 Status 回写 | 公网暴露 8787；动 LAX；改 hy2 主路径 |

**主线 DoD：** 见 `docs/ROADMAP.md` §2（隧道 + healthz + chat 冒烟 + 文档一致）。

---

## 7. 变更日志

| 日期 | 内容 |
|------|------|
| 2026-07-17 | 首次收敛快照：测试 80+103；主线 BLR；PARKED runtime/antibot；studio ROADMAPPED；迁出根目录 session dump |
