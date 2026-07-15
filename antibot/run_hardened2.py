#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""加固检测 - 增量写状态文件,确保即使 stdout 被吞也有结果"""
import time, json, sys, traceback
from pathlib import Path
BASE = Path('/home/zakza/project/research/xpage/antibot')
REPORT = BASE / 'report'
STATE = BASE / '_hardened_state.json'

def write_state(d):
    with open(STATE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

write_state({'step': 'start', 'ts': time.strftime('%H:%M:%S')})

try:
    from DrissionPage import Chromium, ChromiumOptions
    from hardened_options import build_hardened_extras, build_hardened_user_agent

    write_state({'step': 'config', 'ts': time.strftime('%H:%M:%S')})
    co = ChromiumOptions().auto_port().headless()
    for a in ['--no-sandbox','--disable-gpu','--host-resolver-rules=AF ipv4','--no-proxy-server']:
        co.set_argument(a)
    for a in build_hardened_extras():
        co.set_argument(a)
    co.set_user_agent(build_hardened_user_agent())
    co.set_timeouts(base=20, page_load=40)

    write_state({'step': 'launch_browser', 'ts': time.strftime('%H:%M:%S')})
    b = Chromium(co); tab = b.latest_tab

    write_state({'step': 'inject_stealth', 'ts': time.strftime('%H:%M:%S')})
    js = (BASE / 'stealth.js').read_text(encoding='utf-8')
    tab.run_cdp('Page.addScriptToEvaluateOnNewDocument', source=js)

    write_state({'step': 'get_blank', 'ts': time.strftime('%H:%M:%S')})
    tab.get('about:blank'); time.sleep(1)

    write_state({'step': 'get_sannysoft', 'ts': time.strftime('%H:%M:%S')})
    tab.get('https://bot.sannysoft.com', timeout=30)
    write_state({'step': 'loaded', 'ts': time.strftime('%H:%M:%S'), 'title': tab.title})
    time.sleep(3)

    write_state({'step': 'fingerprint', 'ts': time.strftime('%H:%M:%S')})
    fp = tab.run_js(r'''
    return {
      webdriver: navigator.webdriver,
      ua: navigator.userAgent,
      plugins: navigator.plugins.length,
      chrome: typeof window.chrome,
      chrome_runtime: !!(window.chrome && window.chrome.runtime),
      webgl_vendor: (function(){try{var c=document.createElement("canvas");var g=c.getContext("webgl");if(!g)return "no webgl context";var d=g.getExtension("WEBGL_debug_renderer_info");return d?g.getParameter(d.UNMASKED_VENDOR_WEBGL):"no ext";}catch(e){return e.message;}})(),
      webgl_renderer: (function(){try{var c=document.createElement("canvas");var g=c.getContext("webgl");if(!g)return "no webgl context";var d=g.getExtension("WEBGL_debug_renderer_info");return d?g.getParameter(d.UNMASKED_RENDERER_WEBGL):"no ext";}catch(e){return e.message;}})()
    };
    ''')
    write_state({'step': 'got_fingerprint', 'ts': time.strftime('%H:%M:%S'), 'fp': fp})

    san = tab.run_js(r'''
    var rows = document.querySelectorAll("td[id$='-result']");
    var items = {};
    for (const td of rows) {
      if (!td.id) continue;
      var n = td.id.replace(/-result$/, "");
      items[n] = {passed: td.className.includes("passed"), failed: td.className.includes("failed"), txt: td.innerText.trim().slice(0,40)};
    }
    return items;
    ''')
    passed = sum(1 for v in san.values() if v['passed'])
    failed = sum(1 for v in san.values() if v['failed'])
    write_state({'step': 'got_sannysoft', 'ts': time.strftime('%H:%M:%S'),
                 'passed': passed, 'failed': failed, 'total': len(san),
                 'items': san, 'fp': fp})

    # 截图
    try:
        tab.get_screenshot(path=str(REPORT / 'hardened_hl_sannysoft.png'), full_page=True)
    except Exception as e:
        write_state({'step': 'screenshot_failed', 'err': str(e)})

    # 最终 JSON
    out = {'label': 'hardened_hl', 'fingerprint': fp,
           'sannysoft': {'items': san, 'passed': passed, 'failed': failed,
                         'total': len(san),
                         'failed_items': [n for n, v in san.items() if v['failed']]}}
    with open(REPORT / 'hardened_result.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    b.quit()
    write_state({'step': 'done', 'ts': time.strftime('%H:%M:%S'),
                 'passed': passed, 'failed': failed, 'failed_items': [n for n,v in san.items() if v['failed']]})

except Exception as e:
    write_state({'step': 'error', 'ts': time.strftime('%H:%M:%S'),
                 'err': f'{type(e).__name__}: {e}', 'trace': traceback.format_exc()[:1500]})
    raise
