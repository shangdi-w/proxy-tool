"""本地出口IP轮换代理 - HTTP正向代理，支持 HTTP/SOCKS4/SOCKS5 上游"""

import random
import socket
import threading
import time
import select
import socks  # PySocks
from socketserver import ThreadingMixIn
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests

from .pool import ProxyPool


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器，支持并发请求"""
    daemon_threads = True


def _tunnel_data(src, dst, timeout=60):
    """双向转发TCP数据"""
    try:
        while True:
            r, _, _ = select.select([src, dst], [], [], timeout)
            if not r:
                break
            for ready in r:
                data = ready.recv(8192)
                if not data:
                    return
                target = dst if ready is src else src
                target.sendall(data)
    except Exception:
        pass


def _socks_connect(proxy: "Proxy", host: str, port: int, timeout: int = 10) -> socket.socket:
    """通过 SOCKS 代理建立到目标的 TCP 连接"""
    s = socks.socksocket()
    s.set_proxy(
        socks.SOCKS5 if proxy.protocol == "socks5" else socks.SOCKS4,
        proxy.ip, proxy.port
    )
    s.settimeout(timeout)
    s.connect((host, port))
    return s


def _http_connect(proxy: "Proxy", host: str, port: int, timeout: int = 10) -> socket.socket:
    """通过 HTTP CONNECT 建立到目标的 TCP 隧道"""
    s = socket.create_connection((proxy.ip, proxy.port), timeout=timeout)
    req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n"
    s.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = s.recv(4096)
        if not chunk:
            s.close()
            raise ConnectionError("上游代理拒绝 CONNECT")
        resp += chunk
    status = resp.split(b"\r\n")[0].decode(errors="ignore")
    if "200" not in status:
        s.close()
        raise ConnectionError(f"CONNECT 失败: {status}")
    return s


def _connect_via_proxy(proxy: "Proxy", host: str, port: int, timeout: int = 10) -> socket.socket:
    """通过上游代理建立到目标的TCP连接（自动选择 SOCKS 或 HTTP CONNECT）"""
    if proxy.protocol in ("socks4", "socks5"):
        return _socks_connect(proxy, host, port, timeout)
    else:
        return _http_connect(proxy, host, port, timeout)


class _ProxyHandler(BaseHTTPRequestHandler):
    rotator_ref = None

    def _get_proxy_for_request(self):
        """获取本次请求使用的代理（处理会话粘性和按请求数轮换）"""
        rotator = self.rotator_ref
        # 强制轮换头
        if self.headers.get("X-Proxy-Rotate") == "force":
            rotator.rotate()
        # 固定代理优先
        if rotator._pinned_proxy:
            return rotator._pinned_proxy
        # 会话粘性
        if rotator.sticky_sessions:
            sid = self.headers.get("X-Session-Id") or self.headers.get("Cookie", "")
            if sid and sid in rotator._session_map:
                cached = rotator._session_map[sid]
                if cached.status == "alive":
                    return cached
        # 按请求数轮换
        if rotator.rotate_mode == "request":
            rotator._request_count += 1
            if rotator._request_count >= rotator.requests_per_proxy:
                rotator.rotate()
                rotator._request_count = 0
        return rotator.current_proxy

    def _forward_http(self):
        """转发 HTTP 请求，支持 HTTP/SOCKS 上游"""
        max_retries = 3
        last_error = ""
        for _ in range(max_retries):
            proxy = self._get_proxy_for_request()
            if not proxy:
                self._send_error(502, "无可用代理")
                return
            try:
                url = self.path
                headers = {k: v for k, v in self.headers.items() if k.lower() not in ('host', 'x-proxy-rotate')}
                # 随机 UA 伪装
                if "user-agent" not in (k.lower() for k in headers):
                    headers["User-Agent"] = random.choice(self.rotator_ref.UA_POOL)
                body = None
                cl = self.headers.get('Content-Length')
                if cl:
                    body = self.rfile.read(int(cl))

                t0 = time.time()
                proxies = {"http": proxy.url, "https": proxy.url}
                resp = requests.request(
                    method=self.command, url=url, headers=headers, data=body,
                    proxies=proxies, timeout=15, allow_redirects=False, stream=True
                )
                proxy.latency = round((time.time() - t0) * 1000, 1)
                proxy.use_count = getattr(proxy, 'use_count', 0) + 1
                proxy.success_count = getattr(proxy, 'success_count', 0) + 1
                proxy.last_checked = time.time()
                self.rotator_ref.pool.storage.upsert(proxy)

                # 会话粘性缓存
                if self.rotator_ref.sticky_sessions:
                    sid = self.headers.get("X-Session-Id") or self.headers.get("Cookie", "")
                    if sid:
                        self.rotator_ref._session_map[sid] = proxy

                self.send_response(resp.status_code)
                for k, v in resp.headers.items():
                    if k.lower() not in ('transfer-encoding', 'content-encoding', 'content-length'):
                        self.send_header(k, v)
                content = resp.content
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)
                return
            except Exception as e:
                last_error = str(e)
                proxy.fail_count += 1
                proxy.use_count = getattr(proxy, 'use_count', 0) + 1
                if proxy.fail_count >= 3:
                    proxy.status = "dead"
                self.rotator_ref.rotate()
        self._send_error(502, f"转发失败: {last_error}")

    def _tunnel_connect(self):
        """处理 CONNECT（HTTPS隧道），SOCKS 用 socks 库，HTTP 用 CONNECT"""
        target_host, target_port = self.path.split(":")
        target_port = int(target_port)
        max_retries = 3
        last_error = ""

        for _ in range(max_retries):
            proxy = self.rotator_ref.current_proxy
            if not proxy:
                self._send_error(502, "无可用代理")
                return
            upstream = None
            try:
                upstream = _connect_via_proxy(proxy, target_host, target_port)
                self.send_response(200, "Connection Established")
                self.end_headers()

                client = self.connection
                t1 = threading.Thread(target=_tunnel_data, args=(client, upstream), daemon=True)
                t2 = threading.Thread(target=_tunnel_data, args=(upstream, client), daemon=True)
                t1.start(); t2.start()
                t1.join(timeout=120); t2.join(timeout=120)
                return
            except Exception as e:
                last_error = str(e)
                proxy.fail_count += 1
                proxy.use_count = getattr(proxy, 'use_count', 0) + 1
                if proxy.fail_count >= 3:
                    proxy.status = "dead"
                self.rotator_ref.rotate()
                if upstream:
                    try: upstream.close()
                    except Exception: pass
        self._send_error(502, f"隧道失败: {last_error}")

    def _send_error(self, code, msg=""):
        try:
            self.send_response(code)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(msg.encode())
        except Exception:
            pass

    def do_GET(self): self._forward_http()
    def do_POST(self): self._forward_http()
    def do_CONNECT(self): self._tunnel_connect()
    def log_message(self, format, *args): pass


class Rotator(threading.Thread):
    """本地代理轮换器"""

    # 随机 UA 池
    UA_POOL = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ]

    def __init__(self, pool: ProxyPool, port: int = 5000, interval: int = 60,
                 protocol: str = "", country: str = "", max_latency: float = 0):
        super().__init__(daemon=True)
        self.pool = pool
        self.port = port
        self.interval = interval
        self.protocol = protocol
        self.country = country
        self.max_latency = max_latency

        self._lock = threading.Lock()
        self._server: HTTPServer = None
        self._running = False
        self._current_proxy = None
        self._pinned_proxy = None
        self._rotate_count = 0
        self._last_rotate_time = 0.0
        self._rotate_timer: threading.Timer = None
        # 新策略参数
        self.rotate_mode = "time"       # "time" / "request"
        self.requests_per_proxy = 50    # 按请求数模式时，每个代理处理多少请求后切换
        self._request_count = 0
        self._session_map: dict[str, object] = {}  # session_id → proxy
        self.sticky_sessions = False
        self.use_verified_only = False   # 仅使用已验证的代理

    @property
    def current_proxy(self):
        with self._lock:
            return self._pinned_proxy or self._current_proxy

    @current_proxy.setter
    def current_proxy(self, value):
        with self._lock:
            self._current_proxy = value

    def _pick_proxy(self):
        """选代理：SOCKS 天然支持全流量，HTTP 需 supports_connect。
        如果 use_verified_only=True，只从已验证列表中选。"""
        if self.use_verified_only:
            verified = self.pool.get_verified_proxies()
            if verified:
                # 先按条件筛选
                filtered = [p for p in verified if
                            (not self.protocol or p.protocol == self.protocol) and
                            (not self.country or p.country == self.country) and
                            (self.max_latency <= 0 or (p.latency > 0 and p.latency <= self.max_latency))]
                if filtered:
                    random.shuffle(filtered)
                    return filtered[0]
                # 放宽条件
                random.shuffle(verified)
                return verified[0]

        if self.protocol and self.protocol not in ("socks4", "socks5"):
            proxy = self.pool.get(
                protocol=self.protocol, country=self.country,
                max_latency=self.max_latency, supports_connect=True
            )
        else:
            proxy = self.pool.get(
                protocol=self.protocol, country=self.country,
                max_latency=self.max_latency
            )
        if not proxy:
            proxy = self.pool.get(protocol="socks5", strategy="lowest_latency", max_latency=self.max_latency)
        if not proxy:
            proxy = self.pool.get(strategy="random", supports_connect=True)
        if not proxy:
            proxy = self.pool.get(strategy="random")
        return proxy

    def rotate(self):
        if self._pinned_proxy:
            return self.current_proxy
        new_proxy = self._pick_proxy()
        if new_proxy:
            self.current_proxy = new_proxy
            self._rotate_count += 1
            self._last_rotate_time = time.time()
        return self.current_proxy

    def pin(self, proxy_id: int):
        proxy = self.pool.storage.get_by_id(proxy_id)
        if proxy and proxy.status == "alive":
            self._pinned_proxy = proxy
            return True
        return False

    def unpin(self):
        self._pinned_proxy = None

    @property
    def is_pinned(self) -> bool:
        return self._pinned_proxy is not None

    def _schedule_rotate(self):
        if not self._running or self._pinned_proxy:
            return
        self._rotate_timer = threading.Timer(self.interval, self._on_timer_rotate)
        self._rotate_timer.daemon = True
        self._rotate_timer.start()

    def _on_timer_rotate(self):
        if self._running and not self._pinned_proxy:
            self.rotate()
            self._schedule_rotate()

    def run(self):
        proxy = self._pick_proxy()
        if not proxy:
            raise RuntimeError("代理池为空")
        self.current_proxy = proxy
        self._last_rotate_time = time.time()
        self._rotate_count = 1
        self._running = True

        _ProxyHandler.rotator_ref = self
        self._schedule_rotate()

        self._server = _ThreadingHTTPServer(("0.0.0.0", self.port), _ProxyHandler)
        self._server.timeout = 1
        try:
            while self._running:
                self._server.handle_request()
        except Exception:
            pass
        finally:
            self._server.server_close()

    def start_service(self):
        self.start()
        time.sleep(0.5)

    def stop_service(self):
        self._running = False
        if self._rotate_timer:
            self._rotate_timer.cancel()
        try:
            socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
        except Exception:
            pass
        self.join(timeout=5)

    @property
    def status(self) -> dict:
        proxy = self.current_proxy
        elapsed = time.time() - self._last_rotate_time if self._last_rotate_time else 0
        remaining = max(0, self.interval - elapsed) if not self._pinned_proxy else -1
        return {
            "running": self._running,
            "port": self.port,
            "interval": self.interval,
            "rotate_count": self._rotate_count,
            "next_rotate_in": round(remaining, 1),
            "pinned": self.is_pinned,
            "current_proxy": proxy.dict if proxy else None,
            "config": {
                "protocol": self.protocol,
                "country": self.country,
                "max_latency": self.max_latency,
                "rotate_mode": self.rotate_mode,
                "requests_per_proxy": self.requests_per_proxy,
                "sticky_sessions": self.sticky_sessions,
                "use_verified_only": self.use_verified_only,
                "verified_count": len(self.pool._verified_proxy_ids),
            }
        }
