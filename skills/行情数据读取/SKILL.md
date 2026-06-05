---
name: 行情数据读取
description: 从 SQLite 数据库读取 A 股行情数据 — 大盘指标、涨停个股、板块热度、资金流向、龙虎榜。封装了 models.py 的 query() 和 collector.py 的采集函数。
---

# 行情数据读取（Market Data Reader）

## 用途

从 `data/fupan.db` 数据库中读取已存储的行情数据，为其他技能提供数据基础。覆盖：
1. **大盘指标** — 上证/深证/创业板/科创 50 指数、涨跌家数、成交额、市场温度
2. **涨停个股** — 代码/名称/板次/涨停时间/封板率/涨停原因/资金净流入
3. **板块热度排行** — 各行业的涨停家数、最高板次
4. **连板晋级率** — 首板→二板、二板→三板的晋级成功率
5. **资金流向** — 主力净流入/流出、龙虎榜上榜数

## 调用方法

### 方式 A：通过 models.py 的 query() 直接查询

```python
from backend.models import query

# 大盘数据
market = query("SELECT * FROM market_data WHERE date=? ORDER BY id DESC LIMIT 1", ("2025-06-04",))

# 涨停个股（按板次排序）
zt_stocks = query("""
    SELECT * FROM zt_stocks WHERE date=? ORDER BY board_num DESC, seal_time ASC
""", ("2025-06-04",))

# 某板次个股
board2 = query("SELECT * FROM zt_stocks WHERE date=? AND board_num=?", ("2025-06-04", 2))

# 板块热度
sectors = query("""
    SELECT sector, COUNT(*) as zt_count, MAX(board_num) as max_board
    FROM zt_stocks WHERE date=? AND sector!=''
    GROUP BY sector ORDER BY zt_count DESC LIMIT 15
""", ("2025-06-04",))
```

### 方式 B：通过 Collector 采集实时数据

```python
from backend.services.collector import (
    collect_active_topics,    # 当日活跃题材
    collect_daily_quotes,     # 板块每日行情
    collect_capital_flow,     # 资金流向
    collect_heat_data,        # 热度数据
)

today = "2025-06-04"
topics = collect_active_topics(today)
for t in topics[:5]:
    print(f"{t['name']}: {t['zt_count']}涨停")
```

### 方式 C：通过 REST API（Flask 端点）

```bash
# 大盘数据
curl http://localhost:5500/api/market/today

# 板块热度排行
curl http://localhost:5500/api/sectors/hot

# 连板晋级率
curl http://localhost:5500/api/board/summary

# 指定板次个股
curl "http://localhost:5500/api/board/list?board=2"
```

## 输出格式

统一返回 `list[dict]` 或 `dict`，字段与数据库 schema 一致。示例：

```python
{
    "date": "2025-06-04",
    "market_data": {
        "index_sh": 3150.23,      # 上证指数
        "index_sz": 10500.45,     # 深证成指
        "zt_count": 68,           # 涨停家数
        "dt_count": 5,            # 跌停家数
        "seal_rate": 82.5,        # 封板率 %
        "volume": "9500亿",       # 成交额
        "temperature": 65.0,      # 市场温度
    },
    "top_zt_stocks": [
        {"code": "000000", "name": "龙头股", "board_num": 7, "seal_time": "09:30"},
    ],
}
```

## 无数据时

- ✅ 查询返回空列表 `[]`，提示"当前日期暂无数据"
- ✅ 建议先执行数据迁移：`python3 run.py`（首次启动自动迁移）
- ✅ 或手动触发刷新：`curl -X POST http://localhost:5500/api/market/refresh`
- ❌ 不能凭空编造 K 线数据或行情指标

## 参考文件

- `backend/models.py` — 数据库表结构定义（`market_data`、`zt_stocks` 等）
- `backend/services/collector.py` — 采集引擎（实时数据源）
- `backend/app.py` — REST API 端点实现
