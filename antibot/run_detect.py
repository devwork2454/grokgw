#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DrissionPage 反检测 - 基线检测脚本(A 任务)
有头/无头各跑一遍,采集 sannysoft 检测项结果 + navigator 指纹。
"""
import json
import os
import time
import sys

from DrissionPage import Chromium, ChromiumOptions

REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'report')
os.makedirs(REPORT_DIR, exist_ok=True)

# 本机网络修复:2080 是本地 socks5 代理(VPN),让 Chrome 走代理而非直连。
# 直连会因 IPv6 不通 + DNS 优先返回 IPv6 而卡死。走代理由代理解析 DNS,稳定。
BASE_ARGS = [
    '--no-sandbox',
    '--disable-gpu',
    '--proxy-server=socks5://127.0.0.1:2080',
]


def make_options(headless: bool, hardened: bool = False) -> ChromiumOptions:
    co = ChromiumOptions().auto_port()
    if headless:
        co.headless()
    for a in BASE_ARGS:
        co.set_argument(a)
    co.set_timeouts(base=20, page_load=40)
    if hardened:
        # 加固:不使用 co.set_user_agent(headless 下会导致启动异常),
        # 改用 stealth.js 在运行时修补 UA(defineProperty)。见 stealth_min.js
        from pathlib import Path
        stealth_js = Path(__file__).parent / 'stealth.js'
        if stealth_js.exists():
            co.set_pref('credentials_enable_service', False)
    return co


def collect_sannysoft(tab) -> dict:
    """读取 sannysoft 所有检测项结果(含滚动后渲染的下部分)"""
    time.sleep(3)  # 等表格渲染
    # 滚动到底触发可能的懒加载
    tab.run_js('window.scrollTo(0, document.body.scrollHeight)')
    time.sleep(2)
    res = tab.run_js('''
    const rows = document.querySelectorAll('td[id$="-result"], td.result, td.passed, td.failed');
    const items = {};
    const list = [];
    for (const td of rows) {
        let name = td.id ? td.id.replace(/-result$/, '') : (td.previousElementSibling ? td.previousElementSibling.innerText.trim().slice(0,30) : td.className);
        const passed = td.className.includes('passed');
        const failed = td.className.includes('failed');
        if (!td.id) continue;  // 只取有 id 的标准检测项
        name = td.id.replace(/-result$/, '');
        items[name] = {passed: passed, failed: failed, cls: td.className, txt: td.innerText.trim().slice(0,60)};
        list.push({id: td.id, name: name, cls: td.className, txt: td.innerText.trim().slice(0,60)});
    }
    return {items: items, list: list};
    ''')
    return res or {'items': {}, 'list': []}


def collect_fingerprint(tab) -> dict:
    """采集 navigator 等关键指纹"""
    js = '''
    const out = {};
    out.webdriver = navigator.webdriver;
    out.userAgent = navigator.userAgent;
    out.platform = navigator.platform;
    out.languages = navigator.languages;
    out.plugins_length = navigator.plugins.length;
    out.hardwareConcurrency = navigator.hardwareConcurrency;
    out.deviceMemory = navigator.deviceMemory;
    // window.chrome
    out.has_window_chrome = (typeof window.chrome !== 'undefined');
    out.chrome_runtime = (window.chrome && typeof window.chrome.runtime !== 'undefined');
    // WebGL
    try {
        const c = document.createElement('canvas');
        const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
        if (gl) {
            const dbg = gl.getExtension('WEBGL_debug_renderer_info');
            out.webgl_vendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : null;
            out.webgl_renderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null;
        }
    } catch(e) { out.webgl_error = e.message; }
    // permissions query (自动化时 Notification.permissions 行为异常是检测点)
    out.permission_notification_state = 'unknown';
    // webdriver flag in CDP
    out.cdc_props = (function(){
        // 检查 webdriver 注入痕迹 $cdc_ / $wdc_
        const keys = Object.keys(document).filter(k => k.startsWith('$cdc') || k.startsWith('$wdc'));
        return keys;
    })();
    return out;
    '''
    return tab.run_js(js) or {}


def _get_with_retry(tab, url, retries=3, timeout=20):
    """带重试的 get,应对本机网络间歇性卡顿"""
    last_err = None
    for i in range(retries):
        try:
            tab.get(url, timeout=timeout)
            return True
        except Exception as e:
            last_err = e
            print(f'    get 重试 {i+1}/{retries}: {e}', flush=True)
            time.sleep(2)
    print(f'    get 最终失败: {last_err}', flush=True)
    return False


def run_one(label: str, headless: bool, hardened: bool = False) -> dict:
    print(f'\n===== [{label}] headless={headless} hardened={hardened} =====', flush=True)
    result = {'label': label, 'headless': headless, 'hardened': hardened,
              'sites': {}, 'fingerprint': {}, 'error': None}
    b = None
    try:
        t0 = time.time()
        co = make_options(headless, hardened)
        b = Chromium(co)
        tab = b.latest_tab
        # 注入 stealth(加固模式)- 用 run_cdp 直接注入(bs9umuuu8 验证过可行)
        if hardened:
            from pathlib import Path
            js = (Path(__file__).parent / 'stealth_min.js').read_text(encoding='utf-8')
            tab.run_cdp('Page.addScriptToEvaluateOnNewDocument', source=js)
            print('  [+] stealth_min.js 已注入(run_cdp,修补UA)', flush=True)

        print(f'  启动耗时 {time.time()-t0:.1f}s', flush=True)

        # 1. sannysoft
        print('  -> sannysoft', flush=True)
        if _get_with_retry(tab, 'https://bot.sannysoft.com'):
            time.sleep(3)
            result['sites']['sannysoft'] = collect_sannysoft(tab)
            result['fingerprint'] = collect_fingerprint(tab)
            shot = os.path.join(REPORT_DIR, f'{label}_sannysoft.png')
            tab.get_screenshot(path=shot, full_page=True)
            print(f'  sannysoft 截图 -> {shot}', flush=True)
        else:
            result['sites']['sannysoft'] = {'error': 'get failed'}

        # 2. nowsecure
        print('  -> nowsecure', flush=True)
        try:
            if _get_with_retry(tab, 'https://nowsecure.nl', retries=2):
                time.sleep(3)
                ns_txt = tab.run_js('return document.body.innerText.slice(0,300)') or ''
                result['sites']['nowsecure'] = {'title': tab.title, 'text_head': ns_txt,
                                                'has_challenge': any(k in ns_txt.lower() for k in
                                                ['challenge','bot','human','verify','blocked','captcha'])}
                tab.get_screenshot(path=os.path.join(REPORT_DIR, f'{label}_nowsecure.png'), full_page=True)
        except Exception as e:
            result['sites']['nowsecure'] = {'error': f'{type(e).__name__}: {e}'}

        # 3. pixelscan
        print('  -> pixelscan', flush=True)
        try:
            if _get_with_retry(tab, 'https://pixelscan.net', retries=2):
                time.sleep(4)
                ps_txt = tab.run_js('return document.body.innerText.slice(0,400)') or ''
                result['sites']['pixelscan'] = {'title': tab.title, 'text_head': ps_txt}
                tab.get_screenshot(path=os.path.join(REPORT_DIR, f'{label}_pixelscan.png'), full_page=True)
        except Exception as e:
            result['sites']['pixelscan'] = {'error': f'{type(e).__name__}: {e}'}

    except Exception as e:
        import traceback
        result['error'] = f'{type(e).__name__}: {e}'
        result['traceback'] = traceback.format_exc()[:800]
        print(f'  [!] 异常: {result["error"]}', flush=True)
    finally:
        if b is not None:
            try:
                b.quit()
            except Exception:
                pass
        # 兜底:清理可能残留的 chrome 子进程(同 port)
        try:
            import subprocess
            subprocess.run("pkill -9 -f 'autoPortData' 2>/dev/null", shell=True, timeout=5)
        except Exception:
            pass

    # 统计 sannysoft 通过率
    san = result['sites'].get('sannysoft', {})
    items = san.get('items', {}) if isinstance(san, dict) else {}
    passed = sum(1 for v in items.values() if v.get('passed'))
    failed = sum(1 for v in items.values() if v.get('failed'))
    result['sannysoft_summary'] = {'passed': passed, 'failed': failed,
                                   'total': len(items),
                                   'failed_items': [k for k,v in items.items() if v.get('failed')]}
    print(f'  sannysoft: {passed} passed / {failed} failed / {len(items)} total', flush=True)
    if result['sannysoft_summary']['failed_items']:
        print(f'  失败项: {result["sannysoft_summary"]["failed_items"]}', flush=True)
    return result


def main():
    hardened = '--hardened' in sys.argv
    only = None
    for arg in sys.argv[1:]:
        if arg.startswith('--only='):
            only = arg.split('=', 1)[1]

    runs = []
    if only:
        runs.append(run_one(only, headless=(only.endswith('hl')), hardened=hardened))
    else:
        runs.append(run_one('baseline_head', headless=False, hardened=hardened))
        runs.append(run_one('baseline_hl', headless=True, hardened=hardened))

    out = os.path.join(REPORT_DIR, 'detect_result.json' if not hardened else 'detect_result_hardened.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(runs, f, ensure_ascii=False, indent=2)
    print(f'\n报告已写入: {out}', flush=True)

    # 打印对比摘要
    print('\n' + '=' * 60)
    print('摘要')
    print('=' * 60)
    for r in runs:
        s = r.get('sannysoft_summary', {})
        fp = r.get('fingerprint', {})
        print(f"{r['label']:20s} sannysoft {s.get('passed')}/{s.get('total')}  "
              f"webdriver={fp.get('webdriver')}  plugins={fp.get('plugins_length')}  "
              f"chrome_obj={fp.get('has_window_chrome')}")


if __name__ == '__main__':
    main()
