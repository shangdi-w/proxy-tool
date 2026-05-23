"""代理验证模块 - 检测代理可用性、延迟和国家"""

import asyncio
import time
import ssl
from concurrent.futures import ThreadPoolExecutor
import aiohttp
from .models import Proxy

# HTTP/HTTPS 代理用 httpbin 测试；SOCKS 代理也走 httpbin（通过端口转发）
TEST_URLS = {
    "http": "http://httpbin.org/ip",
    "https": "https://httpbin.org/ip",
    "socks4": "http://httpbin.org/ip",
    "socks5": "http://httpbin.org/ip",
}

DEFAULT_TIMEOUT = 10         # 默认超时(秒)
MAX_CONCURRENT = 50          # 最大并发验证数
IP_API_CACHE: dict[str, str] = {}  # IP→国家代码缓存


def _test_connect_support(proxy: Proxy, timeout: int = 8) -> bool:
    """测试代理是否支持 CONNECT 隧道（HTTPS）"""
    try:
        import socket
        s = socket.create_connection((proxy.ip, proxy.port), timeout=timeout)
        s.sendall(b'CONNECT httpbin.org:443 HTTP/1.1\r\nHost: httpbin.org:443\r\n\r\n')
        s.settimeout(timeout)
        resp = s.recv(4096)
        s.close()
        return b'200' in resp.split(b'\r\n')[0]
    except Exception:
        return False


def _validate_socks(proxy: Proxy, timeout: int = DEFAULT_TIMEOUT) -> Proxy:
    """通过 requests[socks] 同步验证 SOCKS 代理（在线程池中运行）"""
    import requests
    t0 = time.time()
    try:
        resp = requests.get(
            "http://httpbin.org/ip",
            proxies={"http": proxy.socks_url, "https": proxy.socks_url},
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if resp.status_code == 200:
            proxy.latency = round((time.time() - t0) * 1000, 1)
            proxy.status = "alive"
            proxy.fail_count = 0
            # 尝试从响应IP反查国家
            origin = resp.json().get("origin", "")
            if origin:
                proxy.country = proxy.country or _get_country_from_ip(origin.split(",")[0].strip())
            # SOCKS 天然支持 CONNECT 隧道
            proxy.supports_connect = True
        else:
            proxy.status = "dead"
            proxy.fail_count += 1
    except Exception:
        proxy.status = "dead"
        proxy.fail_count += 1
        proxy.latency = -1
    proxy.last_checked = time.time()
    return proxy


def _get_country_from_ip(ip: str) -> str:
    """通过 ip-api.com 查询IP所属国家代码"""
    if ip in IP_API_CACHE:
        return IP_API_CACHE[ip]
    try:
        import requests
        resp = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=5)
        if resp.status_code == 200:
            code = resp.json().get("countryCode", "")
            IP_API_CACHE[ip] = code
            return code
    except Exception:
        pass
    return ""


async def _validate_http(proxy: Proxy, session: aiohttp.ClientSession, timeout: int = DEFAULT_TIMEOUT) -> Proxy:
    """通过 aiohttp 异步验证 HTTP/HTTPS 代理"""
    test_url = TEST_URLS.get(proxy.protocol, "http://httpbin.org/ip")
    t0 = time.time()
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as temp_session:
            async with temp_session.get(
                test_url,
                proxy=proxy.url,
                ssl=ssl_ctx if proxy.protocol == "https" else None,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    proxy.latency = round((time.time() - t0) * 1000, 1)
                    proxy.status = "alive"
                    proxy.fail_count = 0
                    origin = data.get("origin", "")
                    if origin and not proxy.country:
                        proxy.country = await _get_country_async(origin.split(",")[0].strip(), session)
                    # 检测 CONNECT 支持
                    proxy.supports_connect = _test_connect_support(proxy)
                else:
                    proxy.status = "dead"
                    proxy.fail_count += 1
    except Exception:
        proxy.status = "dead"
        proxy.fail_count += 1
        proxy.latency = -1
    proxy.last_checked = time.time()
    return proxy


async def _get_country_async(ip: str, session: aiohttp.ClientSession) -> str:
    """异步查询IP国家代码"""
    if ip in IP_API_CACHE:
        return IP_API_CACHE[ip]
    try:
        async with session.get(
            f"http://ip-api.com/json/{ip}?fields=countryCode",
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                code = data.get("countryCode", "")
                IP_API_CACHE[ip] = code
                return code
    except Exception:
        pass
    return ""


def _verify_anonymity(proxy: Proxy, timeout: int = 10) -> str:
    """深度验证代理匿名度。通过代理请求 httpbin.org/headers，
    检测是否泄露真实IP或代理身份。返回 elite/anonymous/transparent。"""
    import requests
    try:
        resp = requests.get(
            "http://httpbin.org/headers",
            proxies={"http": proxy.url, "https": proxy.url},
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if resp.status_code == 200:
            headers = {k.lower(): v for k, v in resp.json().get("headers", {}).items()}
            # 泄露真实 IP 的头部
            real_ip_headers = {"x-forwarded-for", "x-real-ip", "x-client-ip", "forwarded",
                               "x-cluster-client-ip", "true-client-ip"}
            # 暴露代理身份的头部
            proxy_headers = {"via", "proxy-connection", "x-proxy-id", "x-bluecoat-via",
                             "cache-control", "x-forwarded", "x-proxyuser-ip"}
            found = [h for h in set(list(real_ip_headers) + list(proxy_headers)) if h in headers]
            if real_ip_headers & set(found):
                return "transparent"
            if found:
                return "anonymous"
            return "elite"
    except Exception:
        pass
    return ""  # 无法判断时返回空，保持原值


async def validate_batch(proxies: list[Proxy], timeout: int = DEFAULT_TIMEOUT,
                         max_concurrent: int = MAX_CONCURRENT) -> list[Proxy]:
    """批量并发验证代理列表，返回验证后的代理"""
    semaphore = asyncio.Semaphore(max_concurrent)
    validated = []

    async def _validate_one(proxy: Proxy) -> Proxy:
        async with semaphore:
            if proxy.protocol in ("socks4", "socks5"):
                # SOCKS走同步路径，放入线程池避免阻塞事件循环
                loop = asyncio.get_running_loop()
                with ThreadPoolExecutor(max_workers=1) as pool:
                    return await loop.run_in_executor(pool, _validate_socks, proxy, timeout)
            else:
                async with aiohttp.ClientSession() as session:
                    return await _validate_http(proxy, session, timeout)

    tasks = [_validate_one(p) for p in proxies]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Proxy):
            validated.append(r)
    return validated
