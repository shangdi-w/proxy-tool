"""SQLite 持久化存储层 - 管理代理的增删改查"""

import sqlite3
import os
from typing import Optional
from .models import Proxy

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "proxies.db")


def get_db_path() -> str:
    """获取数据库文件绝对路径"""
    return os.path.abspath(DB_PATH)


class Storage:
    """SQLite 存储，管理代理的增删改查操作"""

    def __init__(self, db_path: str = ""):
        self.db_path = db_path or get_db_path()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """创建数据库连接，开启 WAL 模式提升并发性能"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        """初始化表结构和索引"""
        with self._connect() as conn:
            # 兼容旧表：添加新列
            for col in ["supports_connect", "favorite", "use_count", "success_count", "anon_verified"]:
                try:
                    conn.execute(f"ALTER TABLE proxies ADD COLUMN {col} INTEGER DEFAULT 0")
                except Exception:
                    pass
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS proxies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    protocol TEXT NOT NULL DEFAULT 'http',
                    country TEXT DEFAULT '',
                    anonymity TEXT DEFAULT 'unknown',
                    latency REAL DEFAULT -1,
                    status TEXT DEFAULT 'unknown',
                    source TEXT DEFAULT '',
                    last_checked REAL DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    supports_connect INTEGER DEFAULT 0,
                    favorite INTEGER DEFAULT 0,
                    UNIQUE(ip, port, protocol)
                );
                CREATE INDEX IF NOT EXISTS idx_status ON proxies(status);
                CREATE INDEX IF NOT EXISTS idx_country ON proxies(country);
                CREATE INDEX IF NOT EXISTS idx_protocol ON proxies(protocol);
            """)

    def upsert(self, proxy: Proxy) -> Optional[int]:
        """插入或更新单条代理记录"""
        with self._connect() as conn:
            try:
                cur = conn.execute("""
                    INSERT INTO proxies (ip, port, protocol, country, anonymity, latency, status, source, last_checked, fail_count, supports_connect, use_count, success_count, anon_verified)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ip, port, protocol) DO UPDATE SET
                        country=excluded.country,
                        anonymity=excluded.anonymity,
                        latency=excluded.latency,
                        status=excluded.status,
                        source=excluded.source,
                        last_checked=excluded.last_checked,
                        fail_count=excluded.fail_count,
                        supports_connect=excluded.supports_connect,
                        use_count=excluded.use_count,
                        success_count=excluded.success_count,
                        anon_verified=excluded.anon_verified
                """, (proxy.ip, proxy.port, proxy.protocol, proxy.country, proxy.anonymity,
                      proxy.latency, proxy.status, proxy.source, proxy.last_checked, proxy.fail_count,
                      int(proxy.supports_connect), getattr(proxy, 'use_count', 0),
                      getattr(proxy, 'success_count', 0), int(getattr(proxy, 'anon_verified', False))))
                return cur.lastrowid
            except Exception:
                return None

    def upsert_many(self, proxies: list[Proxy]):
        """批量插入或更新代理记录"""
        with self._connect() as conn:
            conn.executemany("""
                INSERT INTO proxies (ip, port, protocol, country, anonymity, latency, status, source, last_checked, fail_count, supports_connect, use_count, success_count, anon_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ip, port, protocol) DO UPDATE SET
                    country=excluded.country,
                    anonymity=excluded.anonymity,
                    latency=excluded.latency,
                    status=excluded.status,
                    source=excluded.source,
                    last_checked=excluded.last_checked,
                    fail_count=excluded.fail_count,
                    supports_connect=excluded.supports_connect,
                    use_count=excluded.use_count,
                    success_count=excluded.success_count,
                    anon_verified=excluded.anon_verified
            """, [(p.ip, p.port, p.protocol, p.country, p.anonymity,
                   p.latency, p.status, p.source, p.last_checked, p.fail_count,
                   int(p.supports_connect), getattr(p, 'use_count', 0),
                   getattr(p, 'success_count', 0), int(getattr(p, 'anon_verified', False))) for p in proxies])

    def query(self, protocol: str = "", country: str = "", status: str = "",
              sort_by: str = "latency", limit: int = 200, offset: int = 0,
              max_latency: float = 0, supports_connect: bool = False) -> list[Proxy]:
        """按条件查询代理列表，supports_connect=True 时仅返回支持 CONNECT 隧道的代理"""
        sql = "SELECT * FROM proxies WHERE 1=1"
        params = []
        if protocol:
            sql += " AND protocol=?"
            params.append(protocol)
        if country:
            sql += " AND country=?"
            params.append(country.upper())
        if status:
            sql += " AND status=?"
            params.append(status)
        if max_latency > 0:
            sql += " AND latency > 0 AND latency <= ?"
            params.append(max_latency)
        if supports_connect:
            sql += " AND supports_connect=1"

        allowed_sort = {"latency", "last_checked", "fail_count", "id", "score"}
        if sort_by == "score":
            order = "latency ASC, fail_count ASC, last_checked DESC"
        else:
            order = sort_by if sort_by in allowed_sort else "latency"
        sql += f" ORDER BY {order} ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Proxy.from_row(r) for r in rows]

    def get_random(self, protocol: str = "", country: str = "", status: str = "alive") -> Optional[Proxy]:
        """随机获取一个符合条件的代理"""
        sql = "SELECT * FROM proxies WHERE 1=1"
        params = []
        if protocol:
            sql += " AND protocol=?"
            params.append(protocol)
        if country:
            sql += " AND country=?"
            params.append(country.upper())
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY RANDOM() LIMIT 1"

        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return Proxy.from_row(row) if row else None

    def count(self) -> dict:
        """统计各状态代理数量"""
        with self._connect() as conn:
            result = {"total": 0, "alive": 0, "dead": 0, "unknown": 0}
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM proxies GROUP BY status"
            ).fetchall()
            for status_val, cnt in rows:
                result[status_val] = cnt
                result["total"] += cnt
            return result

    def get_countries(self) -> list[str]:
        """获取所有有代理的国家代码列表"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT country FROM proxies WHERE country != '' ORDER BY country"
            ).fetchall()
        return [r[0] for r in rows]

    def toggle_favorite(self, proxy_id: int) -> bool:
        """切换收藏状态，返回新状态"""
        with self._connect() as conn:
            row = conn.execute("SELECT favorite FROM proxies WHERE id=?", (proxy_id,)).fetchone()
            if not row:
                return False
            new_val = 0 if row[0] else 1
            conn.execute("UPDATE proxies SET favorite=? WHERE id=?", (new_val, proxy_id))
            return bool(new_val)

    def get_favorites(self, limit: int = 200) -> list[Proxy]:
        """获取所有收藏的代理"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM proxies WHERE favorite=1 ORDER BY latency ASC LIMIT ?", (limit,)
            ).fetchall()
        return [Proxy.from_row(r) for r in rows]

    # ── 代理分组 ──

    def _init_groups_table(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proxy_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    protocol TEXT DEFAULT '',
                    country TEXT DEFAULT '',
                    max_latency REAL DEFAULT 0,
                    anonymity TEXT DEFAULT '',
                    sort_by TEXT DEFAULT 'latency'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS group_proxies (
                    group_id INTEGER NOT NULL,
                    proxy_id INTEGER NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, proxy_id),
                    FOREIGN KEY (group_id) REFERENCES proxy_groups(id) ON DELETE CASCADE,
                    FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE CASCADE
                )
            """)

    def create_group(self, name: str, **filters) -> int:
        self._init_groups_table()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO proxy_groups (name, protocol, country, max_latency, anonymity, sort_by) VALUES (?,?,?,?,?,?)",
                (name, filters.get("protocol", ""), filters.get("country", ""),
                 filters.get("max_latency", 0), filters.get("anonymity", ""),
                 filters.get("sort_by", "latency"))
            )
            gid = cur.lastrowid
        self.populate_group(gid)
        return gid

    def delete_group(self, group_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM group_proxies WHERE group_id=?", (group_id,))
            conn.execute("DELETE FROM proxy_groups WHERE id=?", (group_id,))

    def get_groups(self) -> list[dict]:
        self._init_groups_table()
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT g.*, COUNT(gp.proxy_id) as proxy_count
                FROM proxy_groups g
                LEFT JOIN group_proxies gp ON g.id = gp.group_id
                GROUP BY g.id
                ORDER BY g.id
            """).fetchall()
        return [{"id": r[0], "name": r[1], "protocol": r[2], "country": r[3],
                 "max_latency": r[4], "anonymity": r[5], "sort_by": r[6],
                 "proxy_count": r[7]} for r in rows]

    def get_group(self, group_id: int) -> dict | None:
        self._init_groups_table()
        with self._connect() as conn:
            row = conn.execute("""
                SELECT g.*, COUNT(gp.proxy_id) as proxy_count
                FROM proxy_groups g
                LEFT JOIN group_proxies gp ON g.id = gp.group_id
                WHERE g.id = ?
                GROUP BY g.id
            """, (group_id,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "name": row[1], "protocol": row[2], "country": row[3],
                "max_latency": row[4], "anonymity": row[5], "sort_by": row[6],
                "proxy_count": row[7]}

    # ── 分组-代理关联 ──

    def add_to_group(self, group_id: int, proxy_ids: list[int]) -> int:
        """将代理添加到分组，返回实际添加数量"""
        self._init_groups_table()
        count = 0
        with self._connect() as conn:
            for pid in proxy_ids:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO group_proxies (group_id, proxy_id) VALUES (?, ?)",
                        (group_id, pid)
                    )
                    if conn.total_changes > count:
                        count += 1
                except Exception:
                    pass
        return count

    def remove_from_group(self, group_id: int, proxy_ids: list[int]):
        """从分组移除代理"""
        with self._connect() as conn:
            placeholders = ','.join(['?'] * len(proxy_ids))
            conn.execute(
                f"DELETE FROM group_proxies WHERE group_id=? AND proxy_id IN ({placeholders})",
                [group_id] + proxy_ids
            )

    def get_group_proxy_ids(self, group_id: int) -> list[int]:
        """获取分组内所有代理ID"""
        self._init_groups_table()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT proxy_id FROM group_proxies WHERE group_id=? ORDER BY added_at DESC",
                (group_id,)
            ).fetchall()
        return [r[0] for r in rows]

    def get_group_proxies(self, group_id: int, limit: int = 500) -> list:
        """获取分组内的代理对象列表"""
        ids = self.get_group_proxy_ids(group_id)
        if not ids:
            return []
        with self._connect() as conn:
            placeholders = ','.join(['?'] * len(ids))
            rows = conn.execute(
                f"SELECT * FROM proxies WHERE id IN ({placeholders}) ORDER BY latency ASC LIMIT ?",
                ids + [limit]
            ).fetchall()
        return [Proxy.from_row(r) for r in rows]

    def populate_group(self, group_id: int) -> int:
        """根据分组筛选条件自动填充匹配的代理，返回填充数量"""
        group = self.get_group(group_id)
        if not group:
            return 0
        proxies = self.query(
            protocol=group["protocol"], country=group["country"],
            status="alive", sort_by=group.get("sort_by", "latency"),
            max_latency=group.get("max_latency", 0), limit=500
        )
        if group.get("anonymity"):
            proxies = [p for p in proxies if p.anonymity == group["anonymity"]]
        if not proxies:
            return 0
        ids = [p.id for p in proxies if p.id]
        return self.add_to_group(group_id, ids)

    def get_by_id(self, proxy_id: int) -> Optional[Proxy]:
        """根据ID获取单个代理"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM proxies WHERE id=?", (proxy_id,)
            ).fetchone()
        return Proxy.from_row(row) if row else None

    def delete_dead(self) -> int:
        """删除所有失效代理，返回删除数量"""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM proxies WHERE status='dead'")
            return cur.rowcount

    def delete_by_ids(self, ids: list[int]) -> int:
        """按ID批量删除代理，返回删除数量"""
        if not ids:
            return 0
        with self._connect() as conn:
            placeholders = ','.join(['?'] * len(ids))
            cur = conn.execute(
                f"DELETE FROM proxies WHERE id IN ({placeholders})",
                ids
            )
            return cur.rowcount

    def mark_alive_batch(self, ids: list[int], timestamp: float):
        """批量标记代理为存活"""
        if not ids:
            return
        with self._connect() as conn:
            placeholders = ','.join(['?'] * len(ids))
            conn.execute(
                f"UPDATE proxies SET status='alive', fail_count=0, last_checked=? WHERE id IN ({placeholders})",
                [timestamp] + ids
            )

    def mark_dead(self, proxy_id: int):
        """标记某个代理为失效"""
        import time
        with self._connect() as conn:
            conn.execute(
                "UPDATE proxies SET status='dead', fail_count=fail_count+1, last_checked=? WHERE id=?",
                (time.time(), proxy_id)
            )

    def get_unvalidated(self, limit: int = 500) -> list[Proxy]:
        """获取待验证的代理（未知状态 或 存活但超过5分钟未检测的）"""
        import time
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM proxies WHERE status='unknown' OR (status='alive' AND last_checked < ?) ORDER BY last_checked ASC LIMIT ?",
                (time.time() - 300, limit)
            ).fetchall()
        return [Proxy.from_row(r) for r in rows]
