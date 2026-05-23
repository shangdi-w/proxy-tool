"""代理抓取模块 - 从多个免费公开源异步抓取代理列表"""

import asyncio
import json
import re
import aiohttp
from bs4 import BeautifulSoup
from .models import Proxy

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}


async def _fetch(session: aiohttp.ClientSession, url: str, timeout: int = 15) -> str:
    """通用异步HTTP获取，失败返回空字符串"""
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            return await resp.text()
    except Exception:
        return ""


async def _scrape_proxyscrape(session: aiohttp.ClientSession) -> list[Proxy]:
    """从 ProxyScrape API v2 抓取（支持 http/socks4/socks5）"""
    proxies = []
    for protocol in ["http", "socks4", "socks5"]:
        url = f"https://api.proxyscrape.com/v2/?request=getproxies&protocol={protocol}&timeout=10000&country=all&ssl=all&anonymity=all"
        text = await _fetch(session, url)
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    proxies.append(Proxy(
                        ip=parts[0], port=int(parts[1]), protocol=protocol,
                        source="proxyscrape"
                    ))
    return proxies


async def _scrape_geonode(session: aiohttp.ClientSession) -> list[Proxy]:
    """从 GeoNode 免费代理列表API抓取（含国家、延迟、匿名度等详细信息）"""
    proxies = []
    for page in [1, 2, 3, 4, 5]:
        url = f"https://proxylist.geonode.com/api/proxy-list?limit=500&page={page}&sort_by=lastChecked&sort_type=desc"
        text = await _fetch(session, url)
        if not text:
            continue
        try:
            data = json.loads(text)
        except Exception:
            continue
        for item in data.get("data", []):
            for proto in item.get("protocols", []):
                proxies.append(Proxy(
                    ip=item.get("ip", ""), port=int(item.get("port", 0)),
                    protocol=proto.lower(),
                    country=item.get("country", "").upper(),
                    anonymity=item.get("anonymityLevel", "unknown").lower(),
                    latency=float(item.get("responseTime", -1)),
                    source="geonode",
                ))
    return proxies


async def _scrape_free_proxy_list(session: aiohttp.ClientSession) -> list[Proxy]:
    """从 free-proxy-list.net 网页表格抓取"""
    text = await _fetch(session, "https://free-proxy-list.net/")
    if not text:
        return []
    soup = BeautifulSoup(text, "html.parser")
    table = soup.find("table", class_="table-striped")
    if not table:
        return []
    proxies = []
    rows = table.find_all("tr")[1:]  # 跳过表头
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 8:
            continue
        try:
            ip = cols[0].text.strip()
            port = int(cols[1].text.strip())
            country = cols[3].text.strip()
            anonymity = cols[4].text.strip().lower()
            https = cols[6].text.strip().lower()
            protocol = "https" if https == "yes" else "http"
            proxies.append(Proxy(
                ip=ip, port=port, protocol=protocol,
                country=country, anonymity=anonymity,
                source="free-proxy-list",
            ))
        except (ValueError, IndexError):
            continue
    return proxies


async def _scrape_proxy_list_download(session: aiohttp.ClientSession) -> list[Proxy]:
    """从 proxy-list.download API 抓取"""
    proxies = []
    for proto in ["http", "https", "socks4", "socks5"]:
        url = f"https://www.proxy-list.download/api/v1/get?type={proto}"
        text = await _fetch(session, url)
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    proxies.append(Proxy(
                        ip=parts[0], port=int(parts[1]), protocol=proto,
                        source="proxy-list.download",
                    ))
    return proxies


# ══════════════════════════════════════════
# 国内渗透测试专用代理源
# ══════════════════════════════════════════

async def _scrape_kuaidaili(session: aiohttp.ClientSession) -> list[Proxy]:
    """快代理免费代理列表 — 国内HTTP/HTTPS代理"""
    proxies = []
    for page in [1, 2]:
        url = f"https://www.kuaidaili.com/free/inha/{page}/"
        text = await _fetch(session, url)
        if not text:
            continue
        soup = BeautifulSoup(text, "html.parser")
        table = soup.find("table")
        if not table:
            continue
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) < 7:
                continue
            try:
                ip = cols[0].text.strip()
                port = int(cols[1].text.strip())
                anonymity = cols[2].text.strip()
                proto = cols[3].text.strip().lower()
                if proto not in ("http", "https"):
                    proto = "http"
                proxies.append(Proxy(
                    ip=ip, port=port, protocol=proto,
                    country="CN", anonymity="elite" if "高匿" in anonymity else "anonymous",
                    source="kuaidaili",
                ))
            except (ValueError, IndexError):
                continue
    return proxies


async def _scrape_89ip(session: aiohttp.ClientSession) -> list[Proxy]:
    """89免费代理 — 国内代理"""
    proxies = []
    for page in [1, 2]:
        url = f"https://www.89ip.cn/index_{page}.html" if page > 1 else "https://www.89ip.cn/"
        text = await _fetch(session, url)
        if not text:
            continue
        # 89ip 的数据在 <div class="layui-form"> 的 table 中
        soup = BeautifulSoup(text, "html.parser")
        for row in soup.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) < 5:
                continue
            try:
                ip = cols[0].text.strip()
                port = int(cols[1].text.strip())
                location = cols[2].text.strip() if len(cols) > 2 else ""
                # 判断是否国内
                country = "CN" if any(kw in location for kw in ["中国", "北京", "上海", "广东", "浙江", "江苏", "四川", "湖北", "湖南", "福建", "山东", "河南", "河北", "辽宁", "陕西", "重庆", "天津"]) else ""
                proxies.append(Proxy(
                    ip=ip, port=port, protocol="http",
                    country=country, anonymity="anonymous",
                    source="89ip",
                ))
            except (ValueError, IndexError):
                continue
    return proxies


async def _scrape_ihuan(session: aiohttp.ClientSession) -> list[Proxy]:
    """小幻代理API — 国内HTTP/HTTPS/SOCKS代理"""
    proxies = []
    urls = [
        "https://ip.ihuan.me/tqdl.html?type=http",
        "https://ip.ihuan.me/tqdl.html?type=https",
        "https://ip.ihuan.me/tqdl.html?type=socks5",
    ]
    for url in urls:
        text = await _fetch(session, url)
        if not text:
            continue
        # 页面包含 IP:端口 格式的文本，用正则提取
        pattern = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{2,5})'
        matches = re.findall(pattern, text)
        proto = "http"
        if "socks5" in url:
            proto = "socks5"
        elif "https" in url:
            proto = "https"
        for ip, port in matches:
            proxies.append(Proxy(
                ip=ip, port=int(port), protocol=proto,
                country="CN", source="ihuan",
            ))
    return proxies


async def _scrape_github_proxy_list(session: aiohttp.ClientSession) -> list[Proxy]:
    """GitHub 上的代理列表 — TheSpeedX/PROXY-List（含大量 SOCKS）"""
    proxies = []
    urls = [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    ]
    for url in urls:
        text = await _fetch(session, url)
        if not text:
            continue
        proto = "http"
        if "socks4" in url:
            proto = "socks4"
        elif "socks5" in url:
            proto = "socks5"
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        proxies.append(Proxy(
                            ip=parts[0], port=int(parts[1]),
                            protocol=proto, source="github-speedx",
                        ))
                    except ValueError:
                        continue
    return proxies


async def _scrape_openproxy(session: aiohttp.ClientSession) -> list[Proxy]:
    """OpenProxy.space API — 含国家标记的代理列表"""
    proxies = []
    url = "https://api.openproxy.space/lists/http"
    text = await _fetch(session, url)
    if not text:
        return proxies
    try:
        data = json.loads(text)
        for item in data[:200]:
            proxies.append(Proxy(
                ip=item.get("ip", ""), port=int(item.get("port", 0)),
                protocol=item.get("type", "http").lower(),
                country=item.get("code", "").upper(),
                anonymity=item.get("anonymity", "unknown").lower(),
                latency=float(item.get("speed", -1)),
                source="openproxy",
            ))
    except Exception:
        pass
    return proxies


async def _scrape_cn_proxy_list(session: aiohttp.ClientSession) -> list[Proxy]:
    """国内代理聚合 — 从 proxypool 相关源抓取"""
    proxies = []
    # fate0 proxylist (GitHub)
    url = "https://raw.githubusercontent.com/fate0/proxylist/master/proxy.list"
    text = await _fetch(session, url)
    if text:
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                country = item.get("country", "").upper()
                # 优先保留中国和亚洲代理
                proxies.append(Proxy(
                    ip=item.get("host", ""), port=int(item.get("port", 0)),
                    protocol=item.get("type", "http").lower(),
                    country=country,
                    anonymity=item.get("anonymity", "unknown").lower(),
                    source="fate0",
                ))
            except Exception:
                continue
    return proxies


# ══════════════════════════════════════════
# 扩展代理源 — GitHub仓库 / API / 网页
# ══════════════════════════════════════════

async def _scrape_proxyscrape_https(session: aiohttp.ClientSession) -> list[Proxy]:
    """ProxyScrape HTTPS 协议（补充已有 HTTP/SOCKS 爬取）"""
    proxies = []
    url = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=https&timeout=10000&country=all&ssl=all&anonymity=all"
    text = await _fetch(session, url)
    for line in text.strip().split("\n"):
        line = line.strip()
        if ":" in line and len(line) < 30:
            parts = line.split(":")
            if len(parts) == 2:
                try:
                    proxies.append(Proxy(
                        ip=parts[0], port=int(parts[1]), protocol="https",
                        source="proxyscrape",
                    ))
                except ValueError:
                    continue
    return proxies


async def _scrape_aliilapro(session: aiohttp.ClientSession) -> list[Proxy]:
    """ALIILAPRO/Proxy — GitHub 大量代理列表"""
    proxies = []
    urls = [
        ("https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/http.txt", "http"),
        ("https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/https.txt", "https"),
        ("https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/socks4.txt", "socks4"),
        ("https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/socks5.txt", "socks5"),
    ]
    for url, proto in urls:
        text = await _fetch(session, url)
        if not text:
            continue
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        proxies.append(Proxy(
                            ip=parts[0], port=int(parts[1]),
                            protocol=proto, source="aliilapro",
                        ))
                    except ValueError:
                        continue
    return proxies


async def _scrape_monosans(session: aiohttp.ClientSession) -> list[Proxy]:
    """monosans/proxy-list — JSON 格式，含地理信息和匿名度"""
    proxies = []
    urls = [
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies.json",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_anonymous.json",
    ]
    for url in urls:
        text = await _fetch(session, url)
        if not text:
            continue
        try:
            data = json.loads(text)
            for item in data:
                host = item.get("host", "")
                port = item.get("port", 0)
                if not host or not port or ":" in host:
                    continue
                proto = item.get("type", "http").lower()
                if proto not in ("http", "https", "socks4", "socks5"):
                    proto = "http"
                country = ""
                geo = item.get("geolocation", {})
                if isinstance(geo, dict):
                    country = geo.get("country", {}).get("iso_code", "").upper() if isinstance(geo.get("country"), dict) else ""
                anonymity = item.get("anonymity", "unknown").lower()
                proxies.append(Proxy(
                    ip=host, port=int(port), protocol=proto,
                    country=country, anonymity=anonymity,
                    source="monosans",
                ))
        except Exception:
            continue
    return proxies


async def _scrape_roosterkid(session: aiohttp.ClientSession) -> list[Proxy]:
    """roosterkid/openproxylist — HTTPS/SOCKS4/SOCKS5 代理"""
    proxies = []
    urls = [
        ("https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS.txt", "https"),
        ("https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4.txt", "socks4"),
        ("https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5.txt", "socks5"),
    ]
    for url, proto in urls:
        text = await _fetch(session, url)
        if not text:
            continue
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        proxies.append(Proxy(
                            ip=parts[0], port=int(parts[1]),
                            protocol=proto, source="roosterkid",
                        ))
                    except ValueError:
                        continue
    return proxies


async def _scrape_hookzof(session: aiohttp.ClientSession) -> list[Proxy]:
    """hookzof/socks5_list — SOCKS5 专项代理"""
    proxies = []
    url = "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt"
    text = await _fetch(session, url)
    if not text:
        return proxies
    for line in text.strip().split("\n"):
        line = line.strip()
        if ":" in line and len(line) < 30:
            parts = line.split(":")
            if len(parts) == 2:
                try:
                    proxies.append(Proxy(
                        ip=parts[0], port=int(parts[1]),
                        protocol="socks5", source="hookzof",
                    ))
                except ValueError:
                    continue
    return proxies


async def _scrape_speedx_socks(session: aiohttp.ClientSession) -> list[Proxy]:
    """TheSpeedX/SOCKS-List — SOCKS 专用（不同于 PROXY-List）"""
    proxies = []
    urls = [
        ("https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt", "socks4"),
        ("https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt", "socks5"),
        ("https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt", "http"),
    ]
    for url, proto in urls:
        text = await _fetch(session, url)
        if not text:
            continue
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        proxies.append(Proxy(
                            ip=parts[0], port=int(parts[1]),
                            protocol=proto, source="speedx-socks",
                        ))
                    except ValueError:
                        continue
    return proxies


async def _scrape_jetkai(session: aiohttp.ClientSession) -> list[Proxy]:
    """jetkai/proxy-list — 在线代理 TXT 列表"""
    proxies = []
    urls = [
        ("https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies.txt", ""),
        ("https://raw.githubusercontent.com/jetkai/proxy-list/main/archive/txt/proxies.txt", ""),
    ]
    for url, _ in urls:
        text = await _fetch(session, url)
        if not text:
            continue
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        # jetkai 格式: protocol://ip:port 或 ip:port
                        ip_port = parts[0] + ":" + parts[1]
                        proto = "http"
                        if "://" in line:
                            proto = line.split("://")[0]
                            if proto not in ("http", "https", "socks4", "socks5"):
                                proto = "http"
                        proxies.append(Proxy(
                            ip=parts[0].split("://")[-1] if "://" in parts[0] else parts[0],
                            port=int(parts[1]), protocol=proto,
                            source="jetkai",
                        ))
                    except (ValueError, IndexError):
                        continue
    return proxies


async def _scrape_sunny9577(session: aiohttp.ClientSession) -> list[Proxy]:
    """sunny9577/proxy-scraper — 多协议代理"""
    proxies = []
    url = "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt"
    text = await _fetch(session, url)
    if not text:
        return proxies
    for line in text.strip().split("\n"):
        line = line.strip()
        if ":" in line and len(line) < 35:
            # 格式可能是 protocol://ip:port 或 ip:port
            proto = "http"
            addr = line
            if "://" in line:
                parts_scheme = line.split("://", 1)
                proto = parts_scheme[0]
                addr = parts_scheme[1]
                if proto not in ("http", "https", "socks4", "socks5"):
                    proto = "http"
            parts = addr.split(":")
            if len(parts) == 2:
                try:
                    proxies.append(Proxy(
                        ip=parts[0], port=int(parts[1]),
                        protocol=proto, source="sunny9577",
                    ))
                except ValueError:
                    continue
    return proxies


async def _scrape_mmpx12(session: aiohttp.ClientSession) -> list[Proxy]:
    """mmpx12/proxy-list — HTTP/HTTPS/SOCKS4/SOCKS5 分类"""
    proxies = []
    urls = [
        ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/HTTP.txt", "http"),
        ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/HTTPS.txt", "https"),
        ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/SOCKS4.txt", "socks4"),
        ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/SOCKS5.txt", "socks5"),
    ]
    for url, proto in urls:
        text = await _fetch(session, url)
        if not text:
            continue
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        proxies.append(Proxy(
                            ip=parts[0], port=int(parts[1]),
                            protocol=proto, source="mmpx12",
                        ))
                    except ValueError:
                        continue
    return proxies


async def _scrape_pubproxy(session: aiohttp.ClientSession) -> list[Proxy]:
    """PubProxy.com API — 免费 JSON 代理接口"""
    proxies = []
    for proto in ["http", "socks4", "socks5"]:
        for _ in range(2):
            url = f"http://pubproxy.com/api/proxy?format=json&type={proto}&limit=20&last_check=1440&speed=10000&level=anonymous&level=elite"
            text = await _fetch(session, url, timeout=20)
            if not text:
                continue
            try:
                data = json.loads(text)
                for item in data.get("data", []):
                    proxies.append(Proxy(
                        ip=item.get("ip", ""),
                        port=int(item.get("port", 0)),
                        protocol=item.get("type", proto).lower(),
                        country=item.get("country", "").upper(),
                        source="pubproxy",
                    ))
            except Exception:
                continue
    return proxies


async def _scrape_proxifly(session: aiohttp.ClientSession) -> list[Proxy]:
    """proxifly.dev — 最新免费代理 API"""
    proxies = []
    for _ in range(5):
        url = "https://proxifly.dev/api/proxy/latest"
        text = await _fetch(session, url, timeout=15)
        if not text:
            continue
        try:
            data = json.loads(text)
            item = data if isinstance(data, dict) else {}
            ip = item.get("ip", "") or item.get("proxy", "")
            if ip and ":" in ip:
                parts = ip.split(":")
                if len(parts) == 2:
                    proxies.append(Proxy(
                        ip=parts[0], port=int(parts[1]),
                        protocol=item.get("protocol", "http").lower(),
                        country=item.get("country", "").upper(),
                        latency=float(item.get("speed", -1)),
                        source="proxifly",
                    ))
        except Exception:
            continue
    return proxies


async def _scrape_muhamed(session: aiohttp.ClientSession) -> list[Proxy]:
    """muhamed77/Proxy-List — GitHub 多协议代理"""
    proxies = []
    urls = [
        ("https://raw.githubusercontent.com/muhamed77/Proxy-List/main/http.txt", "http"),
        ("https://raw.githubusercontent.com/muhamed77/Proxy-List/main/https.txt", "https"),
        ("https://raw.githubusercontent.com/muhamed77/Proxy-List/main/socks4.txt", "socks4"),
        ("https://raw.githubusercontent.com/muhamed77/Proxy-List/main/socks5.txt", "socks5"),
    ]
    for url, proto in urls:
        text = await _fetch(session, url)
        if not text:
            continue
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        proxies.append(Proxy(
                            ip=parts[0], port=int(parts[1]),
                            protocol=proto, source="muhamed77",
                        ))
                    except ValueError:
                        continue
    return proxies


async def _scrape_clarketm(session: aiohttp.ClientSession) -> list[Proxy]:
    """clarketm/proxy-list — 精选代理列表"""
    proxies = []
    urls = [
        ("https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt", ""),
    ]
    for url, _ in urls:
        text = await _fetch(session, url)
        if not text:
            continue
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        proxies.append(Proxy(
                            ip=parts[0], port=int(parts[1]),
                            protocol="http", source="clarketm",
                        ))
                    except ValueError:
                        continue
    return proxies


async def _scrape_hyperproxy(session: aiohttp.ClientSession) -> list[Proxy]:
    """hyperreality/proxy-list — GitHub 代理"""
    proxies = []
    url = "https://raw.githubusercontent.com/hyperreality/proxy-list/master/proxy-list.txt"
    text = await _fetch(session, url)
    if not text:
        return proxies
    for line in text.strip().split("\n"):
        line = line.strip()
        if ":" in line and len(line) < 30:
            parts = line.split(":")
            if len(parts) == 2:
                try:
                    proxies.append(Proxy(
                        ip=parts[0], port=int(parts[1]),
                        protocol="http", source="hyperreality",
                    ))
                except ValueError:
                    continue
    return proxies


async def _scrape_themiralay(session: aiohttp.ClientSession) -> list[Proxy]:
    """themiralay/Proxy-List — SOCKS/HTTP 代理"""
    proxies = []
    urls = [
        ("https://raw.githubusercontent.com/themiralay/Proxy-List/main/http.txt", "http"),
        ("https://raw.githubusercontent.com/themiralay/Proxy-List/main/socks4.txt", "socks4"),
        ("https://raw.githubusercontent.com/themiralay/Proxy-List/main/socks5.txt", "socks5"),
    ]
    for url, proto in urls:
        text = await _fetch(session, url)
        if not text:
            continue
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        proxies.append(Proxy(
                            ip=parts[0], port=int(parts[1]),
                            protocol=proto, source="themiralay",
                        ))
                    except ValueError:
                        continue
    return proxies


async def _scrape_proxyscrape_v2_all(session: aiohttp.ClientSession) -> list[Proxy]:
    """ProxyScrape v2 — 全量抓取 (anonymity=all, ssl=all)"""
    proxies = []
    for protocol in ["http", "https", "socks4", "socks5"]:
        url = f"https://api.proxyscrape.com/v2/?request=displayproxies&protocol={protocol}&timeout=10000&country=all&ssl=all&anonymity=all"
        text = await _fetch(session, url)
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line and len(line) < 30:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        proxies.append(Proxy(
                            ip=parts[0], port=int(parts[1]), protocol=protocol,
                            source="proxyscrape",
                        ))
                    except ValueError:
                        continue
    return proxies


# 所有抓取源（通用 + 国内渗透专用）
SCRAPERS = [
    _scrape_proxyscrape,
    _scrape_proxyscrape_https,
    _scrape_geonode,
    _scrape_free_proxy_list,
    _scrape_proxy_list_download,
    _scrape_github_proxy_list,
    _scrape_openproxy,
    _scrape_speedx_socks,
    _scrape_aliilapro,
    _scrape_monosans,
    _scrape_roosterkid,
    _scrape_hookzof,
    _scrape_jetkai,
    _scrape_sunny9577,
    _scrape_mmpx12,
    _scrape_pubproxy,
    _scrape_proxifly,
    _scrape_muhamed,
    _scrape_clarketm,
    _scrape_hyperproxy,
    _scrape_themiralay,
]

# 国内渗透测试专用抓取源
CN_SCRAPERS = [
    _scrape_kuaidaili,
    _scrape_89ip,
    _scrape_ihuan,
    _scrape_cn_proxy_list,
]


async def scrape_all(session: aiohttp.ClientSession = None) -> list[Proxy]:
    """运行所有抓取器，返回去重后的代理列表"""
    if session is None:
        async with aiohttp.ClientSession() as session:
            return await _scrape_internal(session)
    return await _scrape_internal(session)


async def _scrape_internal(session: aiohttp.ClientSession) -> list[Proxy]:
    """内部抓取逻辑：并发执行所有抓取器并去重"""
    all_scrapers = SCRAPERS + CN_SCRAPERS
    results = await asyncio.gather(
        *[scraper(session) for scraper in all_scrapers],
        return_exceptions=True
    )
    all_proxies = []
    for r in results:
        if isinstance(r, list):
            all_proxies.extend(r)

    # 按 (ip, port, protocol) 去重
    seen = set()
    unique = []
    for p in all_proxies:
        key = (p.ip, p.port, p.protocol)
        if key not in seen and p.port > 0:
            seen.add(key)
            unique.append(p)
    return unique
