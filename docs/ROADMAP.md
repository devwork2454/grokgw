# xpage Workspace Roadmap

- **Updated:** 2026-07-17（收敛修订）
- **Identity:** 多产品 **研究工作区**（research monorepo）
- **Active main line:** **grokgw BLR Phase A**（proxy + SSH 隧道）— plan Task **2–7**
- **现状快照（必读）:** [`docs/STATUS.md`](STATUS.md)
- **结构审计:** [`docs/research/2026-07-17-xpage-structure-audit.md`](research/2026-07-17-xpage-structure-audit.md)

> **三角导航：** STATUS = 现在是什么 · **本文件** = 接下来做什么 · AGENTS = 怎么操作  
> 你只维护：**主身份**、**唯一主线**、**各线状态词**。

---

## 1. 产品线状态表

| 线 | 目录 | 成熟度（摘要） | 状态 | 本周期动作 |
|----|------|----------------|------|------------|
| **grokgw** | `grokgw/` | 本地实现+80 tests；deploy 模板 DONE | **ACTIVE** | 只做 BLR plan **Task 2–7** 实机验收 |
| **runtime** | `runtime/` | P0 已验收；103 tests；identity 本地扩展 | **PARKED** | 不新功能；提交整理可另开窗口 |
| **antibot** | `antibot/` | lab 可用；遗留脚本并存 | **PARKED** | 仅主线需要时回归；不扩脚本 |
| **studio** | *无* | 仅有 Approved 设计 | **ROADMAPPED** | 不 scaffold；启动前再写 plan |
| **DrissionPage** | `DrissionPage/` | vendored 5.0.0b0 | 依赖 | 不主动升级 |

状态词：

| 词 | 含义 |
|----|------|
| **ACTIVE** | 本周期唯一允许大块投入的线 |
| **PARKED** | 明确暂停扩 scope |
| **ROADMAPPED** | 承认要做，未排进本周期 |
| **DONE** | 阶段完成（见 STATUS） |

---

## 2. 本周期 Definition of Done（grokgw BLR）

全部满足才算主线收口：

1. BLR：`GROKGW_BACKEND=proxy`、`GROKGW_PROXY_MODE=never` 服务稳定  
2. `8787` 仅本机；操作员经 **SSH 隧道**访问  
3. 服务端 `healthz` + chat 冒烟通过  
4. 本机隧道端到端 chat 通过  
5. `grokgw/deploy/README-remote-proxy.md` 与现实步骤一致  

**非目标：** CLI 上机、media 远程、studio、runtime 新能力、拆 monorepo、公网裸奔 8787、动 hy2/LAX。

**执行入口：** `docs/superpowers/plans/2026-07-17-grokgw-blr-proxy-deploy.md`（从 Task 2 起）。

---

## 3. 仓级约定

| 项 | 约定 |
|----|------|
| 仓库是什么 | lab + 运营运行时 + 网关 +（未来）创作编排 |
| 规划真相 | STATUS（现实）+ 本 ROADMAP（优先级）+ 当前 ACTIVE plan |
| Git remote | 现仍 `devwork2454/grokgw`；与多产品身份不完全一致 — 中期再中性化 |
| 数据 | `data/` gitignore；密钥不进仓 |
| 环境 | `source antibot/.venv/bin/activate` |

---

## 4. 决策与收敛日志

| 日期 | 内容 |
|------|------|
| 2026-07-17 | 结构审计；D1=多产品工作区；D2=grokgw 部署主线；D3=studio 进路线图稍后 |
| 2026-07-17 | **现状收敛**：STATUS.md；spec/plan Progress 回写；session dump 迁入 research；主线收窄为 BLR Task2–7 |
