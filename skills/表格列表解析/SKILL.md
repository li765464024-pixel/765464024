---
name: 表格列表解析
description: 从 HTML/文本中解析结构化表格和列表数据 — 涨停梯队、板块排行、连板晋级率、资金流向排行等。支持多格式适配。
---

# 表格/列表解析（Table Parser）

## 用途

将 A 股数据页面中的结构化信息（表格、排序列表）提取为 Python 字典/列表，便于后续入库和量化分析。典型数据包括：
1. **涨停梯队**（板次分布、涨停时间、封板率）
2. **板块热度排行**（涨跌幅、主力净流入、涨停家数）
3. **连板晋级率汇总**（首板→二板、二板→三板晋级成功率）
4. **龙虎榜数据**（买入席位、卖出金额）
5. **资金流向排行**（行业/概念的主力净流入排序）

## 调用方法

### 方式 A：解析 HTML 表格 → dict 列表

```python
from bs4 import BeautifulSoup

def parse_html_table(table_element) -> list[dict]:
    """将 HTML <table> 解析为 list[dict]"""
    rows = []
    headers = []
    
    # 提取表头
    thead = table_element.find("thead")
    if thead:
        headers = [th.get_text(strip=True) for th in thead.find_all("th")]
    
    # 提取表体
    tbody = table_element.find("tbody") or table_element
    for tr in tbody.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        if headers:
            row = {}
            for i, cell in enumerate(cells):
                if i < len(headers):
                    row[headers[i]] = cell.get_text(strip=True)
        else:
            row = [cell.get_text(strip=True) for cell in cells]
        rows.append(row)
    
    return rows
```

### 方式 B：解析项目数据库中的结构化数据

```python
from backend.models import query

# 涨停梯队
ladder = query("""
    SELECT board_num, COUNT(*) as cnt, 
           ROUND(AVG(seal_rate), 1) as avg_seal_rate
    FROM zt_stocks 
    WHERE date=? GROUP BY board_num ORDER BY board_num DESC
""", ("2025-06-04",))

# 板块热度排行
sectors = query("""
    SELECT sector, COUNT(*) as zt_count, MAX(board_num) as max_board
    FROM zt_stocks WHERE date=? AND sector!=''
    GROUP BY sector ORDER BY zt_count DESC LIMIT 20
""", ("2025-06-04",))
```

### 方式 C：从 Crawler 获取已解析数据

```python
from backend.services.crawler import (
    fetch_board_summary,       # 连板晋级率
    fetch_sector_ranking,      # 板块排行
    fetch_lhb_list,            # 龙虎榜列表
)

summary = fetch_board_summary()   # 返回 list[dict]
ranking = fetch_sector_ranking()  # 返回 list[dict]
```

## 输出格式

统一为 `list[dict]`，每个 dict 代表一行：

```python
[
    {
        "rank": 1,
        "board_num": 7,
        "stock_name": "概念龙头",
        "stock_code": "000000",
        "seal_rate": 85.5,
        "trade_amt": 12.3,        # 成交额（亿）
        "sector": "低空经济",
    },
]
```

## 空数据/解析失败时

- ✅ 返回空列表 `[]`，并附带日志警告
- ✅ 可以尝试降级解析（按逗号/空格分隔的文本行）
- ❌ 不能虚构表格数据

## 参考文件

- `backend/services/crawler.py` — 现有爬虫中的表格解析实现
- `backend/models.py` — 数据库表结构（`zt_stocks`、`market_data` 等）
- `backend/app.py` — API 中已有的 `/api/board/summary`、`/api/sectors/hot` 端点
