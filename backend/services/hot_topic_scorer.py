"""
热门题材与主线题材评分引擎
==========================
从多表聚合数据，计算三重排名：
1. 热度分 — 四个平台加权
2. 主线强度分 — 市场数据加权
3. 综合分 — 热度×40% + 强度×60%
"""
from datetime import date, timedelta
from typing import List, Dict, Any

from backend.models import query


def compute_heat_score(topic_name: str, today: str = None) -> dict:
    """计算单个题材的热度分（0-100）
    
    韭研公社25% + 雪球25% + 东方财富30% + 同花顺20%
    当 platform_heat 无数据时，从 zt_stocks 和 lifecycle 估算
    """
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    import math
    
    # 从 platform_heat 表读取各平台数据
    rows = query(
        "SELECT * FROM platform_heat WHERE topic_name=? AND stat_date=?",
        (topic_name, today)
    )
    
    platform_scores = {}
    for r in rows:
        platform = r['platform']
        mention = r['mention_count'] or 0
        rank = r['hot_rank'] or 99
        change_1d = r['heat_change_1d'] or 0
        change_3d = r['heat_change_3d'] or 0
        
        if platform in ('jygs', 'xueqiu'):
            score = min(100, int(math.log(mention + 1, 1.5) * 15))
            score += min(20, max(-20, int(change_1d / 5)))
            score = max(0, min(100, score))
        elif platform == 'eastmoney':
            score = min(100, mention * 12)
        elif platform == 'ths':
            score = max(0, 100 - rank * 5)
        else:
            score = 0
        
        platform_scores[platform] = {
            'raw_mention': mention, 'raw_rank': rank, 'score': score,
            'change_1d': change_1d, 'change_3d': change_3d,
        }
    
    # 如果 platform_heat 只有 <=1 个平台有数据，从 zt_stocks 估算
    if len(platform_scores) <= 1:
        # 查涨停数据
        zt_count = query(
            "SELECT COUNT(*) as c FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ?)",
            (today, f'%{topic_name}%', f'%{topic_name}%')
        )[0]['c']
        
        # 查 lifecycle 总分
        lc = query(
            "SELECT total_score, sentiment_strength FROM topic_lifecycle WHERE topic_name=? AND date=? ORDER BY id DESC LIMIT 1",
            (topic_name, today)
        )
        total_score = lc[0]['total_score'] if lc else 0
        sentiment = lc[0]['sentiment_strength'] if lc else 0
        
        # 根据涨停数估算东财热度（涨停1只≈12分）
        em_score = min(100, zt_count * 12) if zt_count > 0 else 0
        # 根据总分估算韭研/雪球热度
        jy_score = min(100, max(0, sentiment * 0.8)) if sentiment > 0 else min(40, zt_count * 5)
        xq_score = min(100, max(0, sentiment * 0.6)) if sentiment > 0 else min(30, zt_count * 3)
        # 同花顺排名估算
        ths_score = min(80, total_score) if total_score > 0 else min(50, zt_count * 5)
        
        # 只补充缺失的平台
        weights = {'jygs': 0.25, 'xueqiu': 0.25, 'eastmoney': 0.30, 'ths': 0.20}
        for plat in ['jygs', 'xueqiu', 'eastmoney', 'ths']:
            if plat not in platform_scores:
                score_map = {'jygs': jy_score, 'xueqiu': xq_score, 'eastmoney': em_score, 'ths': ths_score}
                platform_scores[plat] = {
                    'raw_mention': zt_count, 'raw_rank': 0, 'score': score_map[plat],
                    'change_1d': 0, 'change_3d': 0, '_estimated': True,
                }
    
    # 权重加权
    weights = {'jygs': 0.25, 'xueqiu': 0.25, 'eastmoney': 0.30, 'ths': 0.20}
    total = 0
    detail = {}
    for plat, weight in weights.items():
        ps = platform_scores.get(plat, {'score': 0})
        ps['weight'] = weight
        ps['weighted'] = round(ps['score'] * weight, 1)
        total += ps['weighted']
        detail[plat] = ps
    
    heat_score = round(min(100, total), 1)
    jygs = platform_scores.get('jygs', {})
    heat_change_3d = jygs.get('change_3d', 0)
    
    return {
        'heat_score': heat_score,
        'platform_detail': detail,
        'heat_change_3d': heat_change_3d,
        'data_source_count': len(platform_scores),
    }


def compute_mainline_strength(topic_name: str, today: str = None) -> dict:
    """计算单个题材的主线强度分（0-100）
    
    板块涨幅25% + 成交额20% + 涨停/连板20% + 龙头强度20% + 资金流15%
    """
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    # 查 topic_daily_quotes（已有每日行情）
    today_minus_5 = (date.fromisoformat(today) - timedelta(days=5)).strftime("%Y-%m-%d")
    today_minus_10 = (date.fromisoformat(today) - timedelta(days=10)).strftime("%Y-%m-%d")
    
    # 先找 topic_id
    topic = query("SELECT id FROM topics WHERE topic_name=?", (topic_name,))
    if not topic:
        return {'mainline_score': 0, 'factors': {}, 'error': '题材不存在'}
    topic_id = topic[0]['id']
    
    # 近5日、10日行情
    quotes_5d = query(
        "SELECT * FROM topic_daily_quotes WHERE topic_id=? AND trade_date>=? ORDER BY trade_date",
        (topic_id, today_minus_5)
    )
    quotes_10d = query(
        "SELECT * FROM topic_daily_quotes WHERE topic_id=? AND trade_date>=? ORDER BY trade_date",
        (topic_id, today_minus_10)
    )
    
    factors = {}
    
    # 因子1: 板块涨幅强度 (25分)
    board_change_5d = 0
    board_change_10d = 0
    if quotes_5d:
        board_change_5d = sum(q.get('front_avg_change_pct', 0) or 0 for q in quotes_5d)
    if quotes_10d:
        board_change_10d = sum(q.get('front_avg_change_pct', 0) or 0 for q in quotes_10d)
    
    factor_price = 0
    if board_change_5d >= 50: factor_price = 25
    elif board_change_5d >= 30: factor_price = 22
    elif board_change_5d >= 15: factor_price = 18
    elif board_change_5d >= 5: factor_price = 12
    elif board_change_5d >= 0: factor_price = 6
    factors['price_strength'] = {'score': factor_price, 'value': round(board_change_5d, 1)}
    
    # 因子2: 成交额放大 (20分)
    turnover_sum_5d = sum(q.get('board_turnover_amount', 0) or 0 for q in quotes_5d) if quotes_5d else 0
    factor_volume = 0
    if turnover_sum_5d >= 500: factor_volume = 20
    elif turnover_sum_5d >= 200: factor_volume = 17
    elif turnover_sum_5d >= 100: factor_volume = 13
    elif turnover_sum_5d >= 50: factor_volume = 8
    elif turnover_sum_5d >= 10: factor_volume = 4
    factors['volume_strength'] = {'score': factor_volume, 'value': round(turnover_sum_5d, 1)}
    
    # 因子3: 涨停/连板结构 (20分)
    zt_total = sum(q.get('limit_up_count', 0) or 0 for q in quotes_5d) if quotes_5d else 0
    lb_total = sum(q.get('consecutive_board_count', 0) or 0 for q in quotes_5d) if quotes_5d else 0
    # 兜底：从 zt_stocks 直接查
    if zt_total == 0:
        today_zt = query("SELECT COUNT(*) as c FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ?)", (today, f'%{topic_name}%', f'%{topic_name}%'))
        zt_total = today_zt[0]['c'] if today_zt else 0
    factor_zt = 0
    if zt_total >= 30: factor_zt = 20
    elif zt_total >= 20: factor_zt = 17
    elif zt_total >= 10: factor_zt = 13
    elif zt_total >= 5: factor_zt = 8
    elif zt_total > 0: factor_zt = 4
    factors['zt_structure'] = {'score': factor_zt, 'value': {'zt_5d': zt_total, 'lb_5d': lb_total}}
    
    # 因子4: 龙头强度 (20分)
    # 从 topic_lifecycle 或 scoring 表读
    lifecycle = query(
        "SELECT leader_name, leader_board, total_score, lifecycle_stage FROM topic_lifecycle WHERE topic_name=? AND date=? ORDER BY id DESC LIMIT 1",
        (topic_name, today)
    )
    leader_board = lifecycle[0]['leader_board'] if lifecycle else 0
    leader_name = lifecycle[0]['leader_name'] if lifecycle else ''
    factor_leader = 0
    if leader_board >= 7: factor_leader = 20
    elif leader_board >= 5: factor_leader = 18
    elif leader_board >= 4: factor_leader = 15
    elif leader_board >= 3: factor_leader = 12
    elif leader_board >= 2: factor_leader = 8
    elif leader_board >= 1: factor_leader = 4
    factors['leader_strength'] = {'score': factor_leader, 'value': {'name': leader_name, 'board': leader_board}}
    
    # 因子5: 资金流 (15分)
    capital = query(
        "SELECT board_main_net_inflow FROM capital_flow WHERE topic_id=? AND trade_date=? ORDER BY id DESC LIMIT 1",
        (topic_id, today)
    )
    net_inflow = capital[0]['board_main_net_inflow'] if capital else 0
    factor_capital = 0
    if net_inflow >= 10: factor_capital = 15
    elif net_inflow >= 5: factor_capital = 13
    elif net_inflow >= 1: factor_capital = 10
    elif net_inflow >= 0: factor_capital = 6
    elif net_inflow >= -5: factor_capital = 3
    factors['capital_strength'] = {'score': factor_capital, 'value': round(net_inflow, 2)}
    
    total = factor_price + factor_volume + factor_zt + factor_leader + factor_capital
    total = min(100, total)
    
    # 生命周期阶段
    stage = lifecycle[0]['lifecycle_stage'] if lifecycle else '未知'
    
    return {
        'mainline_score': round(total, 1),
        'factors': factors,
        'board_change_5d': round(board_change_5d, 1),
        'board_change_10d': round(board_change_10d, 1),
        'turnover_5d': round(turnover_sum_5d, 1),
        'zt_total_5d': zt_total,
        'leader_name': leader_name,
        'leader_board': leader_board,
        'net_inflow': round(net_inflow, 2),
        'lifecycle_stage': stage,
    }


def compute_all_rankings(today: str = None) -> dict:
    """计算三个排行榜
    
    返回:
    - hot_rankings: 热度最高题材榜
    - mainline_rankings: 最强主线题材榜
    - combined_rankings: 又热又强题材榜
    """
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    # 获取分析过的题材列表
    topics = query(
        "SELECT DISTINCT topic_name FROM topic_lifecycle WHERE date=? ORDER BY total_score DESC LIMIT 30",
        (today,)
    )
    if not topics:
        # fallback: 从 platform_heat 或 topics 表
        topics = query("SELECT topic_name FROM platform_heat WHERE stat_date=? GROUP BY topic_name LIMIT 30", (today,))
        if not topics:
            topics = query("SELECT topic_name FROM topics ORDER BY total_score DESC LIMIT 20")
    
    # 先确保 platform_heat 有数据
    ph_count = query("SELECT COUNT(*) as c FROM platform_heat WHERE stat_date=?", (today,))
    if ph_count[0]['c'] == 0:
        try:
            from backend.services.collector import collect_platform_heat
            collect_platform_heat(today)
        except:
            pass
    
    hot_list = []
    mainline_list = []
    combined_list = []
    
    for t in topics:
        name = t['topic_name']
        heat = compute_heat_score(name, today)
        strength = compute_mainline_strength(name, today)
        
        # 热度排行
        heat_entry = {
            'topic_name': name,
            'heat_score': heat['heat_score'],
            'jygs_heat': heat['platform_detail'].get('jygs', {}).get('score', 0),
            'xueqiu_heat': heat['platform_detail'].get('xueqiu', {}).get('score', 0),
            'eastmoney_heat': heat['platform_detail'].get('eastmoney', {}).get('score', 0),
            'ths_heat': heat['platform_detail'].get('ths', {}).get('score', 0),
            'heat_change_3d': heat.get('heat_change_3d', 0),
            'representative_stocks': strength.get('leader_name', ''),
        }
        hot_list.append(heat_entry)
        
        # 强度排行
        mainline_entry = {
            'topic_name': name,
            'mainline_strength_score': strength['mainline_score'],
            'board_change_5d': strength.get('board_change_5d', 0),
            'board_change_10d': strength.get('board_change_10d', 0),
            'turnover_5d': strength.get('turnover_5d', 0),
            'limit_up_count_5d': strength.get('zt_total_5d', 0),
            'leader_stock': strength.get('leader_name', ''),
            'leader_board': strength.get('leader_board', 0),
            'center_stock': '',
            'net_inflow': strength.get('net_inflow', 0),
            'lifecycle_stage': strength.get('lifecycle_stage', '未知'),
        }
        mainline_list.append(mainline_entry)
        
        # 综合排行
        total_score = round(heat['heat_score'] * 0.4 + strength['mainline_score'] * 0.6, 1)
        
        # 风险等级
        risks = query(
            "SELECT severity FROM topic_risk_events WHERE topic_name=? AND date=? ORDER BY id DESC LIMIT 3",
            (name, today)
        )
        if any(r['severity'] == 'critical' for r in risks):
            risk_level = 'critical'
        elif risks:
            risk_level = 'warning'
        else:
            risk_level = 'none'
        
        combined_entry = {
            'topic_name': name,
            'total_score': total_score,
            'heat_score': heat['heat_score'],
            'mainline_strength_score': strength['mainline_score'],
            'lifecycle_stage': strength.get('lifecycle_stage', '未知'),
            'risk_level': risk_level,
            'leader_stock': strength.get('leader_name', ''),
            'center_stock': '',
        }
        combined_list.append(combined_entry)
    
    # 排序
    hot_list.sort(key=lambda x: x['heat_score'], reverse=True)
    mainline_list.sort(key=lambda x: x['mainline_strength_score'], reverse=True)
    combined_list.sort(key=lambda x: x['total_score'], reverse=True)
    
    # 加排名
    for i, entry in enumerate(hot_list):
        entry['rank'] = i + 1
    for i, entry in enumerate(mainline_list):
        entry['rank'] = i + 1
    for i, entry in enumerate(combined_list):
        entry['rank'] = i + 1
    
    # 取前15
    hot_list = hot_list[:15]
    mainline_list = mainline_list[:15]
    combined_list = combined_list[:15]
    
    return {
        'date': today,
        'hot_rankings': hot_list,
        'mainline_rankings': mainline_list,
        'combined_rankings': combined_list,
    }


if __name__ == '__main__':
    rankings = compute_all_rankings()
    print(f"\n{'='*50}")
    print(f"📊 热门题材与主线题材排行 [{rankings['date']}]")
    print(f"{'='*50}")
    print(f"\n🔥 热度最高前5:")
    for r in rankings['hot_rankings'][:5]:
        print(f"  {r['rank']}. {r['topic_name']}: {r['heat_score']}分")
    print(f"\n💪 主线强度前5:")
    for r in rankings['mainline_rankings'][:5]:
        print(f"  {r['rank']}. {r['topic_name']}: {r['mainline_strength_score']}分")
    print(f"\n⭐ 又热又强前5:")
    for r in rankings['combined_rankings'][:5]:
        print(f"  {r['rank']}. {r['topic_name']}: {r['total_score']}分")
