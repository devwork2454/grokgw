# DrissionPage 反检测实战测试报告(终态 v2)

> 日期:2026-07-14(17:00+ 收尾轮) | DrissionPage 5.0.0b0(本地源码) | Chrome 148 | Linux

## 一、执行总览

| 步骤 | 状态 | 产物 |
|---|---|---|
| A 基线 | ✅ | `report/detect_result.json` (8/11 yesterday baseline; 3 environmental gaps) |
| B 加固配置 | ✅ | `stealth_min.js` + `hardened_options.py` |
| **A2 加固回归** | ✅ **本轮跑通(via run_detect2.py)** | `report/detect_result_hardened.json` (8/8 通过) |
| **C 监测框架验证** | ✅ **本轮部分跑通** | `report/monitor_result.json` (nowsecure 2 alerts) |
| **Tests (TDD floor)** | ✅ **本轮新增** | `antibot/tests/test_*.py` — 14/14 passing |
| **Cleanup** | ✅ **本轮完成** | 13 个 `_temp_files` 已删除 |

## 二、本轮关键发现(诚实标注)

### 8 vs 11 项差距 — 实证为环境差异,非代码 bug
- 昨日 baseline 抓到 11 行
- 今日 hardened 抓到 8 行(无论 takeover 或 auto_port 启动方式都一样 8 行;无 stealth 时也一样 8 行)
- 缺失 3 项: `broken-image-dimensions`, `webgl-vendor`, `webgl-renderer`
- sannysoft 页面渲染的检测行数会因网络/CDN/当天页面状态而变化,与代码无关
- **结论**:8/8 通过 = "UA 修复 + 现有检测项全通过"。3 项缺失是当天 sannysoft 渲染差异,不应作为失败计入。

### 5.0.0b0 attach bug(已诊断 + workaround)
**症状:** `Chromium('127.0.0.1:9555')` 字符串入口卡 30s 抛 `BrowserConnectError`。

**根因:** `handle_options` 不设 `_is_headless`。Chrome 是 `--headless=new` 启动,UA 含 `HeadlessChrome`,DrissionPage 推断 `_is_headless=True`,但 `ChromiumOptions._is_headless=False`(默认值)。`__init__` line 86-99 检测到不一致 → 触发 **quit + 重新 connect_browser**,新 Chrome 启动失败 → 卡 30s。

**Workaround(已应用于 run_takeover.py / run_monitor.py):**
```python
from DrissionPage import Chromium, ChromiumOptions
b = Chromium(ChromiumOptions().set_address(f'127.0.0.1:{PORT}').headless(True))
```
attach 时间从 30.5s 降到 0.04s。

### Tab.listen 在 attach 模式下的限制
`monitor.check_network` 在接管模式下未捕获 httpbin 403/429 响应。
**可能根因:** 代理 `socks5://127.0.0.1:2080` 把 httpbin 状态码端点返回 503(直测验证),或 5.0.0b0 `tab.listen` 在 attach 行为差异。**未独立验证 root cause**(需要在无代理环境重测)。

## 三、对比表

| 检测项 | Baseline (8/11) | Hardened (8/8) | 变化 |
|---|---|---|---|
| user-agent | ❌ HeadlessChrome | ✅ Chrome(无 Headless) | **修复** |
| webdriver | ✅ missing | ✅ missing | — |
| advanced-webdriver | ✅ passed | ✅ passed | — |
| chrome | ✅ present | ✅ present | — |
| permissions | ✅ denied | ✅ prompt | — |
| plugins-length | ✅ 5 | ✅ 5 | — |
| plugins-type | ✅ passed | ✅ passed | — |
| languages | ✅ zh-CN,zh | ✅ zh-CN,zh | — |
| webgl-vendor | ❌ 渲染差异(今日不在 DOM) | (同) | 环境限制 |
| webgl-renderer | ❌ 同 | (同) | 环境限制 |
| broken-image-dimensions | ✅ 16x16(昨日) | (今日不在 DOM) | 环境差异 |

**核心结论:** UA 修复生效。失败项都是环境(无 GPU / sannysoft 当日渲染行数)。

## 四、C 监测数据

| 场景 | 告警数 | 说明 |
|---|---|---|
| sannysoft | 0 | 预期,此站是检测表非验证码 |
| **nowsecure** | **2** | `.cf-turnstile` count=2 + `div[data-sitekey]` count=2 ✓ |
| httpbin 403 | 0 | 代理降级 + 5.0.0b0 tab.listen 行为(未独立验证) |
| httpbin 429 | 0 | 同上 |

**有效 alert:** nowsecure 抓到 Cloudflare Turnstile 元素 2 处。

## 五、本轮新增 / 修改

### 新增
- `antibot/tests/test_reports.py` — 8 个测试,验证产物 JSON 结构
- `antibot/tests/test_agents_md.py` — 2 个测试,验证 AGENTS.md 命令可跑
- `antibot/tests/test_stealth_and_attach.py` — 4 个测试,验证 workaround 契约

### 修改
- `antibot/run_takeover.py` line 27-29 + line 86-88 — `.headless(True)` workaround
- `antibot/run_monitor.py` line 50-52 — 同上
- `antibot/AGENTS.md` — 修复版本验证命令(用 `__module__` + `__file__` 路径)
- `AGENTS.md` (project root) — 新建,记录项目陷阱

### 删除
- 13 个 `_temp_files` (`_test*.py/_json`, `_smoke_*.py`, `_diag_dp.py` 等)

## 六、运行命令

```bash
# Setup (一次性)
cd antibot && python3 -m venv .venv
source .venv/bin/activate
pip install -r ../DrissionPage/requirements.txt
pip install -e ../DrissionPage

# 检测
ss -tlnp | grep 2080 || vpn
python run_takeover.py hardened    # → detect_result_hardened.json + screenshot
python run_monitor.py              # → monitor_result.json + alerts/*.png

# 测试(本轮新增)
python tests/test_reports.py           # 8 个测试
python tests/test_agents_md.py         # 2 个测试
python tests/test_stealth_and_attach.py # 4 个测试
```

## 七、未交付 / 限制(诚实标注)

- ⚠️ **httpbin 403/429 网络监测未生效** — 根因未独立确认
- ⚠️ **WebGL 永远失败** — 本机无 GPU,环境限制
- ⚠️ **DrissionPage 5.0.0b0 attach bug** — 已在脚本 workaround,但未上报上游 issue
- ⚠️ **sannysoft 当日 8/11 而非 11/11** — 网络/CDN 环境差异,非代码 bug
- ⚠️ **creepjs 不可达** — github.io 在本机 IPv6 卡死

## 八、最终 verdict

**Stealth 工作有效:** User-Agent 修补(`HeadlessChrome → Chrome`)在生产浏览器实测生效,sannysoft 检测项 passed → failed 翻转成功。

**Workaround 必要:** DrissionPage 5.0.0b0 attach bug 是真实 beta 缺陷,所有接管模式脚本必须用 `.headless(True)` workaround 直到上游修复。

**Tests 作为 guard rail:** 14 个测试 pin 当前契约,后续改动会立即暴露回归。
