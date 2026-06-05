---
name: 数据清洗去重
description: 新闻/公告去重、异常值标记、内容清洗。基于 cleaner.py 的 deduplicate_news()、deduplicate_announcements()、mark_outliers()。
---

# 数据清洗去重（Data Cleaner/Deduplicator）

## 用途

在采集管道中，对多源汇聚的原始数据进行**去重和清洗**，确保入库数据质量：
1. **新闻去重** — 同链接/同标题/相似内容的多源新闻去重
2. **公告去重** — 同公司同日同主题合并，更正公告保留最新
3. **异常值标记** — 基于 IQR 方法标记价格/成交量/资金流的离群值
4. **正文清洗** — 移除 HTML 标签、空白符压缩、编码修复

## 调用方法

### 方式 A：使用 cleaner.py 内置函数

```python
from backend.services.cleaner import (
    deduplicate_news,           # 新闻去重
    deduplicate_announcements,  # 公告去重
    mark_outliers,              # 异常值标记
    get_stat_bounds,            # IQR 边界计算
)

# 新闻去重
raw_news = [
    {"title": "低空经济政策利好", "source_url": "https://...", "content": "..."},
    {"title": "低空经济政策利好", "source_url": "https://...", "content": "..."},  # 重复
]
clean_news = deduplicate_news(raw_news)  # 只保留第一条

# 异常值标记
data = [{"price": 10}, {"price": 12}, {"price": 11}, {"price": 999}]
marked = mark_outliers(data, field="price")
# marked[3]["_outlier"] == True

# 公告去重
anns = [
    {"stock_code": "000001", "date": "2025-06-04", "title": "业绩预告"},
    {"stock_code": "000001", "date": "2025-06-04", "title": "业绩预告（更正版）"},
]
deduped = deduplicate_announcements(anns)  # 保留更正版
```

### 方式 B：全流程清洗管道

```python
def clean_pipeline(raw_data: list, data_type: str = "news") -> list:
    """完整清洗管道"""
    from backend.services.cleaner import deduplicate_news, deduplicate_announcements, mark_outliers
    
    if data_type == "news":
        cleaned = deduplicate_news(raw_data)
    elif data_type == "announcement":
        cleaned = deduplicate_announcements(raw_data)
    else:
        cleaned = raw_data
    
    # 合并异常值标记
    for numeric_field in ["price", "amount", "net_inflow"]:
        if any(numeric_field in d for d in cleaned):
            cleaned = mark_outliers(cleaned, field=numeric_field)
    
    return cleaned
```

## 输出格式

```python
{
    "original_count": 120,       # 原始条数
    "deduped_count": 95,         # 去重后条数
    "duplicate_removed": 25,     # 去除的重复条数
    "outliers_marked": 3,        # 标记的异常值条数
    "clean_data": [...],         # 清洗后的数据
}
```

## 数据缺失/异常时

- ✅ 输入为 `None` 或空列表时，返回 `{"original_count": 0, "clean_data": []}`
- ✅ 异常值标记不删除数据，仅添加 `_outlier` 标记由下游自行处理
- ❌ 不能篡改原始数据内容，只做去重+标记

## 参考文件

- `backend/services/cleaner.py` — 完整的清洗引擎实现
- `backend/services/pipeline.py` — 全流程编排（调用 cleaner 的上下文示例）
- `backend/services/collector.py` — 采集引擎（清洗的上游）
