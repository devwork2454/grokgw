#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""监测框架验证(C 任务)- 用 takeover 模式( subprocess Chrome 走代理 + DrissionPage 接管)
调用 monitor.BotMonitor 在 sannysoft / nowsecure / httpbin-403 上验证监测逻辑。
用法: python run_monitor.py
"""
import sys, time, json, os, subprocess, traceback, shutil
from pathlib import Path
from DrissionPage import Chromium

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from monitor import BotMonitor, Alert  # noqa

REPORT = BASE / 'report'
ALERTS = REPORT / 'alerts'
ALERTS.mkdir(parents=True, exist_ok=True)
PORT = 9556
USER_DIR = '/tmp/dp_monitor'

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

def main():
    print('=' * 55)
    print('BotMonitor 框架验证 (takeover 模式)')
    print('=' * 55, flush=True)

    subprocess.run(['pkill', '-9', '-f', 'remote-debugging-port=9556'], timeout=5)
    time.sleep(1)
    if Path(USER_DIR).exists():
        shutil.rmtree(USER_DIR, ignore_errors=True)
    cmd = ['google-chrome', '--headless=new', '--no-sandbox', '--disable-gpu',
           '--proxy-server=socks5://127.0.0.1:2080',
           f'--remote-debugging-port={PORT}', f'--user-data-dir={USER_DIR}', 'about:blank']
    print('启动 Chrome 9556(走代理)...', flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_port(PORT, 30):
            print('[!] Chrome 9556 未就绪', flush=True); return
        print('Chrome 就绪', flush=True)
        # 5.0.0b0 attach bug 修复:必须显式 .headless(True) 同步 _is_headless,否则 __init__ 触发 quit+reconnect 卡 30s
        from DrissionPage import ChromiumOptions
        b = Chromium(ChromiumOptions().set_address(f'127.0.0.1:{PORT}').headless(True))
        tab = b.latest_tab
        monitor = BotMonitor(tab)

        # 测试1: sannysoft 页面扫描
        print('\n--- 测试1: sannysoft 页面扫描 ---', flush=True)
        tab.get('https://bot.sannysoft.com', timeout=25)
        time.sleep(3)
        a1 = monitor.scan_page()
        print(f'告警数: {len(a1)}', flush=True)
        for a in a1: print(f'  {a}', flush=True)

        # 测试2: nowsecure 页面扫描
        print('\n--- 测试2: nowsecure 页面扫描 ---', flush=True)
        monitor.alerts = []
        tab.get('https://nowsecure.nl', timeout=25)
        time.sleep(4)
        a2 = monitor.scan_page()
        print(f'告警数: {len(a2)}', flush=True)
        for a in a2: print(f'  {a}', flush=True)

        # 测试3: 构造 403 响应监测(模拟封禁)
        print('\n--- 测试3: 构造 403 响应监测 ---', flush=True)
        monitor.alerts = []
        monitor.start_network_monitor()
        tab.get('https://httpbin.org/status/403', timeout=20)
        time.sleep(2)
        a3 = monitor.check_network(timeout=2)
        print(f'网络封禁告警数: {len(a3)}', flush=True)
        for a in a3: print(f'  {a}', flush=True)

        # 测试4: 构造 429(限流)
        print('\n--- 测试4: 构造 429 限流监测 ---', flush=True)
        monitor.alerts = []
        monitor.start_network_monitor()
        tab.get('https://httpbin.org/status/429', timeout=20)
        time.sleep(2)
        a4 = monitor.check_network(timeout=2)
        print(f'限流告警数: {len(a4)}', flush=True)
        for a in a4: print(f'  {a}', flush=True)

        # 存证
        monitor.save_alerts(label='monitor_run')
        print(f'\n汇总: {monitor.summary()}', flush=True)

        # 写 JSON 结果
        result = {'sannysoft_alerts': len(a1), 'nowsecure_alerts': len(a2),
                  'http403_alerts': len(a3), 'http429_alerts': len(a4),
                  'summary': monitor.summary(),
                  'all_alerts': [a.to_dict() for a in monitor.alerts]}
        (REPORT / 'monitor_result.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'-> {REPORT/"monitor_result.json"}', flush=True)
    except Exception as e:
        print(f'[!] {type(e).__name__}: {e}', flush=True)
        traceback.print_exc()
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except: proc.kill()

if __name__ == '__main__':
    main()
