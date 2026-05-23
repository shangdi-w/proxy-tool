"""Windows 系统代理控制 - 注册表 + 环境变量，尽可能覆盖整机流量"""

import ctypes
import os
import subprocess
import winreg

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

# 常见的代理环境变量，curl / pip / npm / git 等工具都会读取
PROXY_ENV_VARS = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]


def _refresh():
    """通知系统代理设置有变化，使设置立即生效"""
    try:
        ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
        ctypes.windll.wininet.InternetSetOptionW(0, 37, 0, 0)
    except Exception:
        pass


def enable(proxy_addr: str = "127.0.0.1:5000"):
    """开启系统代理（注册表 + 用户环境变量）"""
    proxy_url = f"http://{proxy_addr}"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy_addr)
    _refresh()
    _set_env_vars(proxy_url)


def disable():
    """关闭系统代理（注册表 + 清除环境变量）"""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
    _refresh()
    _clear_env_vars()


def _set_env_vars(proxy_url: str):
    """把 HTTP_PROXY / HTTPS_PROXY 写入用户环境变量"""
    for name in PROXY_ENV_VARS:
        try:
            subprocess.run(["setx", name, proxy_url], capture_output=True, timeout=5)
        except Exception:
            pass
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url


def _clear_env_vars():
    """清除用户环境变量中的代理设置"""
    for name in PROXY_ENV_VARS:
        try:
            subprocess.run(["setx", name, ""], capture_output=True, timeout=5)
        except Exception:
            pass
    for name in PROXY_ENV_VARS:
        os.environ.pop(name, None)


def status() -> dict:
    """读取当前系统代理状态"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ) as key:
            enabled = bool(winreg.QueryValueEx(key, "ProxyEnable")[0])
            server = ""
            try:
                server = winreg.QueryValueEx(key, "ProxyServer")[0] or ""
            except Exception:
                pass
            return {"enabled": enabled, "server": server}
    except Exception:
        return {"enabled": False, "server": ""}
