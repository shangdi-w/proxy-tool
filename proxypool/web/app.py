"""Flask Web 应用 - 代理池管理面板"""

from flask import Flask

from ..pool import ProxyPool
from ..rotator import Rotator

_pool: ProxyPool = None
_rotator: Rotator = None

# 默认使用 MySQL 存储（保存历史数据）
USE_MYSQL = True
MYSQL_CFG = {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "root", "database": "proxy_pool"}


def get_pool() -> ProxyPool:
    """获取全局代理池实例（懒加载，自动启动后台线程）"""
    global _pool
    if _pool is None:
        _pool = ProxyPool(use_mysql=USE_MYSQL, mysql_cfg=MYSQL_CFG)
        _pool.start()
    return _pool


def get_rotator() -> Rotator:
    """获取全局轮换器实例（自动重建已停止的线程）"""
    global _rotator
    if _rotator is None or not _rotator.is_alive():
        _rotator = Rotator(get_pool())
    return _rotator


def create_app() -> Flask:
    """创建 Flask 应用"""
    app = Flask(__name__, template_folder="templates", static_folder="static")

    from .api import api_bp
    app.register_blueprint(api_bp)

    from flask import render_template

    @app.route("/")
    def index():
        """仪表盘首页"""
        return render_template("index.html")

    return app
