# 代理池-石路 — 全球代理抓取·验证·轮换管理工具

面向**渗透测试**和**安全研究**的高性能代理池。支持 HTTP/HTTPS/SOCKS4/SOCKS5 全协议，内置 25+ 个代理源（含国内渗透专用源），提供 Web 管理面板、本地代理轮换服务、Nmap 代理发现、一键系统代理切换。

## 核心功能

| 功能 | 说明 |
|------|------|
| **多源抓取** | 22 个全球源 + 4 个国内渗透测试专用源，异步并发抓取 |
| **协议全覆盖** | HTTP / HTTPS / SOCKS4 / SOCKS5 全支持 |
| **智能验证** | 延迟检测 + 匿名度分级 (elite/anonymous/transparent) + CONNECT 隧道测试 |
| **健康评分** | 综合加权评分 (延迟 40% + 失败数 30% + CONNECT 10% + 新鲜度 20%) |
| **延迟过滤** | 自动过滤延迟 > 2500ms 的代理，仅保留低延迟节点 |
| **已验证IP列表** | 全量测试所有存活代理，通过者加入白名单，轮换器可仅使用已验证IP |
| **出口IP轮换** | 本地 HTTP 转发代理，支持定时/按请求数轮换，请求级会话保持 |
| **自动失效清理** | 3 次连续失败自动标记失效，启动时自动清理 |
| **Web 面板** | Flask + Bootstrap 5 暗色主题，实时统计、批量操作、导出 |
| **一键系统代理** | Windows 系统代理一键开关，指向轮换器 |
| **分组管理** | 持久化代理分组，支持筛选条件 + 手动添加，MySQL/SQLite 双存储 |
| **Nmap 扫描** | 内置 Nmap 集成，扫描 IP 段发现隐藏代理，支持一键扫描公网 VPS |
| **Burp 轮换测试** | 一键验证出口IP是否正常轮换，支持国内IP检测服务 |
| **双存储** | SQLite (轻量/零配置) + MySQL (历史数据/统计/分组持久化) |
| **CN 专项** | 国内代理统计 API、快代理/89ip/小幻/fate0 等国内源 |
| **工具集成** | Burp Suite / sqlmap / dirsearch / Python / Selenium / Scrapy / curl / Proxychains 配置模板 |
| **批量导出** | JSON / CSV / TXT / Proxychains 格式，支持按选中导出 |
| **右键菜单** | 固定使用、复制地址/URL、快捷操作 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动 Web 面板 (默认 MySQL)

```bash
python cli.py web --port 8888
```

面板地址: http://127.0.0.1:8888

### 3. 使用 SQLite (无需 MySQL)

```bash
python cli.py --no-mysql web --port 8888
```

### 4. 启动出口IP轮换代理

```bash
python cli.py rotate --port 5000 --interval 60
```

然后将浏览器/系统代理设为 `127.0.0.1:5000` 即可使用。

## MySQL 配置

### 安装 MySQL Server

Windows 用户推荐使用 MySQL Installer: https://dev.mysql.com/downloads/installer/

或使用 Docker:
```bash
docker run -d --name mysql-proxy \
  -e MYSQL_ROOT_PASSWORD=root \
  -e MYSQL_DATABASE=proxy_pool \
  -p 3306:3306 \
  mysql:8.0
```

### 创建数据库

MySQL 连接后会自动创建 `proxy_pool` 数据库，无需手动建库。

### 配置连接参数

```bash
python cli.py web \
  --mysql-host 127.0.0.1 \
  --mysql-port 3306 \
  --mysql-user root \
  --mysql-password root \
  --mysql-db proxy_pool
```

也可以通过环境变量配置：
```bash
set PROXY_POOL_DB=                            # SQLite 路径 (留空=默认)
set MYSQL_HOST=127.0.0.1
set MYSQL_PORT=3306
set MYSQL_USER=root
set MYSQL_PASSWORD=root
set MYSQL_DATABASE=proxy_pool
```

MySQL 提供的能力：
- **历史数据统计** — 按天统计抓取量、存活率趋势
- **国内代理专项分析** — CN 代理延迟/可用率/存活率
- **分组持久化** — 分组和关联关系持久保存，重启不丢失

## SQLite 模式

无需安装任何数据库，开箱即用。数据库文件 `proxies.db` 自动创建在项目目录下。

```bash
python cli.py --no-mysql web --port 8888
```

**注意：** SQLite 模式下不支持历史数据统计和国内代理专项分析。

## CLI 命令

```
python cli.py web         启动 Web 管理面板
python cli.py scrape      手动抓取代理
python cli.py validate    验证所有待检测代理
python cli.py status      查看代理池统计
python cli.py get         获取可用代理列表
python cli.py rotate      启动出口IP轮换代理服务
python cli.py clean       删除所有失效代理
```

### 示例

```bash
# 查看统计
python cli.py --no-mysql status

# 获取 SOCKS5 代理列表
python cli.py get --protocol socks5 --limit 20

# 获取美国代理
python cli.py get --country US --limit 10

# 启动轮换器（SOCKS5 上游、最大延迟 2000ms）
python cli.py rotate --port 5000 --interval 30 --protocol socks5 --max-latency 2000
```

## 工具集成配置

### sqlmap

```bash
# 通过单个代理
sqlmap -u "http://target.com/page.php?id=1" \
  --proxy=socks5://127.0.0.1:1080 \
  --random-agent \
  --batch

# 通过轮换器（动态IP）
sqlmap -u "http://target.com/page.php?id=1" \
  --proxy=http://127.0.0.1:5000 \
  --check-tor \
  --random-agent
```

### dirsearch

```bash
# 通过轮换器使用动态IP
dirsearch -u http://target.com \
  --proxy=http://127.0.0.1:5000 \
  -e php,asp,aspx,jsp,conf,bak \
  --random-agent \
  -t 30
```

### Burp Suite

1. Settings → Network → Connections
2. 上游代理: `127.0.0.1:5000` (HTTP)
3. 方向: 所有目标 → 上游代理

### Python requests

```python
proxies = {'http': 'socks5://127.0.0.1:1080', 'https': 'socks5://127.0.0.1:1080'}
session = requests.Session()
session.proxies.update(proxies)
resp = session.get('https://httpbin.org/ip')
```

### Proxychains

```bash
# /etc/proxychains4.conf
[ProxyList]
socks5 127.0.0.1 1080
```

## Web 面板功能

### 仪表盘
- 实时统计卡片：总数 · 存活 · 失效 · 平均延迟 · 高匿数 · CONNECT 数
- Sparkline 趋势图（最近20次采样）
- 历史数据面板（MySQL，最近7天统计）

### 代理管理
- 多维度筛选：协议 / 国家 / 状态 / 延迟 / 排序 / 数量
- 快捷筛选标签：收藏、低延迟(<500ms)、高匿、US、CN、SOCKS5
- 场景筛选：爬虫 / API / 流媒体 / 隐身
- 批量操作：验证选中、删除选中、导出 JSON/CSV/TXT/Proxychains
- 右键菜单：固定使用、复制 IP:端口、复制代理URL
- 列可见性切换（协议/国家/匿名度/来源），本地持久化
- 收藏功能

### 出口IP轮换
- 启停控制、间隔/协议/国家/延迟配置（手动输入）
- 当前出口代理详情展示（地址、国家、延迟、匿名度、来源）
- 倒计时进度条
- 固定/取消固定代理
- 一键开启/关闭 Windows 系统代理
- 立即切换按钮

### 工具集成
- Burp Suite / sqlmap / dirsearch / Python requests / Selenium / Scrapy / curl / Proxychains 配置模板
- 一键复制配置命令

### Burp 轮换测试 & 全量代理测试
- 一键验证出口IP轮换是否生效
- 支持多个国内IP检测服务：cip.cc、ipip.net、ip.sb、httpbin.org/ip
- 支持自定义检测URL
- 实时显示请求日志、唯一IP数、轮换次数、成功率
- **全量测试模式**：逐个测试所有存活代理，自动将通过的代理加入"已验证列表"
- 轮换器可切换"仅验证IP"模式，只使用已验证通过的代理

### Nmap 代理发现
- 手动模式：输入 IP/CIDR + 端口 + 扫描速率
- 一键公网扫描：随机扫描 DigitalOcean/Vultr/Linode/AWS/GCP/OVH CIDR 段
- 自动验证发现端口是否为可用代理
- 发现的代理自动存入数据库

### 代理分组
- 创建分组：名称 + 协议/国家/延迟/匿名度筛选条件
- 自动填充匹配代理
- 手动添加/移除代理
- 分组查看、刷新（重新匹配）、删除

## API 概览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/proxies` | GET | 查询代理列表，支持 protocol/country/status/sort_by/limit/max_latency |
| `/api/proxies/random` | GET | 随机获取活代理，支持 strategy=random/round_robin/lowest_latency |
| `/api/proxies/count` | GET | 各状态数量统计 |
| `/api/proxies` | DELETE | 删除失效代理 |
| `/api/proxies/batch` | POST | 批量操作：validate / delete / mark_alive |
| `/api/proxies/<id>/favorite` | POST | 切换收藏状态 |
| `/api/favorites` | GET | 获取收藏列表 |
| `/api/scrape` | POST | 手动触发抓取 |
| `/api/validate` | POST | 触发全量验证 |
| `/api/validate-connect` | POST | CONNECT 支持重检 |
| `/api/verify-anonymity` | POST | 匿名度深度验证 |
| `/api/export?format=json` | GET/POST | 导出 (json/csv/txt/proxychains)，POST 支持按 ID 批量导出 |
| `/api/stats` | GET | 综合统计 (含 avg_latency/elite_count/connect_count) |
| `/api/countries` | GET | 有代理的国家列表 |
| `/api/history?days=7` | GET | 按天历史统计 (MySQL) |
| `/api/cn-stats` | GET | 中国代理专项统计 (MySQL) |
| `/api/groups` | GET/POST | 分组列表 / 创建分组 |
| `/api/groups/<id>` | DELETE | 删除分组 |
| `/api/groups/<id>/proxies` | GET/POST | 分组代理列表 / 添加代理到分组 |
| `/api/groups/<id>/proxies/<pid>` | DELETE | 从分组移除代理 |
| `/api/groups/<id>/populate` | POST | 重新按条件填充分组 |
| `/api/rotator/start` | POST | 启动轮换服务，body: {port, interval, protocol, country, max_latency} |
| `/api/rotator/stop` | POST | 停止轮换服务 |
| `/api/rotator/status` | GET | 轮换状态 (当前代理/下次切换/轮换次数/配置) |
| `/api/rotator/rotate` | POST | 手动立即轮换 |
| `/api/rotator/pin` | POST | 固定代理 {proxy_id} |
| `/api/rotator/unpin` | POST | 取消固定 |
| `/api/rotator/config` | PUT | 更新轮换配置 {interval, protocol, country, max_latency} |
| `/api/rotation-test/start` | POST | 启动轮换测试 {duration, interval, target_url} |
| `/api/rotation-test/test-all` | POST | 全量测试所有存活代理 {target_url} |
| `/api/rotation-test/status` | GET | 轮换测试结果 (含 verified_count / test_all_mode) |
| `/api/rotation-test/stop` | POST | 停止轮换测试 |
| `/api/verified-proxies` | GET | 获取已验证代理列表 |
| `/api/verified-proxies` | DELETE | 清空已验证列表 |
| `/api/nmap/scan` | POST | Nmap 手动扫描 {targets, ports, rate} |
| `/api/nmap/quick-scan` | POST | Nmap 一键公网扫描 {ip_count, rate} |
| `/api/nmap/check` | GET | 检查 nmap 是否可用 |
| `/api/system-proxy/enable` | POST | 开启 Windows 系统代理 {addr} |
| `/api/system-proxy/disable` | POST | 关闭系统代理 |
| `/api/system-proxy/status` | GET | 查询系统代理状态 |
| `/api/auto-scrape/start` | POST | 启动自动抓取 {interval} |
| `/api/auto-scrape/stop` | POST | 停止自动抓取 |
| `/api/auto-scrape/status` | GET | 自动抓取状态 {running, interval, last_scrape_time, last_scrape_count} |
| `/api/tool-templates` | GET | 工具集成配置模板 (8种工具) |

## 项目结构

```
proxy_pool/
├── cli.py                    CLI 入口 (Click)
├── setup.py                  安装配置
├── requirements.txt          依赖声明
├── README.md                 本文件
├── LICENSE                   MIT
├── proxypool/
│   ├── __init__.py           包导出
│   ├── models.py             代理数据模型 (Proxy dataclass, 健康评分)
│   ├── pool.py               代理池管理器 (调度抓取/验证/轮换/健康检查)
│   ├── storage.py            SQLite 存储 (完整 CRUD + 分组)
│   ├── mysql_storage.py      MySQL 存储 (历史数据 + CN统计 + 分组持久化)
│   ├── scraper.py            25+ 个代理源 (22全球 + 4国内)
│   ├── validator.py          异步代理验证 (延迟/匿名度/CONNECT)
│   ├── rotator.py            出口IP轮换 HTTP 转发代理
│   ├── nmap_scanner.py       Nmap 集成代理发现 + 一键公网扫描
│   ├── system_proxy.py       Windows 系统代理控制 (注册表)
│   ├── nmap/                 内置 Nmap 可执行文件 (7.97)
│   └── web/
│       ├── __init__.py
│       ├── app.py            Flask 应用工厂
│       ├── api.py            完整 REST API (40+ 端点)
│       ├── templates/
│       │   └── index.html    管理面板 HTML
│       └── static/
│           ├── app.js        前端逻辑 (Vue-style 数据绑定)
│           └── style.css     Material 暗色主题
```

## 代理源列表

### 全球源（22 个）
| 源 | 协议 | 特点 |
|----|------|------|
| ProxyScrape API v2 | HTTP/HTTPS/SOCKS4/SOCKS5 | 大量免费代理 |
| GeoNode API | HTTP/HTTPS/SOCKS4/SOCKS5 | 含国家/延迟/匿名度 |
| FreeProxyList | HTTP/HTTPS | 网页表格解析 |
| Proxy-List.download API | HTTP/HTTPS/SOCKS4/SOCKS5 | 多协议 |
| GitHub TheSpeedX PROXY-List | HTTP/SOCKS4/SOCKS5 | 开源代理列表 |
| GitHub TheSpeedX SOCKS-List | HTTP/SOCKS4/SOCKS5 | SOCKS 专项 |
| OpenProxy.space API | HTTP | 含国家标记 |
| ALIILAPRO/Proxy | HTTP/HTTPS/SOCKS4/SOCKS5 | GitHub 大量代理 |
| monosans/proxy-list | HTTP/HTTPS/SOCKS4/SOCKS5 | JSON格式+Geo信息 |
| roosterkid/openproxylist | HTTPS/SOCKS4/SOCKS5 | 分类清晰 |
| hookzof/socks5_list | SOCKS5 | SOCKS5 专项 |
| jetkai/proxy-list | HTTP/HTTPS/SOCKS | 在线代理TXT |
| sunny9577/proxy-scraper | HTTP/HTTPS/SOCKS | 多协议格式 |
| mmpx12/proxy-list | HTTP/HTTPS/SOCKS4/SOCKS5 | 四协议分类 |
| PubProxy API | HTTP/SOCKS4/SOCKS5 | JSON API |
| ProxiFly API | HTTP/HTTPS/SOCKS | 最新代理 |
| muhamed77/Proxy-List | HTTP/HTTPS/SOCKS4/SOCKS5 | GitHub 多协议 |
| clarketm/proxy-list | HTTP | 精选列表 |
| hyperreality/proxy-list | HTTP | 经典代理列表 |
| themiralay/Proxy-List | HTTP/SOCKS4/SOCKS5 | GitHub 代理 |

### 国内渗透专用源（4 个）
| 源 | 协议 | 特点 |
|----|------|------|
| 快代理 (kuaidaili) | HTTP/HTTPS | 国内免费代理 |
| 89免费代理 (89ip) | HTTP | 国内 IP |
| 小幻代理 (ihuan) | HTTP/HTTPS/SOCKS5 | 国内代理聚合 |
| fate0 proxylist | HTTP/HTTPS/SOCKS | GitHub 开源列表 |

## 健康评分算法

评分 0-100，加权计算：

- **延迟分 (40%)** — `40 × (1 - latency/5000)`，延迟越低越好
- **失败分 (30%)** — `30 × (1 - fail_count/5)`，连续失败越少越好
- **CONNECT 支持 (10%)** — 支持 CONNECT 隧道得 10 分
- **新鲜度 (20%)** — `20 × (1 - age_hours/24)`，24 小时内验证过的得分高

## 轮换器工作模式

- **定时轮换 (rotate_mode="time")** — 每隔 N 秒自动切换到下一个代理
- **计数轮换 (rotate_mode="request")** — 每处理 N 个请求后切换
- **会话保持 (sticky_sessions)** — 同一 Session 的请求使用同一个代理
- **固定模式 (pin)** — 锁定特定代理，停止自动轮换

## 依赖

- **Python** >= 3.10
- **MySQL** 8.0+ (可选，用于历史数据和分组持久化)
- **Nmap** 7.0+ (可选，项目已内置)

### Python 包

| 包 | 用途 |
|----|------|
| aiohttp | 异步 HTTP 客户端（抓取 + 验证） |
| flask | Web 面板 |
| beautifulsoup4 | HTML 解析（网页表格源） |
| requests[socks] | HTTP 代理验证 + PySocks 支持 |
| PySocks | SOCKS 代理支持 |
| click | CLI 命令行 |
| mysql-connector-python | MySQL 存储 |

## 常见问题

**Q: 启动报错 `mysql.connector` 连接失败？**
A: MySQL 服务未启动或连接参数错误。使用 `--no-mysql` 切换到 SQLite 模式，或检查 MySQL 服务状态。

**Q: Nmap 扫描提示未找到？**
A: 项目已内置 nmap (Windows)，位于 `proxypool/nmap/nmap.exe`。Linux/Mac 用户请 `apt install nmap` 或 `brew install nmap`。

**Q: 系统代理开关无效？**
A: 仅支持 Windows。需要以管理员权限运行程序。

**Q: 代理池中存活代理很少？**
A: 免费代理时效性短，建议开启自动抓取（较短间隔如 5 分钟），并使用 Nmap 一键扫描补充。

**Q: Burp/浏览器配置代理后无法访问 HTTPS？**
A: 确保轮换器使用的代理支持 CONNECT 隧道。SOCKS5 天然支持全流量，HTTP 代理需 supports_connect=1。

## 协议

MIT License
