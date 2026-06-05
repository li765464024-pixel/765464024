---
name: 评分分类器
description: A股题材五维评分 + 六阶段生命周期分类 + 风险检测。基于 scorer.py（价格/资金/催化/热度/结构评分）、classifier.py（孕育→启动→爆发→分歧→退潮→余温）、pipeline.py 全流程编排。
---

# 评分分类器（Scoring/Lifecycle Classifier）

## 用途

对 A 股题材进行**量化评分**和**生命周期阶段判定**，是"题材生命周期分析系统"的核心引擎：
1. **五维评分** — 价格强度(权重30%)、资金强度(25%)、催化强度(20%)、热度强度(15%)、结构质量(10%)
2. **生命周期分类** — 孕育期/预热期 → 启动期 → 爆发期 → 分歧震荡期 → 退潮期 → 余温反复/二波观察期
3. **风险检测** — 断板、高位巨震、梯队断层、板块拥挤等风险信号
4. **置信度评估** — 每次分类附带置信度分数

## 评分维度详解

| 维度 | 权重 | 评分函数 | 关键指标 |
|------|------|----------|----------|
| 价格强度 | 30% | `score_price_strength()` | 涨停家数、龙头板次、板块趋势、涨停变化 |
| 资金强度 | 25% | `score_capital_strength()` | 主力净流入、放量幅度、机构参与数、大单比例 |
| 催化强度 | 20% | `score_catalyst_strength()` | 催化事件数、最高级别、持续性/升级性、落地数 |
| 热度强度 | 15% | `score_sentiment_strength()` | 媒体报道数、热度变化率、社区讨论量 |
| 结构质量 | 10% | `score_structure_quality()` | 梯队层数、中军股、扩散性、封板率 |

## 调用方法

### 方式 A：完整分析管道

```python
from backend.services.pipeline import run_full_analysis

# 全量分析今日所有活跃题材
results = run_full_analysis(today="2025-06-04")
for r in results:
    print(f"{r['topic_name']}: {r['stage']} (总分{r['scores']['total_score']})")
```

### 方式 B：单题材评分 + 分类

```python
from backend.services.scorer import get_all_scores
from backend.services.classifier import classify_with_confidence, detect_risks

# 构造 topic_data
topic_data = {
    'zt_count': 8,
    'leader_board': 4,
    'board_trend': 'up',
    'zt_change': 3,
    'net_inflow': 2.5,
    'volume_change': 35,
    'institution_count': 2,
    'big_order_ratio': 15,
    'catalysts': [{'level': 'national'}, {'level': 'ministry'}],
    'catalyst_continuous': True,
    'catalyst_escalating': True,
    'media_count': 12,
    'sentiment_change': 60,
    'daily_sentiment_change': 25,
    'ladder_levels': 3,
    'has_center_stock': True,
    'has_expansion': True,
    'seal_rate': 75,
    'leader_turnover': 15,
    'yesterday_leader_board': 3,
}

# 五维评分
scores = get_all_scores(topic_data)  # 返回 dict{total_score, price_strength, ...}

# 生命周期分类
classification = classify_with_confidence(scores, topic_data)
# classification = {"stage": "爆发期", "reasons": [...], "confidence": 0.87, "color": "#059669"}

# 风险检测
risks = detect_risks(topic_data)
# risks = [{"risk_type": "梯队断层", "severity": "warning", "description": "..."}]
```

### 方式 C：通过 REST API

```bash
# 触发全量分析
curl -X POST http://localhost:5500/api/v2/analyze

# 获取题材列表（含评分和生命周期）
curl http://localhost:5500/api/v2/topics

# 获取题材详情
curl http://localhost:5500/api/v2/topics/1/detail
```

## 输出格式

```python
{
    "topic_name": "低空经济",
    "scores": {
        "total_score": 72.5,
        "price_strength": 68.0,
        "capital_strength": 60.0,
        "catalyst_strength": 75.0,
        "sentiment_strength": 80.0,
        "structure_quality": 85.0,
    },
    "stage": "爆发期",
    "stage_color": "#059669",
    "confidence": 0.87,
    "reasons": [
        "总分72.5≥65，价格68，资金60，催化75共振",
        "涨停8家，龙头4板，有后排扩散",
        "有中军股坐镇，板块结构完整",
    ],
    "risks": [
        {"risk_type": "梯队断层", "severity": "warning", "description": "..."}
    ],
}
```

## 生命周期判定边界

| 阶段 | 典型总分范围 | 关键判定条件 |
|------|-------------|-------------|
| 孕育期/预热期 | <50 | 催化开始出现，涨停家数少或无 |
| 启动期 | 50-65 | 涨停2+，龙头1板+，资金开始关注 |
| 爆发期 | 65+ | 涨停5+，龙头3板+，有后排扩散 |
| 分歧震荡期 | 55-75 | 价格偏强但资金/结构偏弱 |
| 退潮期 | ≤55 | 价格偏弱，涨停减少 |
| 余温反复/二波观察期 | 45-65 | 催化回升，核心股转强 |

## 数据缺失时

- ✅ 缺失字段使用默认值（0 或 False）
- ✅ 可以提示"数据量不足以给出准确评分，建议补充数据后重试"
- ❌ 不能虚构评分维度或编造生命周期结论

## 参考文件

- `backend/services/scorer.py` — 五维评分引擎（`get_all_scores()`）
- `backend/services/classifier.py` — 生命周期分类器 + 风险检测
- `backend/services/pipeline.py` — 全流程编排（采集→清洗→评分→分类）
- `backend/services/collector.py` — 数据采集（评分所需数据的上游）
