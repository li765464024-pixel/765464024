"""
日报/复盘生成器 (v2)
===================
将分析结果渲染为结构化 Markdown 日报
"""
import json
from datetime import date, datetime
from typing import Optional

from backend.models import query, insert


def generate_topic_report(topic_id: int, analysis_date: str = None) -> dict:
    """为单个题材生成完整日报 Markdown"""
    if not analysis_date:
        analysis_date = date.today().strftime("%Y-%m-%d")
    
    topic = query("SELECT * FROM topics WHERE id=?", (topic_id,))
    if not topic:
        return {'ok': False, 'error': '题材不存在'}
    topic = topic[0]
    
    scoring = query(
        "SELECT * FROM scoring WHERE topic_id=? ORDER BY analysis_date DESC LIMIT 1",
        (topic_id,)
    )
    scoring = scoring[0] if scoring else {}
    
    catalysts = query(
        "SELECT * FROM catalysts WHERE topic_id=? ORDER BY event_date DESC LIMIT 20",
        (topic_id,)
    )
    
    heat = query(
        "SELECT * FROM heat_data WHERE topic_id=? ORDER BY stat_date DESC LIMIT 7",
        (topic_id,)
    )
    
    capital = query(
        "SELECT * FROM capital_flow WHERE topic_id=? ORDER BY trade_date DESC LIMIT 5",
        (topic_id,)
    )
    
    quotes = query(
        "SELECT * FROM topic_daily_quotes WHERE topic_id=? ORDER BY trade_date DESC LIMIT 10",
        (topic_id,)
    )
    
    components = query(
        "SELECT * FROM topic_components_v2 WHERE topic_id=? ORDER BY component_type",
        (topic_id,)
    )
    
    # 构建 Markdown
    stage = scoring.get('lifecycle_stage', topic.get('current_stage', '未知'))
    total = scoring.get('total_score', topic.get('total_score', 0))
    
    md = f"""# 📊 题材日报：{topic['topic_name']}

**分析日期**：{analysis_date}
**生命周期阶段**：{stage}
**总分**：{total}
**核心逻辑**：{topic.get('core_logic', '暂无')}

---

## 一、五维评分

| 维度 | 评分 | 权重 | 加权得分 |
|------|:----:|:----:|:--------:|
| 价格强度 | {scoring.get('price_strength', '-')}/100 | ×30% | {round((scoring.get('price_strength', 0) or 0) * 0.30, 1)} |
| 资金强度 | {scoring.get('capital_strength', '-')}/100 | ×25% | {round((scoring.get('capital_strength', 0) or 0) * 0.25, 1)} |
| 催化强度 | {scoring.get('catalyst_strength', '-')}/100 | ×20% | {round((scoring.get('catalyst_strength', 0) or 0) * 0.20, 1)} |
| 热度强度 | {scoring.get('sentiment_strength', '-')}/100 | ×15% | {round((scoring.get('sentiment_strength', 0) or 0) * 0.15, 1)} |
| 结构质量 | {scoring.get('structure_quality', '-')}/100 | ×10% | {round((scoring.get('structure_quality', 0) or 0) * 0.10, 1)} |
| **总分** | **{total}** | **100%** | **{total}** |

## 二、龙头与梯队

"""
    # 龙头
    leaders = [c for c in components if c.get('component_type') == 'leader_candidate']
    centers = [c for c in components if c.get('component_type') == 'center_candidate']
    followers = [c for c in components if c.get('component_type') == 'follow_up_candidate']
    
    leader_str = '、'.join([f'{c["stock_name"]}({c["stock_code"]})' for c in leaders]) if leaders else '未确定'
    center_str = '、'.join([f'{c["stock_name"]}({c["stock_code"]})' for c in centers]) if centers else '暂无'
    follower_str = '、'.join([c['stock_name'] for c in followers]) if followers else '暂无'
    
    md += f"- **龙头**：{leader_str}\n"
    md += f"- **中军**：{center_str}\n"
    md += f"- **补涨**：{follower_str}\n"
    
    # 行情摘要
    if quotes:
        latest = quotes[0]
        md += f"\n## 三、行情数据（{latest.get('trade_date', '')}）\n\n"
        md += f"- 涨停：{latest.get('limit_up_count', 0)} 家\n"
        md += f"- 跌停：{latest.get('limit_down_count', 0)} 家\n"
        md += f"- 连板：{latest.get('consecutive_board_count', 0)} 家\n"
        md += f"- 成交额：{latest.get('board_turnover_amount', 0)} 亿元\n"
    
    # 催化事件
    if catalysts:
        md += f"\n## 四、催化事件（近7日）\n\n"
        for c in catalysts[:5]:
            md += f"- **{c.get('event_date', '')}** [{c.get('event_type', '')}] {c.get('event_title', '')} — {c.get('event_level', '')}\n"
    
    # 热度
    if heat:
        latest_heat = heat[0]
        md += f"\n## 五、热度数据（{latest_heat.get('stat_date', '')}）\n\n"
        md += f"- 媒体报道：{latest_heat.get('media_report_count', 0)} 篇\n"
        md += f"- 股吧讨论：{latest_heat.get('guba_discussion_count', 0)} 条\n"
        md += f"- 1日变化：{latest_heat.get('heat_change_1d', 0)}%\n"
        md += f"- 3日变化：{latest_heat.get('heat_change_3d', 0)}%\n"
    
    # 资金
    if capital:
        latest_cap = capital[0]
        md += f"\n## 六、资金流向（{latest_cap.get('trade_date', '')}）\n\n"
        md += f"- 板块主力净流入：{latest_cap.get('board_main_net_inflow', 0)} 亿元\n"
        md += f"- 龙头主力净流入：{latest_cap.get('leader_main_net_inflow', 0)} 亿元\n"
        md += f"- 龙虎榜上榜：{latest_cap.get('lhb_stock_count', 0)} 只\n"
    
    # 风险
    risks = query(
        "SELECT * FROM topic_risk_events WHERE topic_name=? AND date=? ORDER BY id DESC",
        (topic['topic_name'], analysis_date)
    )
    if risks:
        md += f"\n## ⚠️ 风险提示\n\n"
        for r in risks:
            md += f"- **[{r.get('risk_type', '风险')}]** {r.get('description', '')}（{r.get('severity', 'warning')}）\n"
    
    # 后续观察
    md += f"""
## 七、后续观察点

- 关注龙头是否继续晋级打开高度
- 观察后排跟风力度是否持续
- 关注板块成交额变化方向

## 八、数据来源

- 涨停池数据：东方财富
- 概念排行：悟道API
- 热度数据：社区帖子
- 资金数据：涨停个股聚合

---
*由 A股题材生命周期分析系统自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
    
    # 保存到reports表
    report_json = json.dumps({
        'topic_id': topic_id,
        'analysis_date': analysis_date,
        'lifecycle_stage': stage,
        'total_score': total,
    }, ensure_ascii=False)
    
    insert('reports', {
        'topic_id': topic_id,
        'analysis_date': analysis_date,
        'lifecycle_stage': stage,
        'summary_text': f"{topic['topic_name']}当前处于{stage}，总分{total}",
        'judgement_reasons': json.dumps([], ensure_ascii=False),
        'risk_warnings': json.dumps([r['risk_type'] for r in risks] if risks else [], ensure_ascii=False),
        'next_observation_points': json.dumps([
            '关注龙头晋级', '观察后排跟风', '关注成交额变化'
        ], ensure_ascii=False),
        'second_wave_trigger_conditions': json.dumps([], ensure_ascii=False),
        'report_json': report_json,
        'report_markdown': md,
    })
    
    return {
        'ok': True,
        'topic_id': topic_id,
        'topic_name': topic['topic_name'],
        'stage': stage,
        'markdown': md,
    }


def generate_all_reports(analysis_date: str = None) -> list:
    """为所有有评分的题材生成日报"""
    if not analysis_date:
        analysis_date = date.today().strftime("%Y-%m-%d")
    
    # 获取当日有评分的所有题材
    scored = query("""
        SELECT DISTINCT s.topic_id, t.topic_name
        FROM scoring s 
        JOIN topics t ON t.id = s.topic_id
        WHERE s.analysis_date=?
        ORDER BY s.total_score DESC
    """, (analysis_date,))
    
    reports = []
    for s in scored:
        result = generate_topic_report(s['topic_id'], analysis_date)
        if result['ok']:
            reports.append(result)
    
    return reports


if __name__ == '__main__':
    reports = generate_all_reports()
    print(f"生成了 {len(reports)} 份日报")
    for r in reports:
        print(f"  - {r['topic_name']}: {r['stage']}")
