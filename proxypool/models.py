"""代理数据模型"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Proxy:
    """代理实体，包含 IP、端口、协议、国家、延迟等信息。"""
    ip: str
    port: int
    protocol: str = "http"       # http / https / socks4 / socks5
    country: str = ""            # ISO 3166-1 两位国家代码
    anonymity: str = "unknown"   # transparent(透明) / anonymous(匿名) / elite(高匿)
    latency: float = -1.0        # 延迟(毫秒)，-1 表示未知
    status: str = "unknown"      # alive(存活) / dead(失效) / unknown(未知)
    source: str = ""             # 抓取来源名称
    last_checked: float = 0.0    # 最后检测时间(unix时间戳)
    fail_count: int = 0          # 连续失败次数
    supports_connect: bool = False  # 是否支持 CONNECT 隧道(HTTPS)
    favorite: bool = False       # 是否收藏
    use_count: int = 0           # 总使用次数
    success_count: int = 0       # 成功次数
    anon_verified: bool = False  # 是否已深度验证匿名度
    id: Optional[int] = None

    @property
    def score(self) -> float:
        """健康度综合评分 0-100，加权计算延迟+失败次数+新鲜度+CONNECT支持"""
        import time
        now = time.time()
        # 延迟分 (40%) — 延迟越低越好
        lat_score = 40 * max(0, 1 - (self.latency / 5000 if self.latency > 0 else 0.5))
        # 失败分 (30%) — 失败越少越好
        fail_score = 30 * max(0, 1 - self.fail_count / 5)
        # CONNECT 支持 (10%)
        conn_score = 10 if self.supports_connect else 0
        # 新鲜度 (20%) — 最近验证过的加分
        age_hours = (now - self.last_checked) / 3600 if self.last_checked > 0 else 24
        fresh_score = 20 * max(0, 1 - age_hours / 24)
        return round(lat_score + fail_score + conn_score + fresh_score, 1)

    @property
    def url(self) -> str:
        """返回 protocol://ip:port 格式的代理URL"""
        return f"{self.protocol}://{self.ip}:{self.port}"

    @property
    def socks_url(self) -> str:
        """返回 socks5h://ip:port 格式，供 requests[socks] 使用"""
        proto = self.protocol.replace("socks", "socks")
        return f"{proto}h://{self.ip}:{self.port}"

    @property
    def dict(self) -> dict:
        """转为字典，方便 JSON 序列化"""
        return {
            "id": self.id,
            "ip": self.ip,
            "port": self.port,
            "protocol": self.protocol,
            "country": self.country,
            "anonymity": self.anonymity,
            "latency": self.latency,
            "status": self.status,
            "source": self.source,
            "last_checked": self.last_checked,
            "fail_count": self.fail_count,
            "supports_connect": self.supports_connect,
            "favorite": self.favorite,
            "score": self.score,
            "use_count": self.use_count,
            "success_count": self.success_count,
            "anon_verified": self.anon_verified,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "Proxy":
        """从 SQLite 行记录构造 Proxy 实例"""
        return cls(
            id=row[0], ip=row[1], port=row[2], protocol=row[3],
            country=row[4], anonymity=row[5], latency=row[6],
            status=row[7], source=row[8], last_checked=row[9],
            fail_count=row[10],
            supports_connect=bool(row[11]) if len(row) > 11 else False,
            favorite=bool(row[12]) if len(row) > 12 else False,
            use_count=int(row[13]) if len(row) > 13 else 0,
            success_count=int(row[14]) if len(row) > 14 else 0,
            anon_verified=bool(row[15]) if len(row) > 15 else False,
        )

    def __hash__(self):
        return hash((self.ip, self.port, self.protocol))

    def __eq__(self, other):
        return (self.ip, self.port, self.protocol) == (other.ip, other.port, other.protocol)
