"""
五维评分引擎 (v2)
================
从 lifecycle.py 提取独立的评分模块
"""
from typing import Dict, Any


def score_price_strength(topic_data: dict) -> float:
    """价格强度评分 (0-100) 权重 0.30"""
    score = 0
    
    zt = topic_data.get('zt_count', 0)
    if zt >= 20: score += 30
    elif zt >= 10: score += 25
    elif zt >= 5: score += 20
    elif zt >= 3: score += 15
    elif zt >= 1: score += 8
    
    leader_board = topic_data.get('leader_board', 0)
    if leader_board >= 7: score += 25
    elif leader_board >= 5: score += 22
    elif leader_board >= 4: score += 18
    elif leader_board >= 3: score += 14
    elif leader_board >= 2: score += 8
    elif leader_board >= 1: score += 4
    
    trend = topic_data.get('board_trend', 'flat')
    if trend == 'strong_up': score += 25
    elif trend == 'up': score += 18
    elif trend == 'flat': score += 10
    elif trend == 'down': score += 5
    elif trend == 'strong_down': score += 0
    
    zt_change = topic_data.get('zt_change', 0)
    if zt_change >= 10: score += 20
    elif zt_change >= 5: score += 16
    elif zt_change >= 0: score += 12
    elif zt_change >= -5: score += 6
    else: score += 2
    
    return min(score, 100)


def score_capital_strength(topic_data: dict) -> float:
    """资金强度评分 (0-100) 权重 0.25"""
    score = 0
    
    net_inflow = topic_data.get('net_inflow', 0)
    if net_inflow >= 10: score += 30
    elif net_inflow >= 5: score += 25
    elif net_inflow >= 1: score += 18
    elif net_inflow >= 0: score += 10
    elif net_inflow >= -5: score += 5
    else: score += 0
    
    volume_change = topic_data.get('volume_change', 0)
    if volume_change >= 50: score += 25
    elif volume_change >= 30: score += 20
    elif volume_change >= 10: score += 15
    elif volume_change >= 0: score += 8
    else: score += 3
    
    institution_count = topic_data.get('institution_count', 0)
    if institution_count >= 5: score += 25
    elif institution_count >= 3: score += 20
    elif institution_count >= 1: score += 12
    else: score += 5
    
    big_order_ratio = topic_data.get('big_order_ratio', 0)
    if big_order_ratio >= 30: score += 20
    elif big_order_ratio >= 20: score += 15
    elif big_order_ratio >= 10: score += 10
    elif big_order_ratio >= 0: score += 5
    
    return min(score, 100)


def score_catalyst_strength(topic_data: dict) -> float:
    """催化强度评分 (0-100) 权重 0.20"""
    score = 0
    catalysts = topic_data.get('catalysts', [])
    
    if not catalysts:
        return 5
    
    c_count = len(catalysts)
    if c_count >= 10: score += 25
    elif c_count >= 7: score += 20
    elif c_count >= 5: score += 16
    elif c_count >= 3: score += 12
    elif c_count >= 1: score += 6
    
    max_level = 0
    level_map = {'national': 5, 'ministry': 4, 'local': 3, 'company': 2, 'media': 1}
    for c in catalysts:
        lvl = c.get('level') or c.get('event_level', '')
        max_level = max(max_level, level_map.get(lvl, 0))
    level_scores = {5: 30, 4: 25, 3: 18, 2: 10, 1: 5, 0: 0}
    score += level_scores.get(max_level, 0)
    
    is_continuous = topic_data.get('catalyst_continuous', False)
    is_escalating = topic_data.get('catalyst_escalating', False)
    if is_continuous and is_escalating: score += 25
    elif is_continuous: score += 18
    elif is_escalating: score += 12
    else: score += 5
    
    landed_count = sum(1 for c in catalysts if c.get('is_landed', False) or c.get('is_confirmed', False))
    if landed_count >= 3: score += 20
    elif landed_count >= 2: score += 15
    elif landed_count >= 1: score += 10
    else: score += 4
    
    return min(score, 100)


def score_sentiment_strength(topic_data: dict) -> float:
    """热度强度评分 (0-100) 权重 0.15"""
    score = 0
    
    media_count = topic_data.get('media_count', 0)
    if media_count >= 20: score += 30
    elif media_count >= 10: score += 25
    elif media_count >= 5: score += 18
    elif media_count >= 3: score += 12
    elif media_count >= 1: score += 6
    
    sentiment_change = topic_data.get('sentiment_change', 0)
    if sentiment_change >= 100: score += 30
    elif sentiment_change >= 50: score += 25
    elif sentiment_change >= 20: score += 18
    elif sentiment_change >= 0: score += 10
    elif sentiment_change >= -20: score += 5
    else: score += 2
    
    daily_change = topic_data.get('daily_sentiment_change', 0)
    if daily_change >= 30: score += 20
    elif daily_change >= 10: score += 15
    elif daily_change >= 0: score += 8
    else: score += 3
    
    score += 10  # 百度指数暂缺
    
    return min(score, 100)


def score_structure_quality(topic_data: dict) -> float:
    """结构质量评分 (0-100) 权重 0.10"""
    score = 0
    
    ladder_levels = topic_data.get('ladder_levels', 0)
    if ladder_levels >= 4: score += 30
    elif ladder_levels >= 3: score += 25
    elif ladder_levels >= 2: score += 18
    elif ladder_levels >= 1: score += 10
    
    has_center = topic_data.get('has_center_stock', False)
    score += 25 if has_center else 8
    
    has_expansion = topic_data.get('has_expansion', False)
    if has_expansion: score += 25
    else:
        score += 10 if topic_data.get('leader_board', 0) >= 3 else 5
    
    seal_rate = topic_data.get('seal_rate', 0)
    if seal_rate >= 80: score += 20
    elif seal_rate >= 60: score += 15
    elif seal_rate >= 40: score += 10
    else: score += 4
    
    return min(score, 100)


def calculate_total(price: float, capital: float, catalyst: float, sentiment: float, structure: float) -> float:
    """计算加权总分"""
    return round(
        price * 0.30 + capital * 0.25 + catalyst * 0.20 + sentiment * 0.15 + structure * 0.10,
        1
    )


def get_all_scores(topic_data: dict) -> dict:
    """对 topic_data 计算全部5维度评分，返回完整 scores dict"""
    ps = score_price_strength(topic_data)
    cs = score_capital_strength(topic_data)
    cat = score_catalyst_strength(topic_data)
    ss = score_sentiment_strength(topic_data)
    sq = score_structure_quality(topic_data)
    total = calculate_total(ps, cs, cat, ss, sq)
    
    return {
        'total_score': total,
        'price_strength': round(ps, 1),
        'capital_strength': round(cs, 1),
        'catalyst_strength': round(cat, 1),
        'sentiment_strength': round(ss, 1),
        'structure_quality': round(sq, 1),
    }


if __name__ == '__main__':
    test_data = {
        'zt_count': 8, 'leader_board': 4, 'board_trend': 'up', 'zt_change': 3,
        'net_inflow': 2.5, 'volume_change': 35, 'institution_count': 2, 'big_order_ratio': 15,
        'catalysts': [{'level': 'national'}, {'level': 'ministry'}],
        'catalyst_continuous': True, 'catalyst_escalating': True,
        'media_count': 12, 'sentiment_change': 60, 'daily_sentiment_change': 25,
        'ladder_levels': 3, 'has_center_stock': True, 'has_expansion': True, 'seal_rate': 75,
    }
    scores = get_all_scores(test_data)
    print(f'Scores: {scores}')
    tot = scores['total_score']
    assert 60 <= tot <= 80, f'Expected 60-80, got {tot}'
    print('✅ scorer.py 验证通过')
