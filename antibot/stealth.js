// stealth.js - DrissionPage 反检测加固脚本
// 用法:tab.run_cdp('Page.addScriptToEvaluateOnNewDocument', source=stealth_js)
// 在每个新文档解析前执行,覆盖自动化痕迹。
// 注意:DrissionPage 用 CDP 直连,navigator.webdriver 默认就是 false,
//       本脚本主要修补 UA(HeadlessChrome)、plugins、languages、window.chrome 细节、WebGL。

(function () {
    'use strict';

    // ---------- 1. navigator.webdriver 防御性清除(即使已是 false 也确保) ----------
    try {
        Object.defineProperty(Navigator.prototype, 'webdriver', {
            get: () => false, configurable: true
        });
    } catch (e) {}

    // ---------- 2. window.chrome 对象补全 ----------
    // headless 模式下 window.chrome 可能存在但缺 runtime,补上使其更像普通 Chrome
    if (!window.chrome) {
        window.chrome = {};
    }
    if (!window.chrome.runtime) {
        // 不能完整伪造(会触发原型检测),仅补存在的属性
        window.chrome.runtime = {
            PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
            PlatformArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
            PlatformNaclArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
            RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' },
            OnInstalledReason: { INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update', SHARED_MODULE_UPDATE: 'shared_module_update' },
            OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' }
        };
    }
    // window.chrome.appi(headless 常缺)
    if (!window.chrome.app) {
        window.chrome.app = {
            isInstalled: false,
            InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
            RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
        };
    }
    // window.chrome.csi / loadTimes(headless 常缺,补上)
    if (!window.chrome.csi) {
        window.chrome.csi = function () { return { onloadT: Date.now(), startE: Date.now(), pageT: 0, tran: 15 }; };
    }
    if (!window.chrome.loadTimes) {
        window.chrome.loadTimes = function () {
            return {
                requestTime: Date.now() / 1000,
                startLoadTime: Date.now() / 1000,
                commitLoadTime: Date.now() / 1000,
                finishDocumentLoadTime: Date.now() / 1000,
                finishLoadTime: Date.now() / 1000,
                firstPaintTime: Date.now() / 1000,
                firstPaintAfterLoadTime: 0,
                navigationType: 'Other',
                wasFetchedViaSpdy: true,
                wasNpnNegotiated: true,
                npnNegotiatedProtocol: 'h2',
                wasAlternateProtocolAvailable: false,
                connectionInfo: 'h2'
            };
        };
    }

    // ---------- 3. navigator.plugins 伪造(常见真实插件) ----------
    // headless 下 plugins.length 可能是 0 或异常,伪造 3 个常见插件
    try {
        const fakePluginData = [
            { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }
        ];
        const makePluginArray = () => {
            const arr = [];
            fakePluginData.forEach(p => {
                const plugin = Object.create(Plugin.prototype);
                Object.defineProperties(plugin, {
                    name: { value: p.name, enumerable: true },
                    filename: { value: p.filename, enumerable: true },
                    description: { value: p.description, enumerable: true },
                    length: { value: 1, enumerable: true }
                });
                arr.push(plugin);
            });
            // 模拟 PluginArray
            arr.namedItem = function (name) { return this.find(p => p.name === name) || null; };
            arr.refresh = function () {};
            arr.item = function (i) { return this[i] || null; };
            return arr;
        };
        Object.defineProperty(Navigator.prototype, 'plugins', {
            get: makePluginArray, configurable: true
        });
    } catch (e) {}

    // ---------- 4. navigator.languages 确保 ----------
    try {
        Object.defineProperty(Navigator.prototype, 'languages', {
            get: () => ['zh-CN', 'zh', 'en-US', 'en'], configurable: true
        });
    } catch (e) {}

    // ---------- 5. permissions.query 修补 ----------
    // 自动化时 Notification 的 permissions.query 返回异常(prompt->denied),修成正常行为
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (window.navigator.permissions && origQuery) {
        window.navigator.permissions.query = function (params) {
            if (params && params.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission, onchange: null });
            }
            return origQuery.call(this, params);
        };
    }

    // ---------- 6. WebGL vendor/renderer 伪造(避开 swiftshader 痕迹) ----------
    // headless 常用 swiftshader,会暴露 "Google Inc. (Google)" / "SwiftShader"
    try {
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function (p) {
            // UNMASKED_VENDOR_WEBGL = 37445, UNMASKED_RENDERER_WEBGL = 37446
            if (p === 37445) return 'Intel Inc.';          // vendor
            if (p === 37446) return 'Intel Iris OpenGL Engine';  // renderer
            return getParameter.call(this, p);
        };
        // WebGL2 同样处理
        if (window.WebGL2RenderingContext) {
            const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function (p) {
                if (p === 37445) return 'Intel Inc.';
                if (p === 37446) return 'Intel Iris OpenGL Engine';
                return getParameter2.call(this, p);
            };
        }
    } catch (e) {}

    // ---------- 7. 隐藏 CDP 注入痕迹($cdc_ / $wdc_) ----------
    // webdriver 驱动常注入 $cdc_ 或 $wdc_ 全局变量,清理之
    try {
        for (const k of Object.keys(document)) {
            if (k.startsWith('$cdc') || k.startsWith('$wdc')) {
                try { delete document[k]; } catch (e) {}
            }
        }
    } catch (e) {}

    // ---------- 8. 修补 navigator.userAgent(去除 HeadlessChrome 字样) ----------
    // 注意:userAgent 是只读,需用 defineProperty 覆盖。
    // 替换 HeadlessChrome 为 Chrome,并修正版本号格式
    try {
        const origUA = navigator.userAgent;
        if (origUA.indexOf('HeadlessChrome') > -1) {
            const fixedUA = origUA.replace(/HeadlessChrome/g, 'Chrome');
            Object.defineProperty(Navigator.prototype, 'userAgent', {
                get: () => fixedUA, configurable: true
            });
        }
        // 修正 appVersion 同步
        if (navigator.appVersion && navigator.appVersion.indexOf('HeadlessChrome') > -1) {
            const fixedAV = navigator.appVersion.replace(/HeadlessChrome/g, 'Chrome');
            Object.defineProperty(Navigator.prototype, 'appVersion', {
                get: () => fixedAV, configurable: true
            });
        }
    } catch (e) {}

})();
