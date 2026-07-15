#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""加固后完整检测(A2),输出写到 stdout 和 JSON 文件"""
import time, json, os
from pathlib import Path
from DrissionPage import Chromium, ChromiumOptions
from hardened_options import build_hardened_extras, build_hardened_user_agent

BASE = Path(__file__).parent
REPORT = BASE / 'report'
REPORT.mkdir(exist_ok=True)

try:
  print('启动加固浏览器', flush=True)
  co = ChromiumOptions().auto_port().headless()
for a in ['--no-sandbox','--disable-gpu','--host-resolver-rules=AF ipv4','--no-proxy-server']:
    co.set_argument(a)
for a in build_hardened_extras():
    co.set_argument(a)
co.set_user_agent(build_hardened_user_agent())
co.set_timeouts(base=20, page_load=40)
b = Chromium(co); tab = b.latest_tab

js = (BASE / 'stealth.js').read_text(encoding='utf-8')
r = tab.run_cdp('Page.addScriptToEvaluateOnNewDocument', source=js)
print(f'stealth.js 注入: {r}', flush=True)

tab.get('about:blank'); time.sleep(1)
print('get sannysoft', flush=True)
tab.get('https://bot.sannysoft.com', timeout=30)
print(f'title={tab.title}', flush=True)
time.sleep(3)

fp = tab.run_js('''
return {
  webdriver: navigator.webdriver,
  ua: navigator.userAgent,
  plugins: navigator.plugins.length,
  chrome: typeof window.chrome,
  chrome_runtime: !!(window.chrome && window.chrome.runtime),
  webgl_vendor: (function(){try{var c=document.createElement('canvas');var g=c.getContext('webgl');if(!g)return 'no webgl context';var d=g.getExtension('WEBGL_debug_renderer_info');return d?g.getParameter(d.UNMASKED_VENDOR_WEBGL):'no ext';}catch(e){return e.message;}})(),
  webgl_renderer: (function(){try{var c=document.createElement('canvas');var g=c.getContext('webgl');if(!g)return 'no webgl context';var d=g.getExtension('WEBGL_debug_renderer_info');return d?g.getParameter(d.UNMASKED_RENDERER_WEBGL):'no ext';}catch(e){return e.message;}})()
};
''')
print('=== 加固后指纹 ===', flush=True)
for k,v in fp.items(): print(f'  {k}: {v}', flush=True)

san = tab.run_js(r'''
const rows = document.querySelectorAll("td[id$='-result']");
const items={};
for(const td of rows){if(!td.id)continue;const n=td.id.replace(/-result$/,'');items[n]={passed:td.className.includes('passed'),failed:td.className.includes('failed'),txt:td.innerText.trim().slice(0,40)};}
return items;
''')
passed=sum(1 for v in san.values() if v['passed'])
failed=sum(1 for v in san.values() if v['failed'])
print(f'\n=== sannysoft: {passed} passed / {failed} failed / {len(san)} total ===', flush=True)
for n,v in san.items():
    mark = '✅' if v['passed'] else ('❌' if v['failed'] else '·')
    print(f'  {mark} {n:25s} {v["txt"]}', flush=True)

out={'label':'hardened_hl','fingerprint':fp,
     'sannysoft':{'items':san,'passed':passed,'failed':failed,'total':len(san),
                  'failed_items':[n for n,v in san.items() if v['failed']]}}
with open(REPORT/'hardened_result.json','w',encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
tab.get_screenshot(path=str(REPORT/'hardened_hl_sannysoft.png'), full_page=True)
b.quit()
print(f'\n已存 {REPORT/"hardened_result.json"}', flush=True)
print('done', flush=True)
except Exception as e:
    import traceback
    print(f'\n[!] 异常: {type(e).__name__}: {e}', flush=True)
    traceback.print_exc()
