"""
题材生命周期分析引擎
=====================
按 JSON 框架的 5 维度评分模型 + 7 阶段判定规则
依赖：悟道 API (stock.quicktiny.cn) + akshare + 本地数据库
"""
import os
import json
import re
import requests
from datetime import date, datetime, timedelta
from typing import Optional

from backend.models import query, insert, insert_many, execute

# ── 配置 ──
API_BASE = "https://stock.quicktiny.cn/api/openclaw"

def _get_api_key():
    """获取悟道 API Key"""
    KEY = os.environ.get('LB_API_KEY', '')
    if not KEY:
        try:
            with open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')) as f:
                for line in f:
                    if line.startswith('LB_API_KEY='):
                        KEY = line.strip().split('=', 1)[1]
                        break
        except:
            pass
    if not KEY:
        KEY = "lb_1325c45a076a931746b446eba05812df3fabcfeca35b4655603670999119484b"
    return KEY

def _api_get(path, params=None):
    """调用悟道 API"""
    key = _get_api_key()
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        print(f"  ⚠️ 悟道API调用失败 {path}: {e}")
        return None


# ═══════════════════════════════════════════════
# 1. 数据收集层
# ═══════════════════════════════════════════════

def collect_concept_ranking(today=None):
    """获取概念排行（悟道API）"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    data = _api_get("/concept-ranking", {"date": today})
    if data and data.get('ok'):
        return data['data']
    return []

def collect_hot_wind(today=None):
    """获取最强风口"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    data = _api_get("/hot-wind", {"date": today})
    if data and data.get('ok'):
        return data['data']
    return []

def collect_sector_analysis(today=None):
    """获取板块分析"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    data = _api_get("/sector-analysis", {"date": today})
    if data and data.get('ok'):
        return data['data']
    return []

def collect_limitup_data(today=None):
    """获取涨停池"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    try:
        import akshare as ak
        df = ak.stock_zt_pool_em(date=today.replace('-', ''))
        if df is not None and len(df) > 0:
            return df.to_dict('records')
    except:
        pass
    
    # fallback: 从本地 zt_stocks 表获取
    rows = query("SELECT * FROM zt_stocks WHERE date=?", (today,))
    if rows:
        return rows
    return []

def collect_daily_brief(today=None):
    """获取每日简报（含催化事件）"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    data = _api_get("/daily-brief", {"date": today})
    if data and data.get('ok'):
        return data['data']
    return {}

def collect_cls_news(today=None, keywords=None):
    """从财联社快讯筛选与题材相关的新闻"""
    try:
        news = query("SELECT * FROM cls_news WHERE date=? ORDER BY created_at DESC", (today,)) if today else []
    except:
        news = []
    if keywords:
        news = [n for n in news if any(kw in str(n.get('title', '')) + str(n.get('content', '')) for kw in keywords)]
    return news

def collect_sentiment_from_db(today, topic_keywords):
    """从本地帖子数据统计热度变化"""
    # 统计股吧/JY/雪球 包含关键词的帖子数量
    all_posts = query("SELECT platform, COUNT(*) as cnt FROM posts WHERE date=? GROUP BY platform", (today,))
    
    # 昨日对比
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_posts = query("SELECT platform, COUNT(*) as cnt FROM posts WHERE date=? GROUP BY platform", (yesterday,))
    
    # 按关键词过滤
    kw_posts = query("SELECT platform, COUNT(*) as cnt FROM posts WHERE date=? AND (title LIKE ? OR content LIKE ?) GROUP BY platform",
                     (today, f'%{topic_keywords[0]}%', f'%{topic_keywords[0]}%')) if topic_keywords else []
    
    return {
        'total_today': sum(r['cnt'] for r in all_posts) if all_posts else 0,
        'total_yesterday': sum(r['cnt'] for r in yesterday_posts) if yesterday_posts else 0,
        'keyword_today': sum(r['cnt'] for r in kw_posts) if kw_posts else 0,
    }


# ═══════════════════════════════════════════════
# 2. 评分层 — 5 维度
# ═══════════════════════════════════════════════

def score_price_strength(topic_data):
    """价格强度评分 (0-100) 权重 0.30"""
    score = 0
    
    # 因子1: 涨停家数 (30分)
    zt = topic_data.get('zt_count', 0)
    if zt >= 20: score += 30
    elif zt >= 10: score += 25
    elif zt >= 5: score += 20
    elif zt >= 3: score += 15
    elif zt >= 1: score += 8
    
    # 因子2: 龙头连板高度 (25分)
    leader_board = topic_data.get('leader_board', 0)
    if leader_board >= 7: score += 25
    elif leader_board >= 5: score += 22
    elif leader_board >= 4: score += 18
    elif leader_board >= 3: score += 14
    elif leader_board >= 2: score += 8
    elif leader_board >= 1: score += 4
    
    # 因子3: 板块近5日涨幅趋势 (25分)
    trend = topic_data.get('board_trend', 'flat')
    if trend == 'strong_up': score += 25
    elif trend == 'up': score += 18
    elif trend == 'flat': score += 10
    elif trend == 'down': score += 5
    elif trend == 'strong_down': score += 0
    
    # 因子4: 涨停家数变化 (20分)
    zt_change = topic_data.get('zt_change', 0)  # 今日-昨日
    if zt_change >= 10: score += 20
    elif zt_change >= 5: score += 16
    elif zt_change >= 0: score += 12
    elif zt_change >= -5: score += 6
    else: score += 2
    
    return min(score, 100)


def score_capital_strength(topic_data):
    """资金强度评分 (0-100) 权重 0.25"""
    score = 0
    
    # 因子1: 主力净流入 (30分)
    net_inflow = topic_data.get('net_inflow', 0)  # 亿
    if net_inflow >= 10: score += 30
    elif net_inflow >= 5: score += 25
    elif net_inflow >= 1: score += 18
    elif net_inflow >= 0: score += 10
    elif net_inflow >= -5: score += 5
    else: score += 0
    
    # 因子2: 成交额变化 (25分)
    volume_change = topic_data.get('volume_change', 0)  # 百分比
    if volume_change >= 50: score += 25
    elif volume_change >= 30: score += 20
    elif volume_change >= 10: score += 15
    elif volume_change >= 0: score += 8
    else: score += 3
    
    # 因子3: 龙虎榜机构参与 (25分)
    institution_count = topic_data.get('institution_count', 0)
    if institution_count >= 5: score += 25
    elif institution_count >= 3: score += 20
    elif institution_count >= 1: score += 12
    else: score += 5
    
    # 因子4: 大单占比 (20分)
    big_order_ratio = topic_data.get('big_order_ratio', 0)
    if big_order_ratio >= 30: score += 20
    elif big_order_ratio >= 20: score += 15
    elif big_order_ratio >= 10: score += 10
    elif big_order_ratio >= 0: score += 5
    
    return min(score, 100)


def score_catalyst_strength(topic_data):
    """催化强度评分 (0-100) 权重 0.20"""
    score = 0
    catalysts = topic_data.get('catalysts', [])
    
    if not catalysts:
        return 5  # 无催化底分
    
    # 因子1: 催化数量 (25分)
    c_count = len(catalysts)
    if c_count >= 10: score += 25
    elif c_count >= 7: score += 20
    elif c_count >= 5: score += 16
    elif c_count >= 3: score += 12
    elif c_count >= 1: score += 6
    
    # 因子2: 催化级别 (30分)
    max_level = 0
    for c in catalysts:
        lvl = c.get('level', '')
        if lvl == '国家级': max_level = max(max_level, 5)
        elif lvl == '部委级': max_level = max(max_level, 4)
        elif lvl == '地方级': max_level = max(max_level, 3)
        elif lvl == '公司级': max_level = max(max_level, 2)
        elif lvl == '媒体级': max_level = max(max_level, 1)
    
    level_scores = {5: 30, 4: 25, 3: 18, 2: 10, 1: 5, 0: 0}
    score += level_scores.get(max_level, 0)
    
    # 因子3: 催化连续性 (25分)
    is_continuous = topic_data.get('catalyst_continuous', False)
    is_escalating = topic_data.get('catalyst_escalating', False)
    if is_continuous and is_escalating: score += 25
    elif is_continuous: score += 18
    elif is_escalating: score += 12
    else: score += 5
    
    # 因子4: 催化落地情况 (20分)
    landed_count = sum(1 for c in catalysts if c.get('is_landed', False))
    if landed_count >= 3: score += 20
    elif landed_count >= 2: score += 15
    elif landed_count >= 1: score += 10
    else: score += 4
    
    return min(score, 100)


def score_sentiment_strength(topic_data):
    """热度强度评分 (0-100) 权重 0.15"""
    score = 0
    
    # 因子1: 媒体报道频次 (30分)
    media_count = topic_data.get('media_count', 0)
    if media_count >= 20: score += 30
    elif media_count >= 10: score += 25
    elif media_count >= 5: score += 18
    elif media_count >= 3: score += 12
    elif media_count >= 1: score += 6
    
    # 因子2: 社区讨论量变化 (30分)
    sentiment_change = topic_data.get('sentiment_change', 0)  # 百分比
    if sentiment_change >= 100: score += 30
    elif sentiment_change >= 50: score += 25
    elif sentiment_change >= 20: score += 18
    elif sentiment_change >= 0: score += 10
    elif sentiment_change >= -20: score += 5
    else: score += 2
    
    # 因子3: 近1日变化率 (20分)
    daily_change = topic_data.get('daily_sentiment_change', 0)
    if daily_change >= 30: score += 20
    elif daily_change >= 10: score += 15
    elif daily_change >= 0: score += 8
    else: score += 3
    
    # 因子4: 百度指数/微信指数 (20分)
    # 暂缺数据源，给中性分
    score += 10
    
    return min(score, 100)


def score_structure_quality(topic_data):
    """结构质量评分 (0-100) 权重 0.10"""
    score = 0
    
    # 因子1: 梯队完整性 (30分)
    ladder_levels = topic_data.get('ladder_levels', 0)  # 有几个板次
    if ladder_levels >= 4: score += 30
    elif ladder_levels >= 3: score += 25
    elif ladder_levels >= 2: score += 18
    elif ladder_levels >= 1: score += 10
    
    # 因子2: 是否有中军 (25分)
    has_center = topic_data.get('has_center_stock', False)
    score += 25 if has_center else 8
    
    # 因子3: 前后排联动 (25分)
    has_expansion = topic_data.get('has_expansion', False)
    if has_expansion: score += 25
    else:
        # 龙头独立走势
        if topic_data.get('leader_board', 0) >= 3:
            score += 10  # 局部抱团
        else:
            score += 5
    
    # 因子4: 涨停封板质量 (20分)
    seal_rate = topic_data.get('seal_rate', 0)
    if seal_rate >= 80: score += 20
    elif seal_rate >= 60: score += 15
    elif seal_rate >= 40: score += 10
    else: score += 4
    
    return min(score, 100)


# ═══════════════════════════════════════════════
# 3. 生命周期分类器 + 风险检测器
# ═══════════════════════════════════════════════

def classify_lifecycle(scores, topic_data):
    """
    根据5维度评分 + 辅助指标，判定生命周期阶段
    返回: (stage_name, reasons_list)
    """
    total = scores['total']
    ps = scores['price_strength']
    cs = scores['capital_strength']
    cat_s = scores['catalyst_strength']
    ss = scores['sentiment_strength']
    sq = scores['structure_quality']
    
    zt = topic_data.get('zt_count', 0)
    leader_board = topic_data.get('leader_board', 0)
    zt_change = topic_data.get('zt_change', 0)
    has_center = topic_data.get('has_center_stock', False)
    has_expansion = topic_data.get('has_expansion', False)
    has_risk = topic_data.get('has_risk', False)
    catalyst_continuous = topic_data.get('catalyst_continuous', False)
    catalysts_count = len(topic_data.get('catalysts', []))
    
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
    if (55 <= total <= 75 and 
        (ps >= 55 and (cs < 45 or sq < 40))):
        reasons.append(f"总分{total}，价格偏强({ps})但资金({cs})或结构({sq})偏弱")
        if not has_expansion:
            reasons.append("后排未能有效跟随，龙头独立行情")
        if has_risk:
            reasons.append("检测到风险信号")
        return "分歧震荡期", reasons
    
    # ── 启动期判定 ──
    if (50 <= total < 65 and ps >= 40 and cat_s >= 40 and
        zt >= 2 and leader_board >= 1):
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
    if (45 <= total <= 65 and cat_s >= 45 and 
        leader_board >= 2 and catalyst_continuous):
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


def detect_risks(topic_data, today=None):
    """检测风险信号"""
    risks = []
    
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    # 1. 龙头断板
    leader_board = topic_data.get('leader_board', 0)
    leader_name = topic_data.get('leader_name', '')
    yesterday_board = topic_data.get('yesterday_leader_board', 0)
    if yesterday_board > 0 and leader_board < yesterday_board:
        risks.append({
            'risk_type': '断板',
            'stock_name': leader_name,
            'description': f'龙头{leader_name}从{yesterday_board}板断至{leader_board}板',
            'severity': 'critical'
        })
    
    # 2. 高位巨震（龙头高换手+冲高回落）
    leader_turnover = topic_data.get('leader_turnover', 0)
    if leader_board >= 4 and leader_turnover >= 30:
        risks.append({
            'risk_type': '高位巨震',
            'stock_name': leader_name,
            'description': f'龙头{leader_name}高位换手{leader_turnover}%，分歧加大',
            'severity': 'warning'
        })
    
    # 3. 梯队断层
    ladder_levels = topic_data.get('ladder_levels', 0)
    if leader_board >= 3 and ladder_levels <= 1:
        risks.append({
            'risk_type': '梯队断层',
            'stock_name': '',
            'description': f'最高{leader_board}板但梯队断层，仅龙头独立走强',
            'severity': 'warning'
        })
    
    # 4. 板块拥挤（涨停太多但资金流入放缓）
    zt = topic_data.get('zt_count', 0)
    net_inflow = topic_data.get('net_inflow', 0)
    if zt >= 10 and net_inflow < 0:
        risks.append({
            'risk_type': '板块拥挤',
            'stock_name': '',
            'description': f'涨停{zt}家但主力净流入为负({net_inflow}亿)，资金边打边撤',
            'severity': 'warning'
        })
    
    # 5. 检查本地风险事件表
    existing_risks = query(
        "SELECT * FROM topic_risk_events WHERE date=? AND topic_name=?",
        (today, topic_data.get('topic_name', ''))
    )
    for r in existing_risks:
        risks.append({
            'risk_type': r['risk_type'],
            'stock_name': r['stock_name'],
            'description': r['description'],
            'severity': r['severity']
        })
    
    return risks


# ═══════════════════════════════════════════════
# 4. 主动题材发现
# ═══════════════════════════════════════════════

def discover_active_topics(today=None):
    """从涨停池+概念排行发现当日活跃题材"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    topics = []
    
    # 1. 从涨停池按行业分组
    stocks = query(
        "SELECT sector, COUNT(*) as cnt, MAX(board_num) as mb FROM zt_stocks WHERE date=? AND sector!='' GROUP BY sector ORDER BY cnt DESC LIMIT 15",
        (today,)
    )
    
    for s in stocks:
        topics.append({
            'name': s['sector'],
            'zt_count': s['cnt'],
            'max_board': s['mb'],
            'source': '涨停池行业分组'
        })
    
    # 2. 从概念排行补充（悟道API）
    concepts = collect_concept_ranking(today)
    for c in concepts:
        name = c.get('concept_name', c.get('name', ''))
        if name and not any(t['name'] == name for t in topics):
            topics.append({
                'name': name,
                'zt_count': c.get('zt_count', c.get('limit_up_count', 0)),
                'max_board': c.get('max_board', 0),
                'source': '概念排行'
            })
    
    # 3. 从最强风口补充
    winds = collect_hot_wind(today)
    for w in winds:
        name = w.get('wind_name', w.get('name', ''))
        if name and not any(t['name'] == name for t in topics):
            topics.append({
                'name': name,
                'zt_count': w.get('zt_count', 0),
                'max_board': w.get('max_board', 0),
                'source': '最强风口'
            })
    
    return topics


# ═══════════════════════════════════════════════
# 5. 主题数据填充
# ═══════════════════════════════════════════════

def enrich_topic_data(topic_name, today=None):
    """对单个题材进行深度数据收集"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    data = {
        'topic_name': topic_name,
        'zt_count': 0,
        'leader_name': '',
        'leader_board': 0,
        'center_name': '',
        'has_center_stock': False,
        'has_expansion': False,
        'ladder_levels': 0,
        'board_trend': 'flat',
        'zt_change': 0,
        'net_inflow': 0,
        'volume_change': 0,
        'institution_count': 0,
        'big_order_ratio': 0,
        'seal_rate': 60,
        'leader_turnover': 0,
        'yesterday_leader_board': 0,
        'has_risk': False,
        'catalysts': [],
        'catalyst_continuous': False,
        'catalyst_escalating': False,
        'media_count': 0,
        'sentiment_change': 0,
        'daily_sentiment_change': 0,
    }
    
    # 1. 从涨停池匹配该题材的个股
    stocks = query(
        "SELECT * FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ? OR name IN (SELECT stock_name FROM topic_components WHERE date=? AND topic_name=?)) ORDER BY board_num DESC",
        (today, f'%{topic_name}%', f'%{topic_name}%', today, topic_name)
    )
    
    if not stocks:
        # 尝试模糊匹配
        kw_match = query(
            "SELECT * FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ?) ORDER BY board_num DESC",
            (today, f'%{topic_name[:2]}%', f'%{topic_name[:2]}%')
        )
        stocks = kw_match
    
    if stocks:
        data['zt_count'] = len(stocks)
        data['leader_name'] = stocks[0]['name']
        data['leader_board'] = stocks[0]['board_num']
        
        # 统计板次分布
        boards = set()
        for s in stocks:
            boards.add(s['board_num'])
        data['ladder_levels'] = len(boards)
        
        # 判断是否有后排扩散
        data['has_expansion'] = len(stocks) >= 3 and len(boards) >= 2
        
        # 找中军（大成交额）
        big_stocks = [s for s in stocks if (s.get('float_mcap') or 0) >= 50 or (s.get('trade_amt') or 0) >= 5]
        if big_stocks:
            data['center_name'] = big_stocks[0]['name']
            data['has_center_stock'] = True
        
        # 龙头换手
        if stocks[0].get('turnovers') is not None:
            data['leader_turnover'] = stocks[0]['turnovers']
        
        # 昨日对比
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).strftime("%Y-%m-%d")
        y_stocks = query(
            "SELECT * FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ?) ORDER BY board_num DESC",
            (yesterday, f'%{topic_name}%', f'%{topic_name}%')
        )
        data['zt_change'] = len(stocks) - len(y_stocks)
        if y_stocks and y_stocks[0].get('board_num') is not None:
            data['yesterday_leader_board'] = y_stocks[0]['board_num']
    
    # 2. 查询本地已有催化
    existing_catalysts = query(
        "SELECT * FROM topic_catalysts WHERE topic_name=? AND date>=?", 
        (topic_name, (date.fromisoformat(today) - timedelta(days=7)).strftime("%Y-%m-%d"))
    )
    if existing_catalysts:
        data['catalysts'] = existing_catalysts
        data['catalyst_continuous'] = len(existing_catalysts) >= 3
        # 检查是否有升级趋势（最近事件级别更高）
        levels_order = {'媒体级': 1, '公司级': 2, '地方级': 3, '部委级': 4, '国家级': 5}
        if len(existing_catalysts) >= 2:
            last = existing_catalysts[-1].get('catalyst_level', '')
            first = existing_catalysts[0].get('catalyst_level', '')
            if levels_order.get(last, 0) >= levels_order.get(first, 0):
                data['catalyst_escalating'] = True
    
    # 3. 资金面数据（从昨日或估算）
    sector_data = query(
        "SELECT net_inflow, trade_amt FROM zt_stocks WHERE date=? AND sector LIKE ? LIMIT 5",
        (today, f'%{topic_name}%')
    )
    if sector_data:
        inflows = [s.get('net_inflow') or 0 for s in sector_data if s.get('net_inflow') is not None]
        amts = [s.get('trade_amt') or 0 for s in sector_data if s.get('trade_amt') is not None]
        if inflows:
            data['net_inflow'] = sum(inflows)
        if amts:
            data['big_order_ratio'] = min(sum(amts) * 10, 100)
    
    # 4. 热度数据
    sentiment = collect_sentiment_from_db(today, [topic_name])
    data['media_count'] = sentiment.get('keyword_today', 0)
    if sentiment.get('total_yesterday', 0) > 0:
        data['sentiment_change'] = ((sentiment['total_today'] - sentiment['total_yesterday']) / sentiment['total_yesterday']) * 100
    data['daily_sentiment_change'] = data['sentiment_change']
    
    # 5. 风险检测
    data['has_risk'] = bool(detect_risks(data, today))
    
    return data


# ═══════════════════════════════════════════════
# 6. 核心入口
# ═══════════════════════════════════════════════

def analyze_topic(topic_name, analysis_date=None):
    """
    分析单个题材的生命周期阶段
    返回完整分析结果的 dict （符合 JSON 框架输出格式）
    """
    if not analysis_date:
        analysis_date = date.today().strftime("%Y-%m-%d")
    
    print(f"  🔍 分析题材: {topic_name} ({analysis_date})")
    
    # Step 1: 收集数据
    topic_data = enrich_topic_data(topic_name, analysis_date)
    
    # Step 2: 5维度评分
    price_score = score_price_strength(topic_data)
    capital_score = score_capital_strength(topic_data)
    catalyst_score = score_catalyst_strength(topic_data)
    sentiment_score = score_sentiment_strength(topic_data)
    structure_score = score_structure_quality(topic_data)
    
    total_score = (
        price_score * 0.30 +
        capital_score * 0.25 +
        catalyst_score * 0.20 +
        sentiment_score * 0.15 +
        structure_score * 0.10
    )
    total_score = round(total_score, 1)
    
    # Step 3: 生命周期判定
    stage, reasons = classify_lifecycle({
        'total': total_score,
        'price_strength': price_score,
        'capital_strength': capital_score,
        'catalyst_strength': catalyst_score,
        'sentiment_strength': sentiment_score,
        'structure_quality': structure_score,
    }, topic_data)
    
    # Step 4: 风险检测
    risks = detect_risks(topic_data, analysis_date)
    
    # 存储原始数据
    raw_zt_count = topic_data.get('zt_count', 0)
    raw_leader_board = topic_data.get('leader_board', 0)
    
    # Step 5: 二波触发条件
    second_wave_conditions = []
    if stage == '余温反复/二波观察期':
        second_wave_conditions = [
            "龙头创出新高且板块涨停重新扩散",
            "出现国家级/部委级新催化",
            "板块成交额重新放大至前期高位",
        ]
    
    # Step 6: 后续观察点
    next_observations = []
    if stage in ('爆发期', '启动期'):
        next_observations.append("关注龙头是否继续晋级打开高度")
        next_observations.append("观察后排跟风力度是否持续")
        next_observations.append("关注板块成交额是否持续放大")
    elif stage == '分歧震荡期':
        next_observations.append("龙头能否分歧转一致继续走强")
        next_observations.append("后排是否止跌企稳")
        next_observations.append("新催化能否出现打破僵局")
    elif stage == '退潮期':
        next_observations.append("龙头是否止跌企稳")
        next_observations.append("是否有新题材替代")
        next_observations.append("板块成交额是否缩至地量")
    elif stage == '孕育期/预热期':
        next_observations.append("催化事件能否持续发酵")
        next_observations.append("是否有龙头率先连板打开空间")
        next_observations.append("板块涨停家数是否增加")
    
    # 组装结果
    result = {
        'topic_name': topic_name,
        'analysis_date': analysis_date,
        'lifecycle_stage': stage,
        'zt_count': raw_zt_count,
        'leader_board': raw_leader_board,
        'scores': {
            'total_score': total_score,
            'price_strength': round(price_score, 1),
            'capital_strength': round(capital_score, 1),
            'catalyst_strength': round(catalyst_score, 1),
            'sentiment_strength': round(sentiment_score, 1),
            'structure_quality': round(structure_score, 1),
        },
        'stage_judgement_reasons': reasons,
        'data_summary': {
            'board_change_5d': topic_data.get('board_trend', 'flat'),
            'board_change_10d': '',
            'board_turnover_change': '',
            'limit_up_count_change': f"{topic_data.get('zt_change', 0):+d}",
            'leader_stock': {
                'name': topic_data.get('leader_name', ''),
                'reason': '最高连板' if topic_data.get('leader_board') else '',
                'performance_summary': f"{topic_data.get('leader_board', 0)}连板" if topic_data.get('leader_board', 0) > 1 else "首板",
            },
            'center_stock': {
                'name': topic_data.get('center_name', ''),
                'performance_summary': '',
            },
            'capital_flow_summary': f"主力净流入{round(topic_data.get('net_inflow', 0), 2)}亿元" if topic_data.get('net_inflow', 0) != 0 else "资金面中性",
            'catalyst_summary': f"近7日{len(topic_data.get('catalysts', []))}件催化事件",
            'sentiment_summary': f"社区讨论量变化{round(topic_data.get('sentiment_change', 0), 1)}%",
        },
        'leader_and_structure': {
            'leader_stock': topic_data.get('leader_name', ''),
            'leader_reason': f"最高{ topic_data.get('leader_board', 0) }板" if topic_data.get('leader_board', 0) > 0 else "",
            'ladder_structure': f"{topic_data.get('ladder_levels', 0)}个板次",
            'has_center_stock': topic_data.get('has_center_stock', False),
            'has_follow_up_expansion': topic_data.get('has_expansion', False),
            'structure_comment': "梯队完整，前后排联动" if topic_data.get('has_expansion') else "局部抱团",
        },
        'catalyst_and_fundamentals': {
            'recent_7d_catalysts': [
                {'date': c.get('event_date', ''), 'title': c.get('title', ''), 'type': c.get('catalyst_type', ''), 'level': c.get('catalyst_level', '')}
                for c in topic_data.get('catalysts', [])
            ],
            'recent_30d_catalysts': [],
            'continuity_assessment': '催化持续' if topic_data.get('catalyst_continuous') else '催化偶发',
            'landing_assessment': '部分落地' if any(c.get('is_landed') for c in topic_data.get('catalysts', [])) else '预期阶段',
            'fundamental_verification': '',
        },
        'risk_warnings': risks,
        'next_observation_points': next_observations,
        'second_wave_trigger_conditions': second_wave_conditions,
        'skill_runtime_status': [],
        'data_sources': ['涨停池数据', '概念排行(悟道API)', '社区帖子', '本地数据库'],
    }
    
    # 保存到数据库
    _save_analysis(result)
    
    return result


def _save_analysis(result):
    """保存分析结果到 topic_lifecycle 表"""
    try:
        summary_json = json.dumps(result, ensure_ascii=False, default=str)
        
        insert('topic_lifecycle', {
            'date': result['analysis_date'],
            'topic_name': result['topic_name'],
            'lifecycle_stage': result['lifecycle_stage'],
            'total_score': result['scores']['total_score'],
            'price_strength': result['scores']['price_strength'],
            'capital_strength': result['scores']['capital_strength'],
            'catalyst_strength': result['scores']['catalyst_strength'],
            'sentiment_strength': result['scores']['sentiment_strength'],
            'structure_quality': result['scores']['structure_quality'],
            'zt_count': result.get('zt_count', 0),
            'leader_name': result['data_summary']['leader_stock'].get('name', ''),
            'leader_board': result.get('leader_board', 0),
            'center_name': result['data_summary']['center_stock'].get('name', ''),
            'summary_json': summary_json,
        })
        print(f"    ✅ 分析结果已保存到数据库")
    except Exception as e:
        print(f"    ⚠️ 保存失败: {e}")


def analyze_all_active_topics(today=None):
    """分析当日所有活跃题材"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    print(f"\n{'='*50}")
    print(f"📊 题材生命周期分析 [{today}]")
    print(f"{'='*50}")
    
    topics = discover_active_topics(today)
    print(f"  发现 {len(topics)} 个活跃题材")
    
    results = []
    for t in topics[:8]:  # 最多分析前8个
        result = analyze_topic(t['name'], today)
        results.append(result)
        print(f"    → {t['name']}: {result['lifecycle_stage']} (总分{result['scores']['total_score']})")
    
    print(f"{'='*50}\n")
    return results


if __name__ == '__main__':
    # 测试运行
    analyze_all_active_topics()
