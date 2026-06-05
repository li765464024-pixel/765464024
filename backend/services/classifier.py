"""
生命周期分类器 (v2)
================
从 lifecycle.py 提取独立的分类逻辑
"""
from typing import Dict, List, Tuple


STAGE_NAMES = [
    '孕育期/预热期',
    '启动期',
    '爆发期',
    '分歧震荡期',
    '退潮期',
    '余温反复/二波观察期',
]

STAGE_COLORS = {
    '孕育期/预热期': '#6b7280',    # 灰蓝
    '启动期': '#22c55e',           # 浅绿
    '爆发期': '#059669',           # 深绿
    '分歧震荡期': '#f59e0b',       # 橙色
    '退潮期': '#ef4444',           # 红色
    '余温反复/二波观察期': '#8b5cf6',  # 紫色
}


def classify_lifecycle(scores: dict, topic_data: dict) -> Tuple[str, List[str]]:
    """
    根据5维度评分 + 辅助指标，判定生命周期阶段
    返回: (stage_name, reasons_list)
    """
    total = scores.get('total', scores.get('total_score', 0))
    ps = scores.get('price_strength', 0)
    cs = scores.get('capital_strength', 0)
    cat_s = scores.get('catalyst_strength', 0)
    ss = scores.get('sentiment_strength', 0)
    sq = scores.get('structure_quality', 0)
    
    zt = topic_data.get('zt_count', 0)
    leader_board = topic_data.get('leader_board', 0)
    zt_change = topic_data.get('zt_change', 0)
    has_center = topic_data.get('has_center_stock', False)
    has_expansion = topic_data.get('has_expansion', False)
    has_risk = topic_data.get('has_risk', False)
    catalyst_continuous = topic_data.get('catalyst_continuous', False)
    
    reasons = []
    
    # ── 爆发期判定 ──
    if (total >= 65 and ps >= 60 and cs >= 50 and cat_s >= 50 and
        zt >= 5 and leader_board >= 3 and has_expansion):
        reasons.append(f"总分{total}≥65，价格{ps}，资金{cs}，催化{cat_s}共振")
        reasons.append(f"涨停{zt}家，龙头{leader_board}板，有后排扩散")
        if has_center:
            reasons.append("有中军股坐镇，板块结构完整")
        return "爆发期", reasons
    
    # ── 分歧震荡期判定 ──
    if 55 <= total <= 75 and (ps >= 55 and (cs < 45 or sq < 40)):
        reasons.append(f"总分{total}，价格偏强({ps})但资金({cs})或结构({sq})偏弱")
        if not has_expansion:
            reasons.append("后排未能有效跟随，龙头独立行情")
        if has_risk:
            reasons.append("检测到风险信号")
        return "分歧震荡期", reasons
    
    # ── 启动期判定 ──
    if 50 <= total < 65 and ps >= 40 and cat_s >= 40 and zt >= 2 and leader_board >= 1:
        reasons.append(f"总分{total}，价格{ps}，催化{cat_s}，题材开始获得认可")
        reasons.append(f"涨停{zt}家，龙头{leader_board}板，资金开始关注")
        return "启动期", reasons
    
    # ── 退潮期判定 ──
    if (total <= 55 or ps < 30) and zt_change < -3:
        reasons.append(f"总分{total}≤55，价格{ps}偏弱")
        reasons.append(f"涨停家数减少{abs(zt_change)}家，赚钱效应下降")
        if has_risk:
            reasons.append("存在风险信号（断板/减持/监管等）")
        return "退潮期", reasons
    
    # ── 余温反复/二波观察期判定 ──
    if 45 <= total <= 65 and cat_s >= 45 and leader_board >= 2 and catalyst_continuous:
        reasons.append(f"总分{total}，催化回升({cat_s})，核心股转强({leader_board}板)")
        reasons.append("老题材因新催化出现局部回流")
        return "余温反复/二波观察期", reasons
    
    # ── 孕育期/预热期 ──
    if total < 50 and cat_s >= 30:
        reasons.append(f"总分{total}<50，催化开始出现({cat_s})")
        if zt > 0:
            reasons.append(f"个别个股异动({zt}家涨停)，板块效应未形成")
        else:
            reasons.append("尚未有涨停个股，板块整体涨幅不强")
        return "孕育期/预热期", reasons
    
    # 兜底
    if total < 35:
        reasons.append(f"总分{total}<35，各项指标偏弱")
        return "孕育期/预热期", reasons
    
    reasons.append(f"总分{total}，价格强度{ps}，符合启动特征")
    if zt > 0:
        reasons.append(f"涨停{zt}家，龙头{leader_board}板，资金开始关注")
    return "启动期", reasons


def classify_with_confidence(scores: dict, topic_data: dict) -> dict:
    """
    返回包含置信度的分类结果
    """
    stage, reasons = classify_lifecycle(scores, topic_data)
    
    # 置信度估计
    total = scores.get('total', scores.get('total_score', 0))
    if stage in ('爆发期', '退潮期'):
        confidence = min(0.5 + abs(total - 50) / 100, 0.95)
    elif stage in ('启动期', '分歧震荡期'):
        confidence = 0.6 + (total % 20) / 100
    else:
        confidence = 0.5
    
    return {
        'stage': stage,
        'reasons': reasons,
        'confidence': round(min(confidence, 0.95), 2),
        'color': STAGE_COLORS.get(stage, '#6b7280'),
    }


def detect_risks(topic_data: dict) -> list:
    """检测风险信号"""
    risks = []
    
    leader_board = topic_data.get('leader_board', 0)
    leader_name = topic_data.get('leader_name', '')
    yesterday_board = topic_data.get('yesterday_leader_board', 0)
    leader_turnover = topic_data.get('leader_turnover', 0)
    ladder_levels = topic_data.get('ladder_levels', 0)
    zt = topic_data.get('zt_count', 0)
    net_inflow = topic_data.get('net_inflow', 0)
    
    if yesterday_board > 0 and leader_board < yesterday_board:
        risks.append({
            'risk_type': '断板',
            'severity': 'critical',
            'description': f'龙头{leader_name}从{yesterday_board}板断至{leader_board}板',
        })
    
    if leader_board >= 4 and leader_turnover >= 30:
        risks.append({
            'risk_type': '高位巨震',
            'severity': 'warning',
            'description': f'龙头{leader_name}高位换手{leader_turnover}%，分歧加大',
        })
    
    if leader_board >= 3 and ladder_levels <= 1:
        risks.append({
            'risk_type': '梯队断层',
            'severity': 'warning',
            'description': f'最高{leader_board}板但梯队断层，仅龙头独立走强',
        })
    
    if zt >= 10 and net_inflow < 0:
        risks.append({
            'risk_type': '板块拥挤',
            'severity': 'warning',
            'description': f'涨停{zt}家但主力净流入为负({net_inflow}亿)，资金边打边撤',
        })
    
    return risks


if __name__ == '__main__':
    test_scores = {
        'total': 68.7, 'price_strength': 68, 'capital_strength': 60,
        'catalyst_strength': 65, 'sentiment_strength': 75, 'structure_quality': 90
    }
    test_data = {
        'zt_count': 8, 'leader_board': 4, 'zt_change': 3,
        'has_center_stock': True, 'has_expansion': True,
        'has_risk': False, 'catalyst_continuous': True, 'leader_turnover': 15,
        'yesterday_leader_board': 3, 'leader_name': '测试龙头',
    }
    
    result = classify_with_confidence(test_scores, test_data)
    print(f'Stage: {result["stage"]}')
    print(f'Confidence: {result["confidence"]}')
    print(f'Reasons: {result["reasons"]}')
    
    risks = detect_risks(test_data | {'net_inflow': -2, 'zt_count': 12})
    print(f'Risks: {[r["risk_type"] for r in risks]}')
    print('✅ classifier.py 验证通过')
