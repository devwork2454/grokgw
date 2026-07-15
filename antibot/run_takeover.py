#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可靠检测:subprocess 启动 Chrome(走代理,已验证稳定),DrissionPage 接管 9555。
用法: python run_takeover.py [hardened]
"""
import sys, time, json, os, subprocess, traceback
from pathlib import Path
from DrissionPage import Chromium

BASE = Path(__file__).parent
REPORT = BASE / 'report'
REPORT.mkdir(exist_ok=True)
PORT = 9555
USER_DIR = '/tmp/dp_takeover'

def wait_port(port, timeout=30):
    import urllib.request
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False

def collect_sannysoft(tab):
    # Note: timing isn't the issue for the 11-row count vs today's actual ~8 rows.
    # Sannysoft's row count varies day-to-day by environmental page state (network/CDN).
    # Keep these waits at the proven baseline pattern (matches run_detect2.py).
    time.sleep(3)
    tab.run_js('window.scrollTo(0, document.body.scrollHeight)')
    time.sleep(2)
    return tab.run_js(r'''
    const rows = document.querySelectorAll("td[id$='-result']");
    const items = {};
    for (const td of rows) {
        if (!td.id) continue;
        const n = td.id.replace(/-result$/, "");
        items[n] = {passed: td.className.includes("passed"),
                    failed: td.className.includes("failed"),
                    txt: td.innerText.trim().slice(0, 50)};
    }
    return items;
    ''') or {}

def collect_fingerprint(tab):
    return tab.run_js(r'''
    const o = {};
    o.webdriver = navigator.webdriver;
    o.userAgent = navigator.userAgent;
    o.languages = navigator.languages;
    o.plugins_length = navigator.plugins.length;
    o.has_window_chrome = (typeof window.chrome !== "undefined");
    o.chrome_runtime = (window.chrome && typeof window.chrome.runtime !== "undefined");
    o.cdc_props = Object.keys(document).filter(k => k.startsWith("$cdc") || k.startsWith("$wdc"));
    try {
        const c = document.createElement("canvas");
        const gl = c.getContext("webgl") || c.getContext("experimental-webgl");
        if (gl) {
            const dbg = gl.getExtension("WEBGL_debug_renderer_info");
            o.webgl_vendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : null;
            o.webgl_renderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null;
        } else { o.webgl_vendor = "no_webgl_context"; o.webgl_renderer = "no_webgl_context"; }
    } catch(e) { o.webgl_error = e.message; }
    return o;
    ''') or {}

def run(label, hardened):
    print(f'\n===== [{label}] hardened={hardened} =====', flush=True)
    # 1. 启动 Chrome(走代理,已验证稳定的命令)
    subprocess.run(['pkill', '-9', '-f', 'remote-debugging-port=9555'], timeout=5)
    time.sleep(1)
    import shutil
    if Path(USER_DIR).exists():
        shutil.rmtree(USER_DIR, ignore_errors=True)
    cmd = ['google-chrome', '--headless=new', '--no-sandbox', '--disable-gpu',
           '--proxy-server=socks5://127.0.0.1:2080',
           f'--remote-debugging-port={PORT}',
           f'--user-data-dir={USER_DIR}', 'about:blank']
    print('  启动 Chrome 9555(走代理)...', flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_port(PORT, 30):
            print('  [!] Chrome 9555 未就绪', flush=True)
            return
        print('  Chrome 就绪', flush=True)
        # 2. DrissionPage 接管
        # 5.0.0b0 attach bug:必须显式 .headless(True) 同步 _is_headless,否则 __init__ 触发 quit+reconnect 卡 30s
        from DrissionPage import ChromiumOptions
        b = Chromium(ChromiumOptions().set_address(f'127.0.0.1:{PORT}').headless(True))
        tab = b.latest_tab
        # 3. 注入 stealth(加固)
        if hardened:
            js = (BASE / 'stealth_min.js').read_text(encoding='utf-8')
            tab.run_cdp('Page.addScriptToEvaluateOnNewDocument', source=js)
            print('  [+] stealth_min.js 注入', flush=True)
        # 4. 访问 sannysoft
        tab.get('https://bot.sannysoft.com', timeout=25)
        print(f'  sannysoft: {tab.title}', flush=True)
        items = collect_sannysoft(tab)
        fp = collect_fingerprint(tab)
        tab.get_screenshot(path=str(REPORT / f'{label}_sannysoft.png'), full_page=True)
        passed = sum(1 for v in items.values() if v['passed'])
        failed = sum(1 for v in items.values() if v['failed'])
        print(f'  sannysoft: {passed} passed / {failed} failed / {len(items)} total', flush=True)
        for n, v in items.items():
            print(f'    {"OK" if v["passed"] else "XX"} {n:28s} {v["txt"]}', flush=True)
        print(f'  webdriver={fp.get("webdriver")} ua={str(fp.get("userAgent",""))[:50]}', flush=True)
        print(f'  webgl_vendor={fp.get("webgl_vendor")} renderer={fp.get("webgl_renderer")}', flush=True)
        # 5. 写 JSON
        result = {'label': label, 'hardened': hardened, 'fingerprint': fp,
                  'sannysoft': {'items': items, 'passed': passed, 'failed': failed,
                                'total': len(items),
                                'failed_items': [n for n, v in items.items() if v['failed']]}}
        out = REPORT / ('detect_result_hardened.json' if hardened else 'detect_result.json')
        out.write_text(json.dumps([result], ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'  -> {out}', flush=True)
    except Exception as e:
        print(f'  [!] {type(e).__name__}: {e}', flush=True)
        traceback.print_exc()
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except: proc.kill()

if __name__ == '__main__':
    hardened = 'hardened' in sys.argv
    run('hardened_hl' if hardened else 'baseline_hl', hardened)
