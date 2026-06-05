---
name: 题材归一化
description: A股题材/概念名称的智能归一化 — 同义词映射、别名管理、催化事件分类。基于 cleaner.py 的 normalize_topic_name()、classify_event_type()。
---

# 题材归一化（Entity Normalizer）

## 用途

将不同数据源的同义题材名称**统一为标准名称**，并对催化事件进行分类分级。这是题材生命周期分析的关键前置步骤：
1. **题材名称归一化** — "飞行汽车" → "低空经济"，"ChatGPT" → "人工智能"
2. **别名管理** — 查询某个标准题材有哪些别名
3. **催化事件类型分类**（9 类） — 政策/公告/订单/合作/产品/业绩/会议/行业数据/媒体
4. **催化事件级别判定**（5 级） — 国家级/部委级/地方级/公司级/媒体级

## 调用方法

### 方式 A：题材归一化

```python
from backend.services.cleaner import (
    normalize_topic_name,
    get_topic_aliases,
)

# 归一化
name1 = normalize_topic_name("飞行汽车")   # 返回"低空经济"
name2 = normalize_topic_name("AI芯片")     # 返回"人工智能"
name3 = normalize_topic_name("存储芯片")   # 返回"半导体/芯片"

# 查询别名
aliases = get_topic_aliases("低空经济")
# 返回 ["飞行汽车", "eVTOL", "无人机", "低空"]

# 直接使用映射表
from backend.services.cleaner import TOPIC_ALIAS_MAP
# TOPIC_ALIAS_MAP 是 dict[str, str]，同义词→标准名
```

### 方式 B：催化事件分类

```python
from backend.services.cleaner import (
    classify_event_type,   # 事件类型（9 分类）
    classify_event_level,  # 事件级别（5 级）
)

# 事件类型
etype = classify_event_type("国务院印发人工智能发展规划")
# 返回 "policy"（政策类）

# 事件级别
level = classify_event_level("工信部发布5G商用通知")
# 返回 "ministry"（部委级）

# 联合使用
title = "国务院常务会议通过《低空经济发展规划》"
event_type = classify_event_type(title)    # "policy"
event_level = classify_event_level(title)  # "national"
```

### 方式 C：扩展映射表

```python
# 在 cleaner.py 的 TOPIC_ALIAS_MAP 中新增映射：
TOPIC_ALIAS_MAP = {**TOPIC_ALIAS_MAP, **{
    '新质生产力': '新质生产力',
    '新质': '新质生产力',
}}
```

## 输出格式

```python
{
    "raw_input": "飞行汽车",
    "normalized": "低空经济",
    "aliases": ["飞行汽车", "eVTOL", "无人机", "低空"],
    "mapping_found": True,      # 是否命中映射表
}
```

## 映射表中不存在时

- ✅ 返回原始名称不变
- ✅ 自动去除尾部冗余词（"行业""板块""概念""产业链"），再尝试匹配
- ✅ 提示用户"未命中映射表，如需纳入请扩展 TOPIC_ALIAS_MAP"
- ❌ 不能将未识别的题材强行归入已有类别

## 参考文件

- `backend/services/cleaner.py` — `TOPIC_ALIAS_MAP`、`EVENT_TYPE_KEYWORDS`、`EVENT_LEVEL_KEYWORDS`
- `backend/services/pipeline.py` — 全流程编排中的归一化调用示例
- `backend/services/collector.py` — 采集引擎（题材数据的上游来源）
