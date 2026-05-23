"""MySQL 持久化存储层 - 保存历史有效数据，支持完整统计"""

import mysql.connector
from typing import Optional
from .models import Proxy


class MysqlStorage:
    """MySQL 存储，保存历史代理数据，适合长期统计和国内渗透测试场景"""

    def __init__(self, host: str = "127.0.0.1", port: int = 3306,
                 user: str = "root", password: str = "root",
                 database: str = "proxy_pool"):
        self._cfg = {
            "host": host, "port": port, "user": user,
            "password": password, "database": database,
            "charset": "utf8mb4", "autocommit": True,
        }
        self._ensure_db()
        self._init_table()

    def _connect(self):
        return mysql.connector.connect(**self._cfg)

    def _ensure_db(self):
        """确保数据库存在"""
        cfg = dict(self._cfg)
        cfg.pop("database", None)
        cfg["autocommit"] = True
        try:
            conn = mysql.connector.connect(**cfg)
            cur = conn.cursor()
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{self._cfg['database']}` "
                f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[MysqlStorage] 无法创建数据库: {e}")

    def _init_table(self):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS proxies (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    ip VARCHAR(45) NOT NULL,
                    port INT NOT NULL,
                    protocol VARCHAR(10) NOT NULL DEFAULT 'http',
                    country VARCHAR(10) DEFAULT '',
                    anonymity VARCHAR(20) DEFAULT 'unknown',
                    latency FLOAT DEFAULT -1,
                    status VARCHAR(20) DEFAULT 'unknown',
                    source VARCHAR(80) DEFAULT '',
                    last_checked DOUBLE DEFAULT 0,
                    fail_count INT DEFAULT 0,
                    supports_connect TINYINT DEFAULT 0,
                    favorite TINYINT DEFAULT 0,
                    use_count INT DEFAULT 0,
                    success_count INT DEFAULT 0,
                    anon_verified TINYINT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_proxy (ip, port, protocol),
                    INDEX idx_status (status),
                    INDEX idx_country (country),
                    INDEX idx_protocol (protocol),
                    INDEX idx_latency (latency),
                    INDEX idx_last_checked (last_checked)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.close()

    def upsert(self, proxy: Proxy) -> Optional[int]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO proxies
                    (ip, port, protocol, country, anonymity, latency, status,
                     source, last_checked, fail_count, supports_connect,
                     use_count, success_count, anon_verified)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    country=VALUES(country),
                    anonymity=VALUES(anonymity),
                    latency=VALUES(latency),
                    status=VALUES(status),
                    source=VALUES(source),
                    last_checked=VALUES(last_checked),
                    fail_count=VALUES(fail_count),
                    supports_connect=VALUES(supports_connect),
                    use_count=VALUES(use_count),
                    success_count=VALUES(success_count),
                    anon_verified=VALUES(anon_verified)
            """, (
                proxy.ip, proxy.port, proxy.protocol, proxy.country,
                proxy.anonymity, proxy.latency, proxy.status,
                proxy.source, proxy.last_checked, proxy.fail_count,
                int(proxy.supports_connect),
                getattr(proxy, 'use_count', 0),
                getattr(proxy, 'success_count', 0),
                int(getattr(proxy, 'anon_verified', False))
            ))
            proxy_id = cur.lastrowid
            cur.close()
            return proxy_id

    def upsert_many(self, proxies: list[Proxy]):
        with self._connect() as conn:
            cur = conn.cursor()
            data = [(
                p.ip, p.port, p.protocol, p.country, p.anonymity,
                p.latency, p.status, p.source, p.last_checked, p.fail_count,
                int(p.supports_connect), getattr(p, 'use_count', 0),
                getattr(p, 'success_count', 0),
                int(getattr(p, 'anon_verified', False))
            ) for p in proxies]
            cur.executemany("""
                INSERT INTO proxies
                    (ip, port, protocol, country, anonymity, latency, status,
                     source, last_checked, fail_count, supports_connect,
                     use_count, success_count, anon_verified)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    country=VALUES(country),
                    anonymity=VALUES(anonymity),
                    latency=VALUES(latency),
                    status=VALUES(status),
                    source=VALUES(source),
                    last_checked=VALUES(last_checked),
                    fail_count=VALUES(fail_count),
                    supports_connect=VALUES(supports_connect),
                    use_count=VALUES(use_count),
                    success_count=VALUES(success_count),
                    anon_verified=VALUES(anon_verified)
            """, data)
            cur.close()

    def query(self, protocol: str = "", country: str = "", status: str = "",
              sort_by: str = "latency", limit: int = 200, offset: int = 0,
              max_latency: float = 0, supports_connect: bool = False) -> list[Proxy]:
        sql = "SELECT * FROM proxies WHERE 1=1"
        params = []
        if protocol:
            sql += " AND protocol=%s"; params.append(protocol)
        if country:
            sql += " AND country=%s"; params.append(country.upper())
        if status:
            sql += " AND status=%s"; params.append(status)
        if max_latency > 0:
            sql += " AND latency > 0 AND latency <= %s"; params.append(max_latency)
        if supports_connect:
            sql += " AND supports_connect=1"

        allowed_sort = {"latency", "last_checked", "fail_count", "id", "score"}
        if sort_by == "score":
            order = "latency ASC, fail_count ASC, last_checked DESC"
        else:
            order = sort_by if sort_by in allowed_sort else "latency"
        sql += f" ORDER BY {order} ASC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.close()
        return [Proxy.from_row(r) for r in rows]

    def get_random(self, protocol: str = "", country: str = "",
                   status: str = "alive") -> Optional[Proxy]:
        sql = "SELECT * FROM proxies WHERE 1=1"
        params = []
        if protocol:
            sql += " AND protocol=%s"; params.append(protocol)
        if country:
            sql += " AND country=%s"; params.append(country.upper())
        if status:
            sql += " AND status=%s"; params.append(status)
        sql += " ORDER BY RAND() LIMIT 1"

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            cur.close()
        return Proxy.from_row(row) if row else None

    def count(self) -> dict:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, COUNT(*) FROM proxies GROUP BY status")
            rows = cur.fetchall()
            cur.close()
        result = {"total": 0, "alive": 0, "dead": 0, "unknown": 0}
        for status_val, cnt in rows:
            result[status_val] = cnt
            result["total"] += cnt
        return result

    def get_countries(self) -> list[str]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT country FROM proxies WHERE country != '' ORDER BY country"
            )
            rows = cur.fetchall()
            cur.close()
        return [r[0] for r in rows]

    def toggle_favorite(self, proxy_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT favorite FROM proxies WHERE id=%s", (proxy_id,))
            row = cur.fetchone()
            if not row:
                cur.close()
                return False
            new_val = 0 if row[0] else 1
            cur.execute("UPDATE proxies SET favorite=%s WHERE id=%s", (new_val, proxy_id))
            cur.close()
            return bool(new_val)

    def get_favorites(self, limit: int = 200) -> list[Proxy]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM proxies WHERE favorite=1 ORDER BY latency ASC LIMIT %s",
                (limit,)
            )
            rows = cur.fetchall()
            cur.close()
        return [Proxy.from_row(r) for r in rows]

    def get_by_id(self, proxy_id: int) -> Optional[Proxy]:
        """根据ID获取单个代理"""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM proxies WHERE id=%s", (proxy_id,))
            row = cur.fetchone()
            cur.close()
        return Proxy.from_row(row) if row else None

    def delete_dead(self) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM proxies WHERE status='dead'")
            count = cur.rowcount
            cur.close()
        return count

    def delete_by_ids(self, ids: list[int]) -> int:
        """按ID批量删除代理，返回删除数量"""
        if not ids:
            return 0
        with self._connect() as conn:
            cur = conn.cursor()
            placeholders = ','.join(['%s'] * len(ids))
            cur.execute(
                f"DELETE FROM proxies WHERE id IN ({placeholders})",
                ids
            )
            count = cur.rowcount
            cur.close()
        return count

    def mark_alive_batch(self, ids: list[int], timestamp: float):
        """批量标记代理为存活"""
        if not ids:
            return
        with self._connect() as conn:
            cur = conn.cursor()
            placeholders = ','.join(['%s'] * len(ids))
            cur.execute(
                f"UPDATE proxies SET status='alive', fail_count=0, last_checked=%s WHERE id IN ({placeholders})",
                [timestamp] + ids
            )
            cur.close()

    def mark_dead(self, proxy_id: int):
        import time as _time
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE proxies SET status='dead', fail_count=fail_count+1, last_checked=%s WHERE id=%s",
                (_time.time(), proxy_id)
            )
            cur.close()

    def get_unvalidated(self, limit: int = 500) -> list[Proxy]:
        import time as _time
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM proxies WHERE status='unknown' "
                "OR (status='alive' AND last_checked < %s) "
                "ORDER BY last_checked ASC LIMIT %s",
                (_time.time() - 300, limit)
            )
            rows = cur.fetchall()
            cur.close()
        return [Proxy.from_row(r) for r in rows]

    # ── 历史数据查询（MySQL特色功能） ──

    def get_history(self, days: int = 7) -> dict:
        """获取历史数据统计：每天的新增/存活/失效数量"""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT DATE(created_at) as dt, status, COUNT(*) as cnt
                FROM proxies
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY DATE(created_at), status
                ORDER BY dt
            """, (days,))
            rows = cur.fetchall()
            cur.close()
        result = {}
        for dt, status, cnt in rows:
            dt_str = str(dt)
            if dt_str not in result:
                result[dt_str] = {"total": 0, "alive": 0, "dead": 0, "unknown": 0}
            result[dt_str][status] = cnt
            result[dt_str]["total"] += cnt
        return result

    def get_cn_stats(self) -> dict:
        """获取中国代理专项统计"""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT status, COUNT(*) FROM proxies WHERE country='CN' GROUP BY status"
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT AVG(latency) FROM proxies WHERE country='CN' AND status='alive' AND latency>0"
            )
            avg_lat = cur.fetchone()[0] or 0
            cur.execute(
                "SELECT COUNT(*) FROM proxies WHERE country='CN' AND status='alive' AND supports_connect=1"
            )
            cn_connect = cur.fetchone()[0] or 0
            cur.close()
        result = {"total": 0, "alive": 0, "dead": 0, "unknown": 0, "avg_latency": 0, "connect_ok": cn_connect}
        for status_val, cnt in rows:
            result[status_val] = cnt
            result["total"] += cnt
        result["avg_latency"] = round(avg_lat, 1)
        return result

    # ── 代理分组 ──

    def _init_groups_table(self):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS proxy_groups (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL UNIQUE,
                    protocol VARCHAR(10) DEFAULT '',
                    country VARCHAR(10) DEFAULT '',
                    max_latency FLOAT DEFAULT 0,
                    anonymity VARCHAR(20) DEFAULT '',
                    sort_by VARCHAR(20) DEFAULT 'latency'
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS group_proxies (
                    group_id INT NOT NULL,
                    proxy_id INT NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, proxy_id),
                    FOREIGN KEY (group_id) REFERENCES proxy_groups(id) ON DELETE CASCADE,
                    FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.close()

    def create_group(self, name: str, **filters) -> int:
        self._init_groups_table()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO proxy_groups (name, protocol, country, max_latency, anonymity, sort_by) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (name, filters.get("protocol", ""), filters.get("country", ""),
                 filters.get("max_latency", 0), filters.get("anonymity", ""),
                 filters.get("sort_by", "latency"))
            )
            gid = cur.lastrowid
            cur.close()
        # 自动填充匹配的代理
        self.populate_group(gid)
        return gid

    def delete_group(self, group_id: int):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM group_proxies WHERE group_id=%s", (group_id,))
            cur.execute("DELETE FROM proxy_groups WHERE id=%s", (group_id,))
            cur.close()

    def get_groups(self) -> list[dict]:
        self._init_groups_table()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT g.*, COUNT(gp.proxy_id) as proxy_count
                FROM proxy_groups g
                LEFT JOIN group_proxies gp ON g.id = gp.group_id
                GROUP BY g.id
                ORDER BY g.id
            """)
            rows = cur.fetchall()
            cur.close()
        return [{"id": r[0], "name": r[1], "protocol": r[2], "country": r[3],
                 "max_latency": r[4], "anonymity": r[5], "sort_by": r[6],
                 "proxy_count": r[7]} for r in rows]

    def get_group(self, group_id: int) -> dict | None:
        self._init_groups_table()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT g.*, COUNT(gp.proxy_id) as proxy_count
                FROM proxy_groups g
                LEFT JOIN group_proxies gp ON g.id = gp.group_id
                WHERE g.id = %s
                GROUP BY g.id
            """, (group_id,))
            row = cur.fetchone()
            cur.close()
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
            cur = conn.cursor()
            for pid in proxy_ids:
                try:
                    cur.execute(
                        "INSERT IGNORE INTO group_proxies (group_id, proxy_id) VALUES (%s, %s)",
                        (group_id, pid)
                    )
                    count += cur.rowcount
                except Exception:
                    pass
            cur.close()
        return count

    def remove_from_group(self, group_id: int, proxy_ids: list[int]):
        """从分组移除代理"""
        with self._connect() as conn:
            cur = conn.cursor()
            placeholders = ','.join(['%s'] * len(proxy_ids))
            cur.execute(
                f"DELETE FROM group_proxies WHERE group_id=%s AND proxy_id IN ({placeholders})",
                [group_id] + proxy_ids
            )
            cur.close()

    def get_group_proxy_ids(self, group_id: int) -> list[int]:
        """获取分组内所有代理ID"""
        self._init_groups_table()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT proxy_id FROM group_proxies WHERE group_id=%s ORDER BY added_at DESC",
                (group_id,)
            )
            ids = [r[0] for r in cur.fetchall()]
            cur.close()
        return ids

    def get_group_proxies(self, group_id: int, limit: int = 500) -> list:
        """获取分组内的代理对象列表"""
        ids = self.get_group_proxy_ids(group_id)
        if not ids:
            return []
        with self._connect() as conn:
            cur = conn.cursor()
            placeholders = ','.join(['%s'] * len(ids))
            cur.execute(
                f"SELECT * FROM proxies WHERE id IN ({placeholders}) ORDER BY latency ASC LIMIT %s",
                ids + [limit]
            )
            rows = cur.fetchall()
            cur.close()
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
        # 前端过滤 anonymity
        if group.get("anonymity"):
            proxies = [p for p in proxies if p.anonymity == group["anonymity"]]
        if not proxies:
            return 0
        ids = [p.id for p in proxies if p.id]
        return self.add_to_group(group_id, ids)
