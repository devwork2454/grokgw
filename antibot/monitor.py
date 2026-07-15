#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DrissionPage 封禁/验证码监测框架(C 任务)

功能:
1. 页面变化监测:检测是否出现验证码元素(g-recaptcha/h-captcha/cf-turnstile/iframe[captcha]等)
2. 网络响应监测:用 tab.listen 监听响应,标记 403/429/503 状态码、含封禁关键词的响应体
3. 行为触发:可选主动触发异常请求,测试监测是否生效
4. 告警存证:监测到异常时记录时间戳/URL/类型/截图到 report/alerts/

设计为可复用框架,核心类 BotMonitor 可挂到任意 tab。
用法见末尾 demo。
"""
import json
import os
import re
import time
from pathlib import Path

from DrissionPage import Chromium, ChromiumOptions

BASE = Path(__file__).parent
REPORT = BASE / 'report'
ALERTS = REPORT / 'alerts'
ALERTS.mkdir(parents=True, exist_ok=True)

# 本机网络修复:走本地 socks5 代理(VPN),直连会因 IPv6 不通卡死
BASE_ARGS = ['--no-sandbox','--disable-gpu','--proxy-server=socks5://127.0.0.1:2080']

# ===== 检测规则 =====

# 验证码/封禁相关的页面元素选择器
CAPTCHA_SELECTORS = [
    'iframe[src*="captcha"]',
    'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    'iframe[src*="turnstile"]',
    'iframe[src*="challenge"]',
    '.g-recaptcha',
    '.h-captcha',
    '#cf-challenge-running',
    '.cf-turnstile',
    '#challenge-form',
    '#challenge-running',
    'div[data-sitekey]',
    'img[src*="captcha"]',
]

# 页面文本中的封禁/验证关键词(中英)
BLOCK_KEYWORDS = [
    # 英文
    'unusual traffic', 'blocked', 'access denied', 'forbidden',
    'are you a robot', 'are you human', 'verify you are human',
    'captcha', 'challenge', 'automated queries', 'rate limit',
    'temporarily blocked', 'suspicious activity', 'bot detection',
    # 中文
    '验证', '人机验证', '操作过于频繁', '访问被拒绝', '请完成验证',
    '异常流量', '暂时无法访问', '安全验证', '滑动验证',
]

# 网络封禁状态码
BLOCK_STATUS_CODES = {403, 429, 503, 451}


class Alert:
    """一条告警记录"""
    def __init__(self, kind, url, detail, ts=None):
        self.kind = kind            # 'captcha_element' / 'block_keyword' / 'block_status'
        self.url = url
        self.detail = detail
        self.ts = ts or time.strftime('%Y-%m-%d %H:%M:%S')

    def to_dict(self):
        return {'kind': self.kind, 'url': self.url, 'detail': self.detail, 'ts': self.ts}

    def __str__(self):
        return f'[{self.ts}] {self.kind}: {self.url} | {self.detail}'


class BotMonitor:
    """挂到 tab 上的监测器"""

    def __init__(self, tab):
        self.tab = tab
        self.alerts = []
        self._listening = False

    # ---- 页面监测 ----
    def scan_page(self, url=None):
        """扫描当前页面的验证码元素和封禁关键词,返回告警列表"""
        new_alerts = []
        u = url or self.tab.url
        try:
            # 检测验证码元素
            for sel in CAPTCHA_SELECTORS:
                try:
                    found = self.tab.run_js(
                        f'return document.querySelectorAll({json.dumps(sel)}).length')
                    if found:
                        a = Alert('captcha_element', u, f'selector={sel} count={found}')
                        new_alerts.append(a)
                except Exception:
                    pass
            # 检测页面文本关键词
            try:
                txt = self.tab.run_js('return document.body ? document.body.innerText : ""') or ''
                lower = txt.lower()
                for kw in BLOCK_KEYWORDS:
                    if kw.lower() in lower:
                        a = Alert('block_keyword', u, f'keyword="{kw}"')
                        new_alerts.append(a)
                        break  # 一个关键词够了
            except Exception:
                pass
        except Exception as e:
            new_alerts.append(Alert('scan_error', u, f'{type(e).__name__}: {e}'))
        self.alerts.extend(new_alerts)
        return new_alerts

    # ---- 网络监测 ----
    def start_network_monitor(self, url_filter=None):
        """启动网络监听,捕获封禁状态码响应"""
        try:
            self.tab.listen.start(url_filter) if url_filter else self.tab.listen.start()
            self._listening = True
            print(f'[monitor] 网络监听已启动 filter={url_filter}', flush=True)
        except Exception as e:
            print(f'[monitor] 启动网络监听失败: {e}', flush=True)

    def check_network(self, timeout=0.5):
        """检查已监听到的网络包,标记封禁响应。返回新告警列表"""
        new_alerts = []
        if not self._listening:
            return new_alerts
        try:
            # 非阻塞拿包(用 steps 生成器,但只取当前已有的)
            for packet in self.tab.listen.steps(count=50, timeout=timeout, gap=0.1):
                u = getattr(packet, 'url', '')
                # 状态码
                resp = getattr(packet, 'response', None)
                status = getattr(resp, 'status', None) if resp else None
                if status in BLOCK_STATUS_CODES:
                    a = Alert('block_status', u, f'http={status}')
                    new_alerts.append(a)
                # 响应体关键词
                body = getattr(resp, 'body', None) if resp else None
                if body and isinstance(body, str):
                    lower = body.lower()
                    for kw in ['blocked','denied','captcha','forbidden','rate limit']:
                        if kw in lower:
                            a = Alert('block_keyword_in_body', u, f'keyword="{kw}"')
                            new_alerts.append(a)
                            break
        except Exception:
            pass
        self.alerts.extend(new_alerts)
        return new_alerts

    # ---- 告警存证 ----
    def save_alerts(self, label='monitor'):
        """保存所有告警 + 截图存证"""
        path = ALERTS / f'{label}_{int(time.time())}.json'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump([a.to_dict() for a in self.alerts], f, ensure_ascii=False, indent=2)
        # 截图存证
        try:
            shot = ALERTS / f'{label}_{int(time.time())}.png'
            self.tab.get_screenshot(path=str(shot), full_page=True)
        except Exception:
            pass
        print(f'[monitor] 告警已存: {path} (共 {len(self.alerts)} 条)', flush=True)
        return path

    @property
    def has_alert(self):
        return len(self.alerts) > 0

    def summary(self):
        return {'total': len(self.alerts),
                'by_kind': {k: sum(1 for a in self.alerts if a.kind == k)
                           for k in set(a.kind for a in self.alerts)}}


# ===== demo:在 nowsecure/sannysoft 上验证监测逻辑 =====

def demo():
    print('=' * 50)
    print('BotMonitor 框架验证')
    print('=' * 50, flush=True)

    co = ChromiumOptions().auto_port().headless()
    for a in BASE_ARGS:
        co.set_argument(a)
    co.set_timeouts(base=20, page_load=40)
    b = Chromium(co)
    tab = b.latest_tab

    monitor = BotMonitor(tab)

    # 测试1: sannysoft(应能扫到验证码相关元素?实际它只有检测表格,预期无告警或少量)
    print('\n--- 测试1: sannysoft 页面扫描 ---', flush=True)
    tab.get('https://bot.sannysoft.com', timeout=30)
    time.sleep(3)
    alerts = monitor.scan_page()
    print(f'告警数: {len(alerts)}', flush=True)
    for a in alerts:
        print(f'  {a}', flush=True)

    # 测试2: nowsecure(反自动化挑战页,可能触发)
    print('\n--- 测试2: nowsecure 页面扫描 ---', flush=True)
    monitor.alerts = []  # 重置
    tab.get('https://nowsecure.nl', timeout=30)
    time.sleep(4)
    alerts = monitor.scan_page()
    print(f'告警数: {len(alerts)}', flush=True)
    for a in alerts:
        print(f'  {a}', flush=True)

    # 测试3: 网络监测(监听 nowsecure 的请求,看有无封禁状态码)
    print('\n--- 测试3: 网络封禁状态码监测 ---', flush=True)
    monitor.start_network_monitor()
    # 触发一次导航产生请求
    tab.get('https://bot.sannysoft.com', timeout=30)
    time.sleep(3)
    net_alerts = monitor.check_network(timeout=2)
    print(f'网络封禁告警数: {len(net_alerts)}', flush=True)
    for a in net_alerts:
        print(f'  {a}', flush=True)

    # 测试4: 人为构造封禁场景(访问一个会返回 403 的 URL,验证监测器能识别)
    print('\n--- 测试4: 构造 403 响应监测(模拟封禁)---', flush=True)
    # 用 httpbin 的 status 端点制造 403
    monitor.alerts = []
    monitor.start_network_monitor()
    tab.get('https://httpbin.org/status/403', timeout=20)
    time.sleep(2)
    net_alerts = monitor.check_network(timeout=2)
    print(f'构造 403 告警数: {len(net_alerts)}', flush=True)
    for a in net_alerts:
        print(f'  {a}', flush=True)

    # 存证
    monitor.save_alerts(label='demo')
    print(f'\n汇总: {monitor.summary()}', flush=True)

    b.quit()
    print('done', flush=True)


if __name__ == '__main__':
    demo()
