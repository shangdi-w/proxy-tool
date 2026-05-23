"""REST API - 代理池接口"""

import asyncio
import csv
import io
import json
import time as _time

from flask import Blueprint, request, jsonify, Response

from .app import get_pool, get_rotator
from ..validator import validate_batch

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/proxies", methods=["GET"])
def list_proxies():
    """查询代理列表，支持协议/国家/状态/排序/最大延迟筛选"""
    pool = get_pool()
    protocol = request.args.get("protocol", "")
    country = request.args.get("country", "")
    status = request.args.get("status", "alive")
    sort_by = request.args.get("sort_by", "latency")
    limit = request.args.get("limit", 200, type=int)
    offset = request.args.get("offset", 0, type=int)
    max_latency = request.args.get("max_latency", 0, type=float)

    proxies = pool.list(
        protocol=protocol, country=country, status=status,
        sort_by=sort_by, limit=min(limit, 1000), max_latency=max_latency
    )
    return jsonify([p.dict for p in proxies])


@api_bp.route("/proxies/random", methods=["GET"])
def random_proxy():
    """随机获取一个存活代理"""
    pool = get_pool()
    protocol = request.args.get("protocol", "")
    country = request.args.get("country", "")
    strategy = request.args.get("strategy", "random")

    proxy = pool.get(protocol=protocol, country=country, strategy=strategy)
    if proxy:
        return jsonify(proxy.dict)
    return jsonify({"error": "没有找到符合条件的代理"}), 404


@api_bp.route("/proxies/count", methods=["GET"])
def proxy_count():
    """获取各状态代理数量统计"""
    pool = get_pool()
    return jsonify(pool.storage.count())


@api_bp.route("/proxies", methods=["DELETE"])
def delete_proxies():
    """删除指定状态的代理（默认为失效）"""
    pool = get_pool()
    status = request.args.get("status", "dead")
    if status == "dead":
        count = pool.clean()
    else:
        count = 0
    return jsonify({"deleted": count})


@api_bp.route("/scrape", methods=["POST"])
def trigger_scrape():
    """手动触发一次抓取"""
    pool = get_pool()
    pool.scrape_now()
    return jsonify({"status": "ok"})


@api_bp.route("/validate", methods=["POST"])
def trigger_validate():
    """手动触发一次全量验证"""
    pool = get_pool()
    count = pool.validate_all()
    return jsonify({"status": "ok", "validated": count})


@api_bp.route("/validate-connect", methods=["POST"])
def trigger_validate_connect():
    """重验所有存活代理的 CONNECT 支持"""
    pool = get_pool()
    count = pool.validate_connect()
    connect_ok = len(pool.list(supports_connect=True, limit=500))
    return jsonify({"status": "ok", "checked": count, "connect_ok": connect_ok})


@api_bp.route("/verify-anonymity", methods=["POST"])
def trigger_anonymity_check():
    """深度验证所有存活代理的匿名度"""
    pool = get_pool()
    count = pool.verify_anonymity_all()
    proxies = pool.list(status="alive", limit=500)
    elite = sum(1 for p in proxies if p.anonymity == "elite")
    anonymous = sum(1 for p in proxies if p.anonymity == "anonymous")
    transparent = sum(1 for p in proxies if p.anonymity == "transparent")
    return jsonify({
        "status": "ok", "checked": count,
        "elite": elite, "anonymous": anonymous, "transparent": transparent
    })


# ── 历史数据与国内代理统计（MySQL 专用）──

@api_bp.route("/history", methods=["GET"])
def proxy_history():
    """获取代理池历史数据（按天统计）"""
    pool = get_pool()
    days = request.args.get("days", 7, type=int)
    if hasattr(pool.storage, 'get_history'):
        return jsonify(pool.storage.get_history(days))
    return jsonify({"error": "仅 MySQL 存储支持历史数据"}), 400


@api_bp.route("/cn-stats", methods=["GET"])
def cn_proxy_stats():
    """获取中国代理专项统计"""
    pool = get_pool()
    if hasattr(pool.storage, 'get_cn_stats'):
        return jsonify(pool.storage.get_cn_stats())
    return jsonify({"error": "仅 MySQL 存储支持CN统计"}), 400


# ── 自动持续抓取 API ──

@api_bp.route("/auto-scrape/status", methods=["GET"])
def auto_scrape_status():
    """查询自动抓取状态"""
    pool = get_pool()
    return jsonify({
        "running": pool._running,
        "interval": pool.scrape_interval,
        "last_scrape_time": pool.last_scrape_time,
        "last_scrape_count": pool.last_scrape_count,
    })


@api_bp.route("/auto-scrape/start", methods=["POST"])
def auto_scrape_start():
    """启动/重启自动抓取"""
    pool = get_pool()
    data = request.get_json(silent=True) or {}
    interval = data.get("interval", 300)
    pool.restart_scrape(int(interval))
    return jsonify(auto_scrape_status().json)


@api_bp.route("/auto-scrape/stop", methods=["POST"])
def auto_scrape_stop():
    """停止自动抓取"""
    pool = get_pool()
    pool.stop()
    return jsonify({"status": "stopped", "running": False})


@api_bp.route("/stats", methods=["GET"])
def stats():
    """获取代理池整体统计"""
    pool = get_pool()
    return jsonify(pool.stats)


@api_bp.route("/countries", methods=["GET"])
def countries():
    """获取所有有代理的国家列表"""
    pool = get_pool()
    return jsonify(pool.storage.get_countries())


@api_bp.route("/export", methods=["GET", "POST"])
def export_proxies():
    """导出代理列表，支持 JSON / CSV / TXT / Proxychains 格式。
    POST 可传 ids 列表批量导出指定代理。"""
    pool = get_pool()
    fmt = request.args.get("format", "json")
    protocol = request.args.get("protocol", "")
    country = request.args.get("country", "")
    status = request.args.get("status", "alive")

    # POST 批量导出指定 ID
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        ids = data.get("ids", [])
        if ids:
            all_proxies = pool.list(status="", limit=5000)
            id_set = set(int(i) for i in ids)
            proxies = [p for p in all_proxies if p.id in id_set]
        else:
            proxies = pool.list(protocol=protocol, country=country, status=status, limit=5000)
    else:
        proxies = pool.list(protocol=protocol, country=country, status=status, limit=5000)

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ip", "port", "protocol", "country", "anonymity", "latency", "status", "source"])
        for p in proxies:
            writer.writerow([p.ip, p.port, p.protocol, p.country, p.anonymity, p.latency, p.status, p.source])
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=proxies.csv"})
    elif fmt == "txt":
        lines = [f"{p.protocol}://{p.ip}:{p.port}" for p in proxies]
        return Response("\n".join(lines), mimetype="text/plain",
                        headers={"Content-Disposition": "attachment; filename=proxies.txt"})
    elif fmt == "proxychains":
        # proxychains 格式: protocol ip port [user pass]
        lines = []
        for p in proxies:
            ptype = "socks5" if p.protocol == "socks5" else "socks4" if p.protocol == "socks4" else "http"
            lines.append(f"{ptype} {p.ip} {p.port}")
        return Response("\n".join(lines), mimetype="text/plain",
                        headers={"Content-Disposition": "attachment; filename=proxychains.conf"})
    else:
        return Response(
            json.dumps([p.dict for p in proxies], indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=proxies.json"}
        )


@api_bp.route("/proxies/batch", methods=["POST"])
def batch_operation():
    """批量操作：validate / delete / mark_dead / mark_alive"""
    pool = get_pool()
    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    ids = [int(i) for i in data.get("ids", [])]
    if not ids:
        return jsonify({"error": "缺少 ids"}), 400

    if action == "delete":
        count = pool.storage.delete_by_ids(ids)
        return jsonify({"status": "ok", "count": count})
    elif action == "validate":
        all_proxies = pool.list(status="", limit=5000)
        to_validate = [p for p in all_proxies if p.id in ids]
        if to_validate:
            validated = asyncio.run(validate_batch(to_validate, max_concurrent=30))
            pool.storage.upsert_many(validated)
        return jsonify({"status": "ok", "count": len(to_validate)})
    elif action == "mark_alive":
        t = _time.time()
        pool.storage.mark_alive_batch(ids, t)
        return jsonify({"status": "ok", "count": len(ids)})
    return jsonify({"error": f"未知操作: {action}"}), 400


@api_bp.route("/proxies/<int:proxy_id>/favorite", methods=["POST"])
def toggle_favorite(proxy_id):
    """切换收藏状态"""
    pool = get_pool()
    result = pool.storage.toggle_favorite(proxy_id)
    return jsonify({"status": "ok", "favorite": result})


@api_bp.route("/favorites", methods=["GET"])
def list_favorites():
    """获取收藏列表"""
    pool = get_pool()
    proxies = pool.storage.get_favorites()
    return jsonify([p.dict for p in proxies])


# ── 代理分组 ──

@api_bp.route("/groups", methods=["GET"])
def list_groups():
    """获取所有分组"""
    pool = get_pool()
    return jsonify(pool.storage.get_groups())


@api_bp.route("/groups", methods=["POST"])
def create_group():
    """创建新分组"""
    pool = get_pool()
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    if not name:
        return jsonify({"error": "名称不能为空"}), 400
    try:
        gid = pool.storage.create_group(name, **data)
        return jsonify({"status": "ok", "id": gid})
    except Exception:
        return jsonify({"error": "名称已存在"}), 409


@api_bp.route("/groups/<int:group_id>", methods=["DELETE"])
def delete_group(group_id):
    """删除分组"""
    pool = get_pool()
    pool.storage.delete_group(group_id)
    return jsonify({"status": "ok"})


@api_bp.route("/groups/<int:group_id>/proxies", methods=["GET"])
def get_group_proxies(group_id):
    """获取分组下的代理列表（从持久化关联表读取）"""
    pool = get_pool()
    group = pool.storage.get_group(group_id)
    if not group:
        return jsonify({"error": "分组不存在"}), 404
    proxies = pool.storage.get_group_proxies(group_id)
    return jsonify([p.dict for p in proxies])


@api_bp.route("/groups/<int:group_id>/proxies", methods=["POST"])
def add_to_group(group_id):
    """将代理添加到分组"""
    pool = get_pool()
    data = request.get_json(silent=True) or {}
    ids = [int(i) for i in data.get("ids", [])]
    if not ids:
        return jsonify({"error": "缺少 ids"}), 400
    count = pool.storage.add_to_group(group_id, ids)
    return jsonify({"status": "ok", "added": count})


@api_bp.route("/groups/<int:group_id>/proxies/<int:proxy_id>", methods=["DELETE"])
def remove_from_group(group_id, proxy_id):
    """从分组移除代理"""
    pool = get_pool()
    pool.storage.remove_from_group(group_id, [proxy_id])
    return jsonify({"status": "ok"})


@api_bp.route("/groups/<int:group_id>/populate", methods=["POST"])
def populate_group(group_id):
    """重新按筛选条件填充分组"""
    pool = get_pool()
    count = pool.storage.populate_group(group_id)
    return jsonify({"status": "ok", "populated": count})


# ── 工具集成模板 ──

@api_bp.route("/tool-templates", methods=["GET"])
def tool_templates():
    """获取各工具的代理配置模板"""
    pool = get_pool()
    proxy = pool.get(strategy="lowest_latency")
    addr = f"{proxy.ip}:{proxy.port}" if proxy else "127.0.0.1:1080"
    proto = proxy.protocol if proxy else "socks5"

    return jsonify({
        "burp": {
            "name": "Burp Suite",
            "config": f"Settings → Network → Connections\n上游代理: 127.0.0.1:5000 (HTTP)\n方向: 所有目标 → 上游代理"
        },
        "python": {
            "name": "Python requests",
            "config": f"proxies = {{'http': '{proto}://{addr}', 'https': '{proto}://{addr}'}}\n" +
                      f"session = requests.Session()\nsession.proxies.update(proxies)"
        },
        "selenium": {
            "name": "Selenium",
            "config": f"from selenium import webdriver\n" +
                      f"opts = webdriver.ChromeOptions()\n" +
                      f"opts.add_argument('--proxy-server={proto}://{addr}')"
        },
        "scrapy": {
            "name": "Scrapy",
            "config": f"# settings.py\nROTATING_PROXY_LIST = ['{proto}://{addr}']\n" +
                      f"DOWNLOADER_MIDDLEWARES = {{\n    'rotating_proxies.middlewares.RotatingProxyMiddleware': 610,\n}}"
        },
        "curl": {
            "name": "curl 命令行",
            "config": f"curl --proxy {proto}://{addr} https://httpbin.org/ip\n" +
                      f"# 或设置环境变量:\nexport HTTP_PROXY={proto}://{addr}\nexport HTTPS_PROXY={proto}://{addr}"
        },
        "proxychains": {
            "name": "Proxychains",
            "config": f"# /etc/proxychains4.conf\n[ProxyList]\n{proto} {proxy.ip if proxy else '127.0.0.1'} {proxy.port if proxy else 1080}"
        },
        "sqlmap": {
            "name": "sqlmap",
            "config": f"# 使用代理池进行SQL注入扫描\nsqlmap -u \"http://target.com/page.php?id=1\" \\\n"
                      f"  --proxy={proto}://{addr} \\\n"
                      f"  --random-agent \\\n"
                      f"  --batch\n\n"
                      f"# 使用tor代理 + 代理池轮换器\n"
                      f"sqlmap -u \"http://target.com/page.php?id=1\" \\\n"
                      f"  --proxy=http://127.0.0.1:5000 \\\n"
                      f"  --check-tor \\\n"
                      f"  --random-agent"
        },
        "dirsearch": {
            "name": "dirsearch",
            "config": f"# 使用代理池进行目录扫描\n"
                      f"dirsearch -u http://target.com \\\n"
                      f"  --proxy={proto}://{addr} \\\n"
                      f"  -e php,asp,aspx,jsp,js,txt,bak,zip \\\n"
                      f"  --random-agent \\\n"
                      f"  -t 30\n\n"
                      f"# 或通过轮换器使用动态IP\n"
                      f"dirsearch -u http://target.com \\\n"
                      f"  --proxy=http://127.0.0.1:5000 \\\n"
                      f"  -e php,asp,aspx,jsp,conf,bak \\\n"
                      f"  --random-agent"
        },
    })


# ── 出口IP轮换 API ──

@api_bp.route("/rotator/start", methods=["POST"])
def rotator_start():
    """启动轮换代理服务"""
    try:
        rotator = get_rotator()
        if rotator._running:
            return jsonify({"status": "already_running", **rotator.status})
        # 从请求体读取配置
        data = request.get_json(silent=True) or {}
        port = data.get("port", 5000)
        interval = data.get("interval", 60)
        protocol = data.get("protocol", "")
        country = data.get("country", "")
        max_latency = data.get("max_latency", 0)

        rotator.port = port
        rotator.interval = interval
        rotator.protocol = protocol
        rotator.country = country
        rotator.max_latency = max_latency

        rotator.start_service()
        return jsonify({"status": "started", **rotator.status})
    except Exception:
        import traceback
        return jsonify({"status": "error", "traceback": traceback.format_exc()}), 500


@api_bp.route("/rotator/stop", methods=["POST"])
def rotator_stop():
    """停止轮换代理服务"""
    rotator = get_rotator()
    if not rotator._running:
        return jsonify({"status": "not_running"})
    rotator.stop_service()
    return jsonify({"status": "stopped"})


@api_bp.route("/rotator/status", methods=["GET"])
def rotator_status():
    """获取轮换器当前状态"""
    rotator = get_rotator()
    return jsonify(rotator.status)


@api_bp.route("/rotator/rotate", methods=["POST"])
def rotator_rotate():
    """手动触发一次立即轮换"""
    rotator = get_rotator()
    if not rotator._running:
        return jsonify({"error": "轮换服务未运行"}), 400
    proxy = rotator.rotate()
    if proxy:
        return jsonify({"status": "ok", "current_proxy": proxy.dict})
    return jsonify({"error": "轮换失败，无可用的代理"}), 500


@api_bp.route("/rotator/pin", methods=["POST"])
def rotator_pin():
    """固定使用指定代理，停止自动轮换"""
    rotator = get_rotator()
    data = request.get_json(silent=True) or {}
    proxy_id = data.get("proxy_id", 0)
    if not proxy_id:
        return jsonify({"error": "缺少 proxy_id"}), 400
    ok = rotator.pin(int(proxy_id))
    if ok:
        return jsonify({"status": "ok", "pinned": rotator.is_pinned, "current_proxy": rotator.current_proxy.dict})
    return jsonify({"error": "代理不存在或已失效"}), 404


@api_bp.route("/rotator/unpin", methods=["POST"])
def rotator_unpin():
    """取消固定，恢复自动轮换"""
    rotator = get_rotator()
    rotator.unpin()
    # 恢复定时轮换
    rotator._schedule_rotate()
    return jsonify({"status": "ok", "pinned": False})


@api_bp.route("/rotator/config", methods=["PUT"])
def rotator_config():
    """更新轮换配置（间隔、协议等），下次轮换生效"""
    rotator = get_rotator()
    data = request.get_json(silent=True) or {}
    if "interval" in data:
        rotator.interval = int(data["interval"])
    if "protocol" in data:
        rotator.protocol = data["protocol"]
    if "country" in data:
        rotator.country = data["country"]
    if "max_latency" in data:
        rotator.max_latency = float(data["max_latency"])
    if "use_verified_only" in data:
        rotator.use_verified_only = bool(data["use_verified_only"])
    return jsonify({"status": "ok", "config": {
        "interval": rotator.interval,
        "protocol": rotator.protocol,
        "country": rotator.country,
        "max_latency": rotator.max_latency,
        "use_verified_only": rotator.use_verified_only,
    }})


# ── 出口IP轮换测试 API ──

_running_test_id = None


@api_bp.route("/rotation-test/start", methods=["POST"])
def rotation_test_start():
    """启动轮换测试：定期通过轮换器发请求检测出口IP是否变化"""
    global _running_test_id
    pool = get_pool()
    rotator = get_rotator()
    if not rotator._running:
        return jsonify({"error": "请先启动轮换服务"}), 400

    data = request.get_json(silent=True) or {}
    duration = min(data.get("duration", 60), 600)  # 最长 10 分钟
    interval = min(data.get("interval", 5), 30)     # 最短 1 秒
    target = data.get("target_url", "http://httpbin.org/ip")

    test_id = pool.start_rotation_test(duration=duration, interval=interval, target_url=target, rotator_port=rotator.port)
    _running_test_id = test_id
    return jsonify({
        "test_id": test_id,
        "duration": duration,
        "interval": interval,
        "target_url": target,
    })


@api_bp.route("/rotation-test/status", methods=["GET"])
def rotation_test_status():
    """获取轮换测试当前状态和结果"""
    pool = get_pool()
    test_id = request.args.get("test_id", type=int)
    tid = test_id or _running_test_id
    if not tid:
        return jsonify({"error": "没有正在运行的测试"}), 404

    result = pool.get_rotation_test(tid)
    if not result:
        return jsonify({"error": "测试不存在"}), 404

    # 序列化为 JSON 安全的格式
    return jsonify({
        "test_id": tid,
        "running": result["running"],
        "duration": result["duration"],
        "interval": result["interval"],
        "elapsed": round(result["requests"][-1]["time"] - result["start_time"], 1) if result["requests"] else 0,
        "total_requests": len(result["requests"]),
        "success_count": sum(1 for r in result["requests"] if r["success"]),
        "fail_count": sum(1 for r in result["requests"] if not r["success"]),
        "unique_ips": len(result["unique_ips"]),
        "rotate_count": result["rotate_count"],
        "current_ip": result["last_ip"],
        "avg_latency": round(
            sum(r["latency_ms"] for r in result["requests"] if r["latency_ms"] > 0) /
            max(1, sum(1 for r in result["requests"] if r["latency_ms"] > 0)), 1
        ) if any(r["latency_ms"] > 0 for r in result["requests"]) else 0,
        "requests": result["requests"][-50:],  # 最近 50 条
        "test_all_mode": result.get("test_all_mode", False),
        "total_to_test": result.get("total_to_test", 0),
        "verified_count": len(get_pool()._verified_proxy_ids),
    })


@api_bp.route("/rotation-test/test-all", methods=["POST"])
def rotation_test_all():
    """全量测试所有存活代理：逐个代理请求目标URL，通过者加入已验证列表"""
    global _running_test_id
    pool = get_pool()
    data = request.get_json(silent=True) or {}
    target = data.get("target_url", "http://cip.cc")

    test_id = pool.test_all_proxies(target_url=target)
    _running_test_id = test_id
    return jsonify({
        "test_id": test_id,
        "target_url": target,
        "total_proxies": len(pool.list(status="alive", limit=1000)),
    })


@api_bp.route("/verified-proxies", methods=["GET"])
def verified_proxies():
    """获取已验证通过的代理列表"""
    pool = get_pool()
    proxies = pool.get_verified_proxies()
    return jsonify([p.dict for p in proxies])


@api_bp.route("/verified-proxies", methods=["DELETE"])
def clear_verified_proxies():
    """清空已验证代理列表"""
    pool = get_pool()
    pool.clear_verified_proxies()
    return jsonify({"status": "ok"})


@api_bp.route("/rotation-test/stop", methods=["POST"])
def rotation_test_stop():
    """停止轮换测试"""
    global _running_test_id
    pool = get_pool()
    tid = _running_test_id
    if not tid:
        return jsonify({"error": "没有正在运行的测试"}), 404
    pool.stop_rotation_test(tid)
    _running_test_id = None
    return jsonify({"status": "stopped"})


@api_bp.route("/rotation-test/clear", methods=["DELETE"])
def rotation_test_clear():
    """清除测试记录并重置UI状态"""
    global _running_test_id
    pool = get_pool()
    tid = request.args.get("test_id", type=int) or _running_test_id
    if tid:
        pool.stop_rotation_test(tid)
        pool.clear_test_results(tid)
        _running_test_id = None
    return jsonify({"status": "cleared"})


# ── Nmap 扫描 API ──

@api_bp.route("/nmap/scan", methods=["POST"])
def nmap_scan():
    """启动 nmap 代理发现扫描"""
    pool = get_pool()
    data = request.get_json(silent=True) or {}
    targets = data.get("targets", "")
    if not targets:
        return jsonify({"error": "请输入扫描目标，如 192.168.1.0/24"}), 400
    ports = data.get("ports", [])
    rate = data.get("rate", 3000)

    from ..nmap_scanner import discover_proxies
    import asyncio

    proxies = asyncio.run(discover_proxies(
        targets=targets,
        ports=ports if ports else None,
        rate=rate,
    ))
    if proxies:
        pool.storage.upsert_many(proxies)
    return jsonify({
        "status": "ok",
        "discovered": len(proxies),
        "proxies": [p.dict for p in proxies],
    })


@api_bp.route("/nmap/quick-scan", methods=["POST"])
def nmap_quick_scan():
    """一键扫描公网代理（无需输入IP范围）"""
    pool = get_pool()
    data = request.get_json(silent=True) or {}
    ip_count = data.get("ip_count", 200)
    rate = data.get("rate", 3000)

    from ..nmap_scanner import quick_scan
    import asyncio

    proxies = asyncio.run(quick_scan(ip_count=ip_count, rate=rate))
    if proxies:
        pool.storage.upsert_many(proxies)
    return jsonify({
        "status": "ok",
        "scanned_ips": ip_count,
        "discovered": len(proxies),
        "proxies": [p.dict for p in proxies],
    })


@api_bp.route("/nmap/check", methods=["GET"])
def nmap_check():
    """检查 nmap 是否可用"""
    from ..nmap_scanner import find_nmap
    path = find_nmap()
    return jsonify({"available": path is not None, "path": path})


# ── 系统代理开关 API ──

from ..system_proxy import enable as sys_proxy_enable, disable as sys_proxy_disable, status as sys_proxy_status


@api_bp.route("/system-proxy/enable", methods=["POST"])
def system_proxy_enable():
    """开启 Windows 系统代理，指向轮换器地址（需轮换已启动）"""
    rotator = get_rotator()
    if not rotator._running:
        return jsonify({"error": "请先启动轮换服务再开启系统代理"}), 400
    data = request.get_json(silent=True) or {}
    addr = data.get("addr", "127.0.0.1:5000")
    sys_proxy_enable(addr)
    return jsonify({"status": "ok", "enabled": True, "server": addr})


@api_bp.route("/system-proxy/disable", methods=["POST"])
def system_proxy_disable():
    """关闭 Windows 系统代理"""
    sys_proxy_disable()
    return jsonify({"status": "ok", "enabled": False})


@api_bp.route("/system-proxy/status", methods=["GET"])
def system_proxy_status():
    """查询 Windows 系统代理状态"""
    return jsonify(sys_proxy_status())
