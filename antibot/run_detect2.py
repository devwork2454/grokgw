#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整检测脚本 - 基于 _diag_dp 验证过的可靠结构(普通前台 + 走代理)
支持 baseline / hardened 两种模式,输出到 report/ JSON + 截图。
用法: python run_detect2.py [hardened]
"""
import sys, time, json, os, traceback
from pathlib import Path
from DrissionPage import Chromium, ChromiumOptions

BASE = Path(__file__).parent
REPORT = BASE / 'report'
REPORT.mkdir(exist_ok=True)

def ws_state(d, path):
    d['ts'] = time.strftime('%H:%M:%S')
    Path(path).write_text(json.dumps(d, ensure_ascii=False))

def make_options(hardened):
    co = ChromiumOptions().auto_port().headless()
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--proxy-server=socks5://127.0.0.1:2080')
    co.set_timeouts(base=20, page_load=40)
    return co

def collect_sannysoft(tab):
    time.sleep(3)
    tab.run_js('window.scrollTo(0, document.body.scrollHeight)')
    time.sleep(2)
    return tab.run_js(r'''
    const rows = document.querySelectorAll("td[id$='-result']");
    const items = {};
    for (const td of rows) {
        if (!td.id) continue;
        const n = td.id.replace(/-result$/, '');
        items[n] = {passed: td.className.includes('passed'),
                    failed: td.className.includes('failed'),
                    cls: td.className,
                    txt: td.innerText.trim().slice(0, 50)};
    }
    return items;
    ''') or {}

def collect_fingerprint(tab):
    return tab.run_js(r'''
    const o = {};
    o.webdriver = navigator.webdriver;
    o.userAgent = navigator.userAgent;
    o.platform = navigator.platform;
    o.languages = navigator.languages;
    o.plugins_length = navigator.plugins.length;
    o.hardwareConcurrency = navigator.hardwareConcurrency;
    o.deviceMemory = navigator.deviceMemory;
    o.has_window_chrome = (typeof window.chrome !== 'undefined');
    o.chrome_runtime = (window.chrome && typeof window.chrome.runtime !== 'undefined');
    o.cdc_props = Object.keys(document).filter(k => k.startsWith('$cdc') || k.startsWith('$wdc'));
    try {
        const c = document.createElement('canvas');
        const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
        if (gl) {
            const dbg = gl.getExtension('WEBGL_debug_renderer_info');
            o.webgl_vendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : null;
            o.webgl_renderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null;
        } else { o.webgl_vendor = 'no_webgl_context'; o.webgl_renderer = 'no_webgl_context'; }
    } catch(e) { o.webgl_error = e.message; }
    return o;
    ''') or {}

def run(label, hardened):
    print(f'\n===== [{label}] hardened={hardened} =====', flush=True)
    state = f'/tmp/dp_{label}_state.json'
    ws_state({'step': 'start'}, state)
    b = None
    try:
        co = make_options(hardened)
        b = Chromium(co)
        tab = b.latest_tab
        ws_state({'step': 'browser_up'}, state)
        if hardened:
            js = (BASE / 'stealth_min.js').read_text(encoding='utf-8')
            tab.run_cdp('Page.addScriptToEvaluateOnNewDocument', source=js)
            print('  [+] stealth_min.js 注入', flush=True)
            ws_state({'step': 'stealth_injected'}, state)
        tab.get('https://bot.sannysoft.com', timeout=25)
        print(f'  sannysoft loaded: {tab.title}', flush=True)
        ws_state({'step': 'sanny_loaded'}, state)
        items = collect_sannysoft(tab)
        fp = collect_fingerprint(tab)
        tab.get_screenshot(path=str(REPORT / f'{label}_sannysoft.png'), full_page=True)
        passed = sum(1 for v in items.values() if v['passed'])
        failed = sum(1 for v in items.values() if v['failed'])
        print(f'  sannysoft: {passed} passed / {failed} failed / {len(items)} total', flush=True)
        for n, v in items.items():
            mark = 'OK' if v['passed'] else ('XX' if v['failed'] else '--')
            print(f'    {mark} {n:28s} {v["txt"]}', flush=True)
        print(f'  webdriver={fp.get("webdriver")} ua={str(fp.get("userAgent",""))[:50]}', flush=True)
        result = {'label': label, 'hardened': hardened, 'fingerprint': fp,
                  'sannysoft': {'items': items, 'passed': passed, 'failed': failed,
                                'total': len(items),
                                'failed_items': [n for n, v in items.items() if v['failed']]}}
        out = REPORT / ('detect_result_hardened.json' if hardened else 'detect_result.json')
        out.write_text(json.dumps([result], ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'  -> {out}', flush=True)
        ws_state({'step': 'done', 'passed': passed, 'failed': failed}, state)
    except Exception as e:
        print(f'  [!] {type(e).__name__}: {e}', flush=True)
        traceback.print_exc()
        ws_state({'step': 'error', 'err': str(e)}, state)
    finally:
        if b:
            try: b.quit()
            except: pass

if __name__ == '__main__':
    hardened = 'hardened' in sys.argv
    run('hardened_hl' if hardened else 'baseline_hl', hardened)
