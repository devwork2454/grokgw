#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""加固配置工厂(B 任务)
提供 build_hardened_extras():返回加固用启动参数列表。
被 run_detect.py 的 make_options(hardened=True) 调用。

加固策略:
1. 移除 'AutomationControlled' 痕迹(--disable-blink-features)
2. 用真实 UA 覆盖 HeadlessChrome 字样
3. 禁用自动化相关特性
4. 其余指纹修补在 stealth.js 里(add_init_js 注入)
"""
import os


def build_hardened_extras():
    """返回加固启动参数列表"""
    return [
        # 移除自动化控制特征(关键:禁用 Blink 的 AutomationControlled)
        '--disable-blink-features=AutomationControlled',
        # 禁用一些会暴露自动化的功能
        '--disable-features=IsolateOrigins,site-per-process',
        # 禁用 AutomationControlled 对应的 infobars
        '--disable-infobars',
        # 不显示"正受到自动化测试软件控制"提示
        '--exclude-switches=enable-automation',
        '--ignore-certificate-errors',
        # 伪装更真实的窗口尺寸(影响某些检测)
        '--window-size=1920,1080',
    ]


def build_hardened_user_agent():
    """返回一个真实(非 Headless)的 Chrome UA,Linux 桌面版"""
    # 与本机 Chrome 148 版本匹配,但去掉 HeadlessChrome
    return ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36')


def apply_hardening(co):
    """对一个 ChromiumOptions 对象应用加固(可选,直接用也可)"""
    for arg in build_hardened_extras():
        co.set_argument(arg)
    co.set_user_agent(build_hardened_user_agent())
    # 关闭凭据服务(降低自动化痕迹)
    co.set_pref('credentials_enable_service', False)
    return co


if __name__ == '__main__':
    print('加固参数:')
    for a in build_hardened_extras():
        print(' ', a)
    print('加固 UA:', build_hardened_user_agent())
