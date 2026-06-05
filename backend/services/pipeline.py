"""
全流程编排引擎 (v2)
===================
采集 → 清洗 → 打分 → 分类 → 写库
"""
import json
from datetime import date, datetime, timedelta
from typing import Optional

from backend.models import query, insert, insert_many, execute
from backend.services.collector import (
    collect_active_topics, collect_topic_components,
    collect_heat_data, collect_capital_flow, collect_daily_quotes
)
from backend.services.cleaner import normalize_topic_name, get_topic_aliases
from backend.services.scorer import get_all_scores
from backend.services.classifier import classify_with_confidence, detect_risks


def ensure_topic_id(topic_name: str) -> int:
    """获取或创建题材记录，返回 topic_id"""
    normalized = normalize_topic_name(topic_name)
    aliases = get_topic_aliases(normalized)
    
    rows = query("SELECT id FROM topics WHERE topic_name=?", (normalized,))
    if rows:
        # 更新别名
        if aliases:
            execute("UPDATE topics SET topic_aliases=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (json.dumps(aliases, ensure_ascii=False), rows[0]['id']))
        return rows[0]['id']
    
    # 创建新题材
    insert('topics', {
        'topic_name': normalized,
        'topic_aliases': json.dumps(aliases, ensure_ascii=False),
        'core_logic': '',
        'industry_chain': '',
        'first_active_date': date.today().strftime("%Y-%m-%d"),
        'last_analysis_date': date.today().strftime("%Y-%m-%d"),
    })
    rows = query("SELECT id FROM topics WHERE topic_name=?", (normalized,))
    return rows[0]['id']


def analyze_single_topic(topic_id: int, topic_name: str, today: str) -> dict:
    """分析单个题材的全流程"""
    print(f"  🔍 [{topic_id}] {topic_name}")
    
    # Step 1: 收集成分股
    components = collect_topic_components(topic_id, topic_name, today)
    if components:
        insert_many('topic_components_v2', components)
    
    # Step 2: 收集每日行情
    daily = collect_daily_quotes(topic_id, topic_name, today)
    if daily:
        insert('topic_daily_quotes', daily)
    
    # Step 3: 收集热度
    heat = collect_heat_data(topic_id, topic_name, today)
    if heat:
        insert('heat_data', heat)
    
    # Step 4: 收集资金
    capital = collect_capital_flow(topic_id, topic_name, today)
    if capital:
        insert('capital_flow', capital)
    
    # Step 5: 构造 topic_data 用于评分
    stocks = query(
        "SELECT * FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ?) ORDER BY board_num DESC",
        (today, f'%{topic_name}%', f'%{topic_name}%')
    )
    today_zt = len(stocks)
    today_leader_board = stocks[0]['board_num'] if stocks else 0
    
    # 昨日对比
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).strftime("%Y-%m-%d")
    y_stocks = query(
        "SELECT * FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ?) ORDER BY board_num DESC",
        (yesterday, f'%{topic_name}%', f'%{topic_name}%')
    )
    yesterday_count = len(y_stocks)
    yesterday_leader_board = y_stocks[0]['board_num'] if y_stocks else 0
    
    # 板次分布
    boards = set()
    for s in stocks:
        if s.get('board_num'):
            boards.add(s['board_num'])
    
    # 找中军
    big_stocks = [s for s in stocks if (s.get('float_mcap') or 0) >= 50 or (s.get('trade_amt') or 0) >= 5]
    
    topic_data = {
        'zt_count': today_zt,
        'leader_board': today_leader_board,
        'leader_name': stocks[0]['name'] if stocks else '',
        'center_name': big_stocks[0]['name'] if big_stocks else '',
        'has_center_stock': len(big_stocks) > 0,
        'has_expansion': today_zt >= 3 and len(boards) >= 2,
        'ladder_levels': len(boards),
        'board_trend': 'up' if today_zt > yesterday_count else 'flat',
        'zt_change': today_zt - yesterday_count,
        'net_inflow': capital.get('board_main_net_inflow', 0) if capital else 0,
        'volume_change': 0,
        'institution_count': capital.get('lhb_stock_count', 0) if capital else 0,
        'big_order_ratio': 0,
        'seal_rate': 60,
        'leader_turnover': stocks[0].get('turnovers') or 0 if stocks else 0,
        'yesterday_leader_board': yesterday_leader_board,
        'has_risk': False,
        'catalysts': [],
        'catalyst_continuous': False,
        'catalyst_escalating': False,
        'media_count': heat.get('media_report_count', 0) if heat else 0,
        'sentiment_change': heat.get('heat_change_1d', 0) if heat else 0,
        'daily_sentiment_change': heat.get('heat_change_1d', 0) if heat else 0,
    }
    
    # Step 6: 五维评分
    scores = get_all_scores(topic_data)
    
    # Step 7: 生命周期分类
    classification = classify_with_confidence(scores, topic_data)
    
    # Step 8: 风险检测
    risks = detect_risks(topic_data)
    topic_data['has_risk'] = len(risks) > 0
    
    # Step 9: 保存评分
    insert('scoring', {
        'topic_id': topic_id,
        'analysis_date': today,
        'price_strength': scores['price_strength'],
        'capital_strength': scores['capital_strength'],
        'catalyst_strength': scores['catalyst_strength'],
        'sentiment_strength': scores['sentiment_strength'],
        'structure_quality': scores['structure_quality'],
        'total_score': scores['total_score'],
        'lifecycle_stage': classification['stage'],
        'confidence': classification['confidence'],
    })
    
    # Step 10: 更新题材主表
    execute(
        "UPDATE topics SET current_stage=?, total_score=?, last_analysis_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (classification['stage'], scores['total_score'], today, topic_id)
    )
    
    print(f"    → {classification['stage']} (总分{scores['total_score']}, 置信度{classification['confidence']})")
    
    return {
        'topic_id': topic_id,
        'topic_name': topic_name,
        'stage': classification['stage'],
        'scores': scores,
        'confidence': classification['confidence'],
        'reasons': classification['reasons'],
        'risks': risks,
    }


def run_full_analysis(today: str = None) -> list:
    """执行全量分析：发现题材 → 逐个分析"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    print(f"\n{'='*50}")
    print(f"📊 v2 全量分析 [{today}]")
    print(f"{'='*50}")
    
    # Step 1: 采集活跃题材
    raw_topics = collect_active_topics(today)
    print(f"  发现 {len(raw_topics)} 个活跃题材")
    
    # Step 2: 清洗归一化 → 去重
    seen = {}
    for t in raw_topics:
        normalized = normalize_topic_name(t['name'])
        if normalized not in seen:
            t['name'] = normalized
            seen[normalized] = t
    unique_topics = list(seen.values())
    print(f"  归一化后 {len(unique_topics)} 个唯一题材")
    
    # Step 3: 逐个分析
    results = []
    for t in unique_topics[:10]:  # 最多10个
        topic_id = ensure_topic_id(t['name'])
        result = analyze_single_topic(topic_id, t['name'], today)
        results.append(result)
    
    print(f"{'='*50}\n")
    return results


if __name__ == '__main__':
    run_full_analysis()
