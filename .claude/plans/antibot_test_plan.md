# DrissionPage 反检测实战测试计划

## 前提核实结论(已验证)
- Chrome 148 可被 CDP 启动,远程调试接口正常工作
- sannysoft 页面结构:每项检测 `<td class="passed|failed result" id="xxx-result">`,可精确读取通过/失败
- DrissionPage 本地源码 = 5.0.0b0(beta,未发 PyPI);PyPI 最新是 4.1.1.4(API 不同)
- 全部依赖在 PyPI 可得(requests/lxml/cssselect/DrissionGet/DrissionRecord/websocket-client/click/tldextract/psutil/ftfy)
- PyPI 可联网;网络直连可用(代理未运行但不需要)

## 用户决策
- 版本基线:**本地 5.0.0b0 源码**(`pip install -e .`),API 用 `Chromium` + `latest_tab`
- 运行模式:**有头 + 无头都测**,对比差异
- C 任务范围:**仅指纹/行为检测站**(sannysoft/pixelscan/browserleaks/nowsecure),不碰生产网站

## 目录与产物
所有产物放在 `/home/zakza/project/research/xpage/antibot/`:
- `env_setup.sh` - 环境准备脚本(装依赖、装本地源码)
- `stealth.js` - 注入的 stealth 反检测脚本(B 任务)
- `hardened_options.py` - 加固后的 ChromiumOptions 工厂(B 任务)
- `run_detect.py` - 主检测脚本(A/C 任务,有头+无头+加固前后对比)
- `report/` - 输出目录(截图 + JSON 报告)
- `monitor.py` - 封禁/验证码监测框架(C 任务核心)
- `reports/*.md` - 每轮测试总结

## 实施步骤

### 步骤 0:环境准备(一次性)
1. 建 venv:`python3 -m venv /home/zakza/project/research/xpage/antibot/.venv`
2. 升级 pip,`pip install -r requirements.txt`(从本地 DrissionPage/requirements.txt)
3. `cd DrissionPage && pip install -e .` 装本地 5.0.0b0 源码
4. 验证:`python -c "import DrissionPage; print(DrissionPage.__version__)"` 期望 `5.0.0b0`
- **验证标准**:import 成功,版本号正确

### 步骤 A:基线检测(未加固)
脚本 `run_detect.py` 核心逻辑:
1. 用最小配置启动 Chromium(`auto_port()`,临时用户数据目录)
2. 遍历测试站:[sannysoft, pixelscan, browserleaks/javascript, nowsecure]
3. 每站:`tab.get(url)` -> `wait.doc_loaded()` -> 全页截图 -> 读取关键指纹
4. sannysoft 精确读取:遍历所有 `td[id$="-result"]`,按 class 分 passed/failed,统计通过率
5. 读 JS 指纹:`navigator.webdriver`、`navigator.userAgent`、`navigator.plugins.length`、`navigator.languages`、WebGL vendor/renderer、permissions API
6. **有头模式跑一遍,无头模式跑一遍**,结果分别存 `report/headless_false.json` / `report/headless_true.json`
7. 打印对比摘要表(每模式通过项数/失败项数)
- **验证标准**:两轮都产出 JSON+截图,能看出哪些项暴露;期望 `navigator.webdriver=False`(CDP 优势)

### 步骤 B:加固配置
分析 A 暴露的项,针对性写 `stealth.js`(用 `add_init_js` 注入到每个新文档前执行):
- 覆盖 `navigator.webdriver` 为 undefined(防御性,即使 CDP 默认 false 也加固)
- 伪造 `navigator.plugins`(返回 3 个常见插件)、`navigator.languages`(返回 `['zh-CN','zh','en-US','en']`)
- 修复 `window.chrome` 对象、`navigator.permissions.query` 行为
- WebGL vendor/renderer 改成常见真实值(如 `Intel Inc.` / `Intel Iris OpenGL`)
- `hardened_options.py`:封装加固配置(真实 UA、`use_system_user_path` 或自定义、`--disable-blink-features=AutomationControlled`、`--no-sandbox` 等)
- **验证标准**:stealth.js 语法正确能在浏览器执行;hardened_options 能生成 Chromium 并打开页面

### 步骤 A2:加固后回归检测
用加固配置重跑步骤 A 的检测,结果存 `report/hardened_*.json`。
**对比 A vs A2**:看暴露项是否减少、通过率是否提升。
- **验证标准**:加固后 sannysoft 通过项数 >= 加固前;`navigator.webdriver` 仍为 False

### 步骤 C:封禁/验证码监测框架
脚本 `monitor.py` 设计为可复用框架:
1. **页面变化监测**:定期对比页面 DOM 关键特征,检测是否出现验证码元素(常见选择器:iframe[src*="captcha"]、`#challenge-form`、`g-recaptcha`、`h-captcha`、`cf-turnstile`、文字含"验证"/"人机"/"unusual traffic"/"blocked")
2. **网络响应监测**:用 `tab.listen` 监听响应,标记 403/429/503 状态码、含 `captcha`/`blocked`/`access denied` 的响应体
3. **行为触发**:可选触发动作(如重复快速请求、异常 UA),用于主动诱发验证码以测试监测是否生效
4. **结果输出**:监测到异常时记录时间戳、URL、异常类型、截图存证到 `report/alerts/`
5. 用 sannysoft/nowsecure 作为安全测试床验证监测逻辑(这些站会触发某些检测,但不会真封)
- **验证标准**:框架能正确识别"已知验证码元素"和"封禁响应码";在 nowsecure 上能监测到挑战行为

### 步骤 D:总结
汇总三任务结果到 `reports/summary.md`:
- DrissionPage 5.0.0b0 基线反检测能力(哪些项天然过关,哪些暴露)
- 有头 vs 无头差异
- 加固前后对比(通过率提升)
- 监测框架用法说明
- 诚实标注:哪些验证了、哪些受限于网络未验证(如 creepjs 不通)

## 风险与诚实标注
- creepjs(github.io)本地直连不通,只用 sannysoft 等可达站点
- 本机是无显示 Linux 环境,所谓"有头"模式实际可能是 headless=new 或 xvfb;需在步骤 A 确认有头能否真正启动可见窗口,若不行则如实标注"本环境无法真正有头,以 headless=new 代替"
- 5.0.0b0 是 beta,若遇 bug 如实报告不绕过
- 全程不触碰生产网站,不用真实账号,合规
