"""代理池管理器 - 调度抓取、验证、轮换和后台健康检查"""

import asyncio
import time
import threading
import random
from typing import Optional, Generator, List
import aiohttp
import requests

from .models import Proxy
from .storage import Storage
from .mysql_storage import MysqlStorage
from .scraper import scrape_all
from .validator import validate_batch


class ProxyPool:
    """代理池，提供代理的获取、轮换、后台自动抓取和健康检查"""

    def __init__(self, db_path: str = "", max_pool_size: int = 500,
                 use_mysql: bool = False, mysql_cfg: dict = None):
        if use_mysql:
            cfg = mysql_cfg or {}
            self.storage = MysqlStorage(
                host=cfg.get("host", "127.0.0.1"),
                port=cfg.get("port", 3306),
                user=cfg.get("user", "root"),
                password=cfg.get("password", "root"),
                database=cfg.get("database", "proxy_pool"),
            )
        else:
            self.storage = Storage(db_path)
        self.max_pool_size = max_pool_size
        self._lock = threading.Lock()
        self._running = False
        self._scrape_thread: Optional[threading.Thread] = None
        self._health_thread: Optional[threading.Thread] = None
        self._round_robin_index = 0
        self.scrape_interval = 1800
        self.last_scrape_time = 0.0
        self.last_scrape_count = 0
        self._auto_clean_on_start = True

    def _start_threads(self, scrape_interval: int, health_interval: int = 60):
        """启动后台抓取和健康检查线程（内部方法）"""
        self.scrape_interval = scrape_interval

        def _scrape_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            while self._running:
                try:
                    loop.run_until_complete(self._scrape_and_store())
                except Exception:
                    pass
                for _ in range(self.scrape_interval):
                    if not self._running:
                        break
                    time.sleep(1)

        def _health_loop():
            while self._running:
                try:
                    self._run_health_check()
                except Exception:
                    pass
                for _ in range(health_interval):
                    if not self._running:
                        break
                    time.sleep(1)

        self._scrape_thread = threading.Thread(target=_scrape_loop, daemon=True)
        self._health_thread = threading.Thread(target=_health_loop, daemon=True)
        self._scrape_thread.start()
        self._health_thread.start()

    def start(self, scrape_interval: int = 1800, health_interval: int = 60):
        """启动后台线程：定时抓取 + 定时健康检查"""
        if self._running:
            return
        self._running = True

        if self._auto_clean_on_start:
            cleaned = self.clean()
            if cleaned > 0:
                print(f"[ProxyPool] 启动时自动清理 {cleaned} 个失效代理")

        self._start_threads(scrape_interval, health_interval)

    def stop(self):
        """停止后台线程"""
        self._running = False
        if self._scrape_thread:
            self._scrape_thread.join(timeout=5)
        if self._health_thread:
            self._health_thread.join(timeout=5)

    def restart_scrape(self, interval: int):
        """修改抓取间隔并重启后台线程"""
        self.stop()
        self._running = True
        self._start_threads(interval)

    MAX_LATENCY = 2500  # 最大允许延迟(ms)，超过则标记为失效

    @staticmethod
    def _parse_ip(resp) -> str:
        """解析不同IP检测服务的返回，提取出口IP"""
        import re
        ct = resp.headers.get("content-type", "")
        text = resp.text
        if "json" in ct or text.strip().startswith("{"):
            try:
                data = resp.json()
                for key in ("origin", "ip", "query"):
                    if key in data:
                        return data[key].split(",")[0].strip()
            except Exception:
                pass
        m = re.search(r'IP\s*[：:]\s*([\d.]+)', text)
        if m:
            return m.group(1)
        if re.match(r'^[\d.]+$', text.strip()):
            return text.strip()
        m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', text)
        if m:
            return m.group(1)
        return ""

    def _filter_high_latency(self, proxies: list) -> list:
        """将延迟 > MAX_LATENCY 的代理标记为失效，返回完整列表（含被标dead的）"""
        for p in proxies:
            if p.latency > 0 and p.latency > self.MAX_LATENCY:
                p.status = "dead"
        return proxies

    async def _scrape_and_store(self):
        """执行一次完整的抓取+验证+存储流程"""
        async with aiohttp.ClientSession() as session:
            proxies = await scrape_all(session)
        count = len(proxies) if proxies else 0
        if count:
            self.storage.upsert_many(proxies)
            validated = await validate_batch(proxies, max_concurrent=50)
            validated = self._filter_high_latency(validated)
            self.storage.upsert_many(validated)
        self.last_scrape_time = time.time()
        self.last_scrape_count = count

    def _run_health_check(self):
        """对池中存活代理做一轮健康复查"""
        proxies = self.storage.get_unvalidated(limit=100)
        if not proxies:
            return
        loop = asyncio.new_event_loop()
        try:
            validated = loop.run_until_complete(validate_batch(proxies, max_concurrent=30))
            validated = self._filter_high_latency(validated)
            self.storage.upsert_many(validated)
        finally:
            loop.close()

    def scrape_now(self):
        """手动触发一次抓取+验证（同步阻塞）"""
        asyncio.run(self._scrape_and_store())
        self.last_scrape_time = time.time()

    def validate_all(self) -> int:
        """验证所有待检测的代理，返回验证数量"""
        proxies = self.storage.get_unvalidated(limit=500)
        if not proxies:
            return 0
        validated = asyncio.run(validate_batch(proxies, max_concurrent=50))
        validated = self._filter_high_latency(validated)
        self.storage.upsert_many(validated)
        return len(validated)

    def get(self, protocol: str = "", country: str = "",
            strategy: str = "random", max_latency: float = 0,
            supports_connect: bool = False) -> Optional[Proxy]:
        """从代理池中获取一个代理，自动排除 fail_count >= 3 的代理"""
        if strategy == "round_robin":
            alive = self.storage.query(protocol=protocol, country=country, status="alive", sort_by="latency", limit=500, max_latency=max_latency, supports_connect=supports_connect)
            alive = [p for p in alive if p.fail_count < 3]
            if not alive:
                return None
            with self._lock:
                idx = self._round_robin_index % len(alive)
                self._round_robin_index += 1
                return alive[idx]
        elif strategy == "lowest_latency":
            proxies = self.storage.query(protocol=protocol, country=country, status="alive", sort_by="latency", limit=50, max_latency=max_latency, supports_connect=supports_connect)
            proxies = [p for p in proxies if p.fail_count < 3]
            return proxies[0] if proxies else None
        else:
            proxy = self.storage.get_random(protocol=protocol, country=country, status="alive")
            return proxy if proxy and proxy.fail_count < 3 else None

    def list(self, protocol: str = "", country: str = "", status: str = "alive",
             sort_by: str = "latency", limit: int = 200, max_latency: float = 0,
             supports_connect: bool = False) -> List[Proxy]:
        """列出符合条件的代理"""
        return self.storage.query(
            protocol=protocol, country=country, status=status,
            sort_by=sort_by, limit=limit, max_latency=max_latency,
            supports_connect=supports_connect
        )

    def iter(self, protocol: str = "", country: str = "",
             strategy: str = "round_robin") -> Generator[Proxy, None, None]:
        """代理迭代器，持续产出代理，适用于长时间任务"""
        while True:
            proxy = self.get(protocol=protocol, country=country, strategy=strategy)
            if proxy:
                yield proxy
            else:
                time.sleep(1)

    def session(self, protocol: str = "http", country: str = "") -> requests.Session:
        """创建一个自动切换代理的 requests.Session"""
        session = requests.Session()

        class ProxyHTTPAdapter(requests.adapters.HTTPAdapter):
            """每次请求自动从代理池获取新代理的适配器"""
            def __init__(self, pool, proto, ctry, **kwargs):
                super().__init__(**kwargs)
                self._pool = pool
                self._proto = proto
                self._ctry = ctry

            def send(self, request, **kwargs):
                proxy = self._pool.get(protocol=self._proto, country=self._ctry)
                if proxy:
                    request.proxies = {"http": proxy.url, "https": proxy.url}
                return super().send(request, **kwargs)

        adapter = ProxyHTTPAdapter(self, protocol, country)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    # ── 已验证代理列表 ──
    _verified_proxy_ids: set = set()

    def get_verified_proxies(self) -> List[Proxy]:
        """返回已验证通过的代理列表"""
        if not self._verified_proxy_ids:
            return []
        ids = list(self._verified_proxy_ids)
        proxies = self.storage.query(status="", limit=5000)
        return [p for p in proxies if p.id in ids and p.status == "alive"]

    def clear_verified_proxies(self):
        """清空已验证代理集合"""
        self._verified_proxy_ids.clear()

    def test_all_proxies(self, target_url: str = "http://cip.cc",
                         max_concurrent: int = 5) -> int:
        """全量测试所有存活代理：逐个请求目标URL检测出口IP，通过者加入已验证集合。
        返回测试ID（时间戳），结果通过 get_rotation_test() 轮询。"""
        import threading as _thr

        test_id = int(time.time())
        results = {
            "running": True, "start_time": time.time(),
            "target_url": target_url, "requests": [],
            "unique_ips": set(), "rotate_count": 0,
            "last_ip": None, "total_to_test": 0,
            "test_all_mode": True,
        }

        def _run():
            import requests as _requests
            alive = self.storage.query(status="alive", limit=1000)
            results["total_to_test"] = len(alive)

            for i, proxy in enumerate(alive):
                if not results["running"]:
                    break
                try:
                    t0 = time.time()
                    resp = _requests.get(
                        target_url,
                        proxies={"http": proxy.url, "https": proxy.url},
                        timeout=10,
                        headers={"User-Agent": "Mozilla/5.0"}
                    )
                    elapsed = (time.time() - t0) * 1000
                    if resp.status_code == 200:
                        ip = ProxyPool._parse_ip(resp)
                        if ip:
                            self._verified_proxy_ids.add(proxy.id)
                            proxy.latency = elapsed
                            proxy.status = "alive"
                            proxy.fail_count = 0
                            proxy.last_checked = time.time()
                            self.storage.upsert(proxy)
                        else:
                            ip = ""
                    else:
                        ip = ""
                except Exception as e:
                    elapsed = -1
                    ip = ""
                    error = str(e)[:80]
                    proxy.fail_count += 1
                    if proxy.fail_count >= 3:
                        proxy.status = "dead"
                    proxy.last_checked = time.time()
                    self.storage.upsert(proxy)

                if not ip and elapsed > 0:
                    error = "无法解析IP"

                entry = {
                    "time": time.time(), "ip": ip,
                    "latency_ms": round(elapsed, 1) if elapsed > 0 else -1,
                    "success": elapsed > 0 and bool(ip),
                    "error": error, "proxy_id": proxy.id,
                    "proxy_addr": f"{proxy.ip}:{proxy.port}",
                }
                if ip and ip != results["last_ip"]:
                    if results["last_ip"] is not None:
                        results["rotate_count"] += 1
                    results["last_ip"] = ip
                if ip:
                    results["unique_ips"].add(ip)
                results["requests"].append(entry)

            results["running"] = False
            if not hasattr(self, "_test_results"):
                self._test_results = {}
            self._test_results[test_id] = results

        t = _thr.Thread(target=_run, daemon=True)
        if not hasattr(self, "_test_results"):
            self._test_results = {}
        self._test_results[test_id] = results
        t.start()
        return test_id

    def verify_anonymity_all(self) -> int:
        """深度验证所有存活代理的匿名度，返回验证数量"""
        from .validator import _verify_anonymity
        proxies = self.storage.query(status="alive", limit=500)
        count = 0
        for p in proxies:
            result = _verify_anonymity(p)
            if result:
                p.anonymity = result
                p.anon_verified = True
            p.last_checked = time.time()
            count += 1
        self.storage.upsert_many(proxies)
        return count

    @property
    def stats(self) -> dict:
        """获取代理池统计信息"""
        counts = self.storage.count()
        alive = self.storage.query(status="alive", limit=500)
        alive_with_latency = [p for p in alive if p.latency > 0]
        avg_latency = round(
            sum(p.latency for p in alive_with_latency) / max(len(alive_with_latency), 1), 1
        )
        total_use = sum(getattr(p, 'use_count', 0) for p in alive)
        total_success = sum(getattr(p, 'success_count', 0) for p in alive)
        elite_count = sum(1 for p in alive if p.anonymity == "elite")
        connect_count = sum(1 for p in alive if p.supports_connect)
        return {
            **counts,
            "avg_latency": avg_latency,
            "countries": len(self.storage.get_countries()),
            "total_use": total_use,
            "total_success": total_success,
            "elite_count": elite_count,
            "connect_count": connect_count,
        }

    def validate_connect(self) -> int:
        """重验所有存活代理的 CONNECT 支持（不重测延迟）"""
        from .validator import _test_connect_support
        proxies = self.storage.query(status="alive", limit=500)
        count = 0
        for p in proxies:
            p.supports_connect = _test_connect_support(p)
            p.last_checked = time.time()
            count += 1
        self.storage.upsert_many(proxies)
        return count

    def clean(self) -> int:
        """清理所有失效代理"""
        return self.storage.delete_dead()

    def start_rotation_test(self, duration: int = 60, interval: int = 5,
                            target_url: str = "http://httpbin.org/ip",
                            rotator_port: int = 5000) -> int:
        """启动出口IP轮换测试，duration秒内每interval秒发一次请求，
        检测返回IP是否变化，返回测试ID（实际为开始时间戳）"""
        import threading as _thr
        test_id = int(time.time())
        results = {
            "running": True, "start_time": time.time(),
            "duration": duration, "interval": interval,
            "target_url": target_url, "requests": [],
            "unique_ips": set(), "rotate_count": 0,
            "last_ip": None,
        }

        def _test_loop():
            session = requests.Session()
            proxy_addr = f"http://127.0.0.1:{rotator_port}"
            session.proxies = {"http": proxy_addr, "https": proxy_addr}
            end_time = time.time() + duration
            while time.time() < end_time and results["running"]:
                error = ""
                try:
                    t0 = time.time()
                    resp = session.get(target_url, timeout=15, headers={"X-Proxy-Rotate": "force"})
                    elapsed = (time.time() - t0) * 1000
                    if resp.status_code == 200:
                        ip = ProxyPool._parse_ip(resp)
                        if not ip:
                            error = f"无法解析IP (响应前200字: {resp.text[:200]})"
                    else:
                        ip = ""
                        error = f"HTTP {resp.status_code}"
                except Exception as e:
                    elapsed = -1
                    ip = ""
                    error = str(e)[:100]
                cur_time = time.time()
                entry = {
                    "time": cur_time,
                    "ip": ip,
                    "latency_ms": round(elapsed, 1) if elapsed > 0 else -1,
                    "success": elapsed > 0 and bool(ip),
                    "error": error,
                }
                if ip and ip != results["last_ip"]:
                    if results["last_ip"] is not None:
                        results["rotate_count"] += 1
                    results["last_ip"] = ip
                if ip:
                    results["unique_ips"].add(ip)
                results["requests"].append(entry)
                for _ in range(interval):
                    if time.time() >= end_time or not results["running"]:
                        break
                    time.sleep(1)
            results["running"] = False
            session.close()
            # 将结果存到内存中
            if not hasattr(self, "_test_results"):
                self._test_results = {}
            self._test_results[test_id] = results

        t = _thr.Thread(target=_test_loop, daemon=True)
        if not hasattr(self, "_test_results"):
            self._test_results = {}
        self._test_results[test_id] = results
        t.start()
        return test_id

    def get_rotation_test(self, test_id: int) -> dict | None:
        """获取轮换测试的当前结果"""
        if not hasattr(self, "_test_results"):
            return None
        return self._test_results.get(test_id)

    def stop_rotation_test(self, test_id: int) -> bool:
        """停止轮换测试"""
        result = self.get_rotation_test(test_id)
        if result:
            result["running"] = False
            return True
        return False

    def clear_test_results(self, test_id: int) -> bool:
        """清除指定测试的记录"""
        if not hasattr(self, "_test_results"):
            return False
        if test_id in self._test_results:
            del self._test_results[test_id]
            return True
        return False
