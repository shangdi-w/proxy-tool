#!/usr/bin/env python
"""代理池 CLI - 全球代理抓取、验证与管理工具"""

import time
import click

from proxypool import ProxyPool


@click.group()
@click.option("--db", default="", help="SQLite数据库路径", envvar="PROXY_POOL_DB")
@click.option("--mysql/--no-mysql", default=True, help="使用MySQL存储 (默认: 启用)")
@click.option("--mysql-host", default="127.0.0.1", help="MySQL地址")
@click.option("--mysql-port", default=3306, help="MySQL端口")
@click.option("--mysql-user", default="root", help="MySQL用户")
@click.option("--mysql-password", default="root", help="MySQL密码")
@click.option("--mysql-db", default="proxy_pool", help="MySQL数据库名")
@click.pass_context
def cli(ctx, db, mysql, mysql_host, mysql_port, mysql_user, mysql_password, mysql_db):
    ctx.ensure_object(dict)
    mysql_cfg = {
        "host": mysql_host, "port": mysql_port,
        "user": mysql_user, "password": mysql_password,
        "database": mysql_db,
    }
    ctx.obj["pool"] = ProxyPool(
        db_path=db, use_mysql=mysql, mysql_cfg=mysql_cfg
    )


@cli.command()
@click.option("--port", default=8888, help="Web面板端口号")
@click.option("--host", default="127.0.0.1", help="绑定地址")
@click.pass_context
def web(ctx, port, host):
    """启动Web管理面板"""
    from proxypool.web.app import create_app
    pool = ctx.obj["pool"]
    pool.start()
    app = create_app()
    click.echo(f"\n  管理面板: http://{host}:{port}\n")
    app.run(host=host, port=port, debug=False)


@cli.command()
@click.pass_context
def scrape(ctx):
    """从公开源抓取代理并存入数据库"""
    pool = ctx.obj["pool"]
    click.echo("正在从公开源抓取代理...")
    pool.scrape_now()
    counts = pool.storage.count()
    click.echo(f"完成。总计: {counts['total']}, 存活: {counts['alive']}, "
               f"失效: {counts['dead']}, 未知: {counts['unknown']}")


@cli.command()
@click.pass_context
def validate(ctx):
    """验证所有待检测的代理"""
    pool = ctx.obj["pool"]
    click.echo("正在验证代理...")
    count = pool.validate_all()
    click.echo(f"已验证 {count} 个代理。")


@cli.command()
@click.pass_context
def status(ctx):
    """查看代理池统计信息"""
    pool = ctx.obj["pool"]
    stats = pool.stats
    click.echo(f"总计:     {stats['total']}")
    click.echo(f"存活:     {stats['alive']}")
    click.echo(f"失效:     {stats['dead']}")
    click.echo(f"未知:     {stats['unknown']}")
    click.echo(f"平均延迟: {stats['avg_latency']}ms")
    click.echo(f"覆盖国家: {stats['countries']}")


@cli.command()
@click.option("--protocol", default="", help="协议筛选 (http, https, socks4, socks5)")
@click.option("--country", default="", help="国家代码筛选 (US, CN 等)")
@click.option("--limit", default=10, help="显示数量")
@click.pass_context
def get(ctx, protocol, country, limit):
    """从代理池获取可用代理"""
    pool = ctx.obj["pool"]
    proxies = pool.list(protocol=protocol, country=country, status="alive", limit=limit)
    if not proxies:
        click.echo("没有找到存活代理。")
        return
    click.echo(f"{'IP:端口':<24} {'协议':<8} {'国家':<8} {'延迟':<10} {'来源'}")
    click.echo("-" * 80)
    for p in proxies:
        lat = f"{p.latency:.0f}ms" if p.latency > 0 else "-"
        click.echo(f"{p.ip}:{p.port:<6} {p.protocol:<8} {p.country or '-':<8} {lat:<10} {p.source}")


@cli.command()
@click.option("--port", default=5000, help="本地监听端口")
@click.option("--interval", default=60, help="轮换间隔(秒)")
@click.option("--protocol", default="", help="上游代理协议筛选")
@click.option("--country", default="", help="上游代理国家筛选")
@click.option("--max-latency", default=0, type=float, help="最大延迟限制(ms)")
@click.pass_context
def rotate(ctx, port, interval, protocol, country, max_latency):
    """启动本地出口IP轮换代理服务"""
    from proxypool.rotator import Rotator
    pool = ctx.obj["pool"]
    pool.start()

    rotator = Rotator(pool, port=port, interval=interval,
                      protocol=protocol, country=country, max_latency=max_latency)
    rotator.start_service()
    proxy = rotator.current_proxy
    click.echo(f"\n  轮换代理已启动!")
    click.echo(f"  本地地址:  http://127.0.0.1:{port}")
    click.echo(f"  轮换间隔:  {interval}秒")
    click.echo(f"  当前出口:  {proxy.ip}:{proxy.port}" if proxy else "  当前出口:  暂无")
    click.echo(f"\n  将浏览器/系统代理设为 127.0.0.1:{port} 即可使用")
    click.echo(f"  按 Ctrl+C 停止\n")

    try:
        while rotator._running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        rotator.stop_service()
        click.echo("已停止轮换服务。")


@cli.command()
@click.pass_context
def clean(ctx):
    """删除所有失效代理"""
    pool = ctx.obj["pool"]
    count = pool.clean()
    click.echo(f"已删除 {count} 个失效代理。")


if __name__ == "__main__":
    cli()
