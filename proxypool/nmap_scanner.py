"""Nmap 代理发现 - 扫描 IP 段中的常见代理端口"""

import asyncio
import subprocess
import xml.etree.ElementTree as ET
import tempfile
import os
import re
import random
import ipaddress
import aiohttp
from .models import Proxy

# 常见代理端口
PROXY_PORTS = [1080, 3128, 8080, 8081, 8118, 8888, 9000, 9999, 9050, 3129, 8000, 8889, 8089, 3127]

# 一键扫描用：常见VPS/云服务商 CIDR（取小段，避免扫描量过大）
QUICK_SCAN_CIDRS = [
    # DigitalOcean
    "143.110.128.0/20", "159.65.0.0/18", "167.71.0.0/17",
    # Vultr
    "45.77.0.0/18", "104.238.128.0/18", "149.28.0.0/17",
    # Linode
    "45.33.0.0/18", "45.79.0.0/18", "192.53.160.0/19",
    # AWS us-east
    "44.192.0.0/20", "3.80.0.0/18",
    # Google Cloud
    "34.75.0.0/18", "35.185.0.0/18",
    # OVH
    "51.68.0.0/17", "54.36.0.0/18",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def find_nmap() -> str | None:
    """查找 nmap 可执行文件路径（优先使用项目内置版本）"""
    # 项目内置 nmap（最高优先）
    _here = os.path.dirname(os.path.abspath(__file__))
    _bundled = os.path.join(_here, "nmap", "nmap.exe")
    if os.path.exists(_bundled):
        return _bundled
    # 系统安装路径
    for path in [
        r"C:\Program Files (x86)\Nmap\nmap.exe",
        r"C:\Program Files\Nmap\nmap.exe",
        r"E:\tools\saomiao\nmap\nmap.exe",
        "nmap",
    ]:
        try:
            subprocess.run([path, "--version"], capture_output=True, timeout=5)
            return path
        except Exception:
            continue
    return None


def _random_ips_from_cidrs(cidrs: list[str], count: int = 200) -> str:
    """从CIDR列表中随机选取 count 个IP，返回 nmap 可用的目标字符串"""
    all_ips = []
    for cidr in cidrs:
        net = ipaddress.ip_network(cidr, strict=False)
        # 每个CIDR取少量随机IP
        sample_size = min(count // len(cidrs) + 1, max(1, net.num_addresses // 256))
        for _ in range(sample_size):
            rand_int = random.randint(0, min(net.num_addresses - 1, 2**16 - 1))
            all_ips.append(str(net[rand_int]))
    # 去重并限制总数
    all_ips = list(set(all_ips))[:count]
    return " ".join(all_ips)


def scan_ports(targets: str, ports: list[int] = None,
               rate: int = 3000, timeout_sec: int = 120) -> list[dict]:
    """使用 nmap 扫描指定目标的代理端口，返回开放端口列表"""
    nmap_path = find_nmap()
    if not nmap_path:
        print("[NmapScanner] nmap 未找到，请安装: https://nmap.org/download.html")
        return []

    ports = ports or PROXY_PORTS
    port_str = ",".join(str(p) for p in ports)

    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name

    try:
        cmd = [
            nmap_path, "-sS", "-p", port_str,
            "--min-rate", str(rate),
            "--max-retries", "1",
            "--host-timeout", f"{timeout_sec}s",
            "-oX", xml_path,
            targets
        ]
        subprocess.run(cmd, capture_output=True, timeout=timeout_sec + 30)

        if not os.path.exists(xml_path) or os.path.getsize(xml_path) == 0:
            return []

        tree = ET.parse(xml_path)
        root = tree.getroot()
        results = []

        for host in root.findall("host"):
            addr_elem = host.find("address")
            if addr_elem is None:
                continue
            ip = addr_elem.get("addr", "")
            for port_elem in host.findall(".//port"):
                state_elem = port_elem.find("state")
                if state_elem is None:
                    continue
                if state_elem.get("state") != "open":
                    continue
                port = int(port_elem.get("portid", 0))
                service_elem = port_elem.find("service")
                service = service_elem.get("name", "") if service_elem is not None else ""
                results.append({
                    "ip": ip, "port": port,
                    "service": service,
                })

        return results
    except Exception as e:
        print(f"[NmapScanner] 扫描异常: {e}")
        return []
    finally:
        try:
            os.unlink(xml_path)
        except Exception:
            pass


async def _test_proxy(session: aiohttp.ClientSession, ip: str, port: int,
                      protocol: str, timeout: int = 10) -> Proxy | None:
    """测试某个端口是否为代理（HTTP CONNECT 或 SOCKS）"""
    test_url = "http://httpbin.org/ip"
    proxy_url = f"{protocol}://{ip}:{port}"

    try:
        async with session.get(
            test_url, proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            if resp.status == 200:
                text = await resp.text()
                if ip in text or "origin" in text:
                    return Proxy(
                        ip=ip, port=port, protocol=protocol,
                        source="nmap", status="alive",
                    )
    except Exception:
        pass
    return None


async def discover_proxies(targets: str, ports: list[int] = None,
                           rate: int = 3000) -> list[Proxy]:
    """扫描目标 IP 段，发现并验证代理服务，返回可用代理列表"""
    open_ports = scan_ports(targets, ports=ports, rate=rate)

    if not open_ports:
        return []

    # 按端口猜测协议类型
    socks_ports = {1080, 9050}
    # 并发测试每个发现的端口
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = []
        for item in open_ports:
            proto = "socks5" if item["port"] in socks_ports else "http"
            tasks.append(_test_proxy(session, item["ip"], item["port"], proto))
        results = await asyncio.gather(*tasks, return_exceptions=True)

    proxies = [r for r in results if isinstance(r, Proxy)]
    return proxies


async def quick_scan(ip_count: int = 200, rate: int = 3000,
                     ports: list[int] = None) -> list[Proxy]:
    """一键扫描：随机扫描公网VPS CIDR，发现代理并验证"""
    targets = _random_ips_from_cidrs(QUICK_SCAN_CIDRS, ip_count)
    print(f"[NmapScanner] 一键扫描 {ip_count} 个随机公网IP...")
    return await discover_proxies(targets, ports=ports, rate=rate)
