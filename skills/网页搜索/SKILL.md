---
name: 网页搜索
description: 多平台网页搜索 — 淘股吧、韭研公社、同花顺、东方财富、财联社、百度。返回带摘要的搜索结果列表，支持指定平台/关键词/日期范围过滤。
---

# 网页搜索（Web Search）

## 用途

在 A 股数据采集流程中，用于从多个平台搜索社区帖子、新闻快讯、个股讨论等文本信息。是采集管道的**第一入口**。

## 数据源优先级

1. **淘股吧** — 短线游资聚集地，搜索 `taoguba.com.cn` 的帖子/回复
2. **韭研公社** — 题材挖掘核心平台，搜索 `jiuyangongshe.com` 的热榜/讨论
3. **同花顺** — 个股社区 + 行业板块，搜索 `10jqka.com.cn`
4. **东方财富** — 股吧 + 研报，搜索 `eastmoney.com`
5. **财联社** — 快讯 + 电报，搜索 `cls.cn`（优先走 `collect_cls_news()` 接口）
6. **百度网页** — 通用兜底搜索

## 调用方法

### 方式 A：使用项目内置爬虫（推荐）

```python
from backend.services.crawler import (
    fetch_jiuyangongshe,       # 韭研公社热榜
    fetch_taoguba,             # 淘股吧帖子
    fetch_news_from_cls,       # 财联社快讯
    fetch_dongfang_caifu,      # 东方财富研报/新闻
)

# 示例：抓取韭研公社热榜
posts = fetch_jiuyangongshe()  # 返回 list[dict]

# 示例：抓取淘股吧帖子
posts = fetch_taoguba()        # 返回 list[dict]
```

### 方式 B：使用采集引擎 collector.py

```python
from backend.services.collector import (
    collect_cls_news,     # 从数据库查询财联社快讯
    collect_active_topics, # 采集当日活跃题材
)

# 示例：按关键词过滤财联社新闻
news = collect_cls_news(today="2025-06-04", keywords=["低空经济", "AI"])
```

### 方式 C：通用 HTTP 请求（兜底）

```python
import requests
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/604.1",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
resp = requests.get("https://www.baidu.com/s?wd=低空经济", headers=HEADERS, timeout=10)
```

## 输出格式

返回统一的搜索结果列表：

```python
[
    {
        "platform": "jiuyangongshe",  # 数据源平台标识
        "title": "低空经济政策催化不断",
        "author": "题材挖掘机",
        "date": "2025-06-04",
        "url": "https://www.jiuyangongshe.com/...",
        "summary": "摘要内容...",
        "relevance_score": 0.85,       # 与搜索关键词的相关度 (0-1)
    }
]
```

## 数据缺失时

- ✅ 可以告知用户"当前搜索未返回结果"，并建议换关键词/换平台
- ✅ 可以调换数据源优先级，尝试其他平台
- ❌ 不能凭空捏造搜索结果

## 参考文件

- `backend/services/crawler.py` — 各平台爬虫实现
- `backend/services/collector.py` — 采集引擎（数据库查询 + API 调用）
- `.env` — `LB_API_KEY` 用于悟道 API（概念排行/最强风口等）
