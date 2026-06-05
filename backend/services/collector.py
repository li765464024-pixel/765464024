"""
数据采集引擎 (v2)
================
官方来源优先、多平台交叉采集
"""
import os
import json
import re
import requests
from datetime import date, datetime, timedelta

from backend.models import query, insert, insert_many

# ── 配置 ──
API_BASE = "https://stock.quicktiny.cn/api/openclaw"

def _get_api_key():
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
    return KEY or "lb_1325c45a076a931746b446eba05812df3fabcfeca35b4655603670999119484b"

def _api_get(path, params=None):
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
# 1. 题材信息采集
# ═══════════════════════════════════════════════

def collect_active_topics(today=None):
    """采集当日活跃题材列表（多源聚合）"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    topics_map = {}  # name -> info
    
    # 来源1: 涨停池行业分组
    stocks = query(
        "SELECT sector, COUNT(*) as cnt, MAX(board_num) as mb FROM zt_stocks WHERE date=? AND sector!='' GROUP BY sector ORDER BY cnt DESC LIMIT 20",
        (today,)
    )
    for s in stocks:
        name = s['sector']
        topics_map[name] = {
            'name': name,
            'zt_count': s['cnt'],
            'max_board': s['mb'],
            'sources': ['涨停池'],
            'aliases': [],
        }
    
    # 来源2: 悟道概念排行
    concepts = _api_get("/concept-ranking", {"date": today})
    if concepts and concepts.get('ok'):
        for c in concepts['data']:
            name = c.get('concept_name', c.get('name', ''))
            if name and name not in topics_map:
                topics_map[name] = {
                    'name': name,
                    'zt_count': c.get('zt_count', 0),
                    'max_board': c.get('max_board', 0),
                    'sources': ['概念排行'],
                    'aliases': [],
                }
            elif name:
                topics_map[name]['sources'].append('概念排行')
    
    # 来源3: 最强风口
    winds = _api_get("/hot-wind", {"date": today})
    if winds and winds.get('ok'):
        for w in winds['data']:
            name = w.get('wind_name', w.get('name', ''))
            if name and name not in topics_map:
                topics_map[name] = {
                    'name': name,
                    'zt_count': w.get('zt_count', 0),
                    'max_board': w.get('max_board', 0),
                    'sources': ['最强风口'],
                    'aliases': [],
                }
    
    return list(topics_map.values())


def collect_topic_components(topic_id, topic_name, today=None):
    """采集题材成分股 — 从涨停池+旧成分股表匹配"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    # 从涨停池匹配
    stocks = query(
        "SELECT code, name, board_num, trade_amt, float_mcap FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ?) ORDER BY board_num DESC",
        (today, f'%{topic_name}%', f'%{topic_name}%')
    )
    
    if not stocks:
        stocks = query(
            "SELECT code, name, board_num, trade_amt, float_mcap FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ?) ORDER BY board_num DESC",
            (today, f'%{topic_name[:2]}%', f'%{topic_name[:2]}%')
        )
    
    components = []
    for s in stocks:
        # 判定角色
        if s['board_num'] and s['board_num'] >= 2:
            ctype = 'leader_candidate'
        elif (s['float_mcap'] or 0) >= 50 or (s['trade_amt'] or 0) >= 5:
            ctype = 'center_candidate'
        else:
            ctype = 'follow_up_candidate'
        
        components.append({
            'topic_id': topic_id,
            'stock_code': s['code'],
            'stock_name': s['name'],
            'component_type': ctype,
            'source_platform': '东方财富',
            'source_date': today,
        })
    
    return components


def collect_cls_news(today=None, keywords=None):
    """采集财联社快讯"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    try:
        news = query("SELECT * FROM cls_news WHERE date=? ORDER BY created_at DESC", (today,)) if today else []
    except:
        news = []
    if keywords:
        news = [n for n in news if any(kw in str(n.get('title', '')) + str(n.get('content', '')) for kw in keywords)]
    return news


def collect_heat_data(topic_id, topic_name, today=None):
    """采集热度数据 — 从帖子表统计"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).strftime("%Y-%m-%d")
    day3 = (date.fromisoformat(today) - timedelta(days=3)).strftime("%Y-%m-%d")
    day7 = (date.fromisoformat(today) - timedelta(days=7)).strftime("%Y-%m-%d")
    
    # 今日包含关键词的帖子数
    today_count = query(
        "SELECT COUNT(*) as c FROM posts WHERE date=? AND (title LIKE ? OR content LIKE ?)",
        (today, f'%{topic_name}%', f'%{topic_name}%')
    )[0]['c']
    
    yesterday_count = query(
        "SELECT COUNT(*) as c FROM posts WHERE date=? AND (title LIKE ? OR content LIKE ?)",
        (yesterday, f'%{topic_name}%', f'%{topic_name}%')
    )[0]['c']
    
    day3_avg = 0
    day7_avg = 0
    try:
        day3_count = query(
            "SELECT COUNT(*) as c FROM posts WHERE date>=? AND date<=? AND (title LIKE ? OR content LIKE ?)",
            (day3, today, f'%{topic_name}%', f'%{topic_name}%')
        )[0]['c']
        day3_avg = day3_count / 3
        
        day7_count = query(
            "SELECT COUNT(*) as c FROM posts WHERE date>=? AND date<=? AND (title LIKE ? OR content LIKE ?)",
            (day7, today, f'%{topic_name}%', f'%{topic_name}%')
        )[0]['c']
        day7_avg = day7_count / 7
    except:
        pass
    
    heat_change_1d = ((today_count - yesterday_count) / max(yesterday_count, 1)) * 100 if yesterday_count > 0 else 0
    heat_change_3d = ((today_count - day3_avg) / max(day3_avg, 1)) * 100 if day3_avg > 0 else 0
    heat_change_7d = ((today_count - day7_avg) / max(day7_avg, 1)) * 100 if day7_avg > 0 else 0
    
    return {
        'topic_id': topic_id,
        'stat_date': today,
        'media_report_count': today_count,
        'guba_discussion_count': today_count,
        'xueqiu_discussion_count': 0,
        'baidu_index_value': 0,
        'heat_change_1d': round(heat_change_1d, 1),
        'heat_change_3d': round(heat_change_3d, 1),
        'heat_change_7d': round(heat_change_7d, 1),
    }


def collect_capital_flow(topic_id, topic_name, today=None):
    """采集资金流向 — 从涨停个股资金数据聚合"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    stocks = query(
        "SELECT net_inflow, trade_amt, name FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ?) ORDER BY board_num DESC LIMIT 10",
        (today, f'%{topic_name}%', f'%{topic_name}%')
    )
    
    total_inflow = sum(s.get('net_inflow') or 0 for s in stocks)
    total_amt = sum(s.get('trade_amt') or 0 for s in stocks)
    
    # 龙虎榜上榜数
    lhb_count = query(
        "SELECT COUNT(*) as c FROM zt_stocks WHERE date=? AND is_dragon=1 AND (sector LIKE ? OR reason LIKE ?)",
        (today, f'%{topic_name}%', f'%{topic_name}%')
    )[0]['c']
    
    return {
        'topic_id': topic_id,
        'trade_date': today,
        'board_main_net_inflow': round(total_inflow, 2),
        'leader_main_net_inflow': round(stocks[0].get('net_inflow') or 0, 2) if stocks else 0,
        'center_main_net_inflow': 0,
        'lhb_stock_count': lhb_count,
        'institution_participation': '',
        'hot_money_participation': '',
        'northbound_change_desc': '',
    }


def collect_daily_quotes(topic_id, topic_name, today=None):
    """采集板块每日行情聚合数据"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    stocks = query(
        "SELECT * FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ?) ORDER BY board_num DESC",
        (today, f'%{topic_name}%', f'%{topic_name}%')
    )
    
    limit_up = len(stocks)
    boards = set(s['board_num'] for s in stocks if s.get('board_num'))
    
    # 前排: 板数>=2, 后排: 板数=1
    front = [s for s in stocks if (s.get('board_num') or 0) >= 2]
    back = [s for s in stocks if (s.get('board_num') or 0) == 1]
    
    front_avg = sum(s.get('price') or 0 for s in front) / len(front) / 10 if front else 0
    back_avg = sum(s.get('price') or 0 for s in back) / len(back) / 10 if back else 0
    
    return {
        'topic_id': topic_id,
        'trade_date': today,
        'board_change_pct': None,  # 需要板块指数
        'board_turnover_amount': round(sum(s.get('trade_amt') or 0 for s in stocks), 2),
        'rising_stock_count': limit_up,
        'falling_stock_count': 0,
        'limit_up_count': limit_up,
        'limit_down_count': sum(1 for s in stocks if s.get('reopen_count', 0) > 2),
        'consecutive_board_count': len(boards),
        'front_avg_change_pct': round(front_avg, 2),
        'back_avg_change_pct': round(back_avg, 2),
    }


# ═══════════════════════════════════════════════
# 多平台热度采集 — 写入 platform_heat 表
# ═══════════════════════════════════════════════

def collect_platform_heat(today=None):
    """从4个已有数据源聚合题材热度数据 → 写入 platform_heat 表
    
    - 韭研公社: posts 表 platform='jy' 按关键词计数
    - 雪球: heat_data.xueqiu_discussion_count (有则用)
    - 东方财富: zt_stocks 涨停池数据 (涨停家数=热度)
    - 同花顺: 概念排行排名 (排名=关注度)
    """
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    from backend.models import insert, query, execute
    from backend.services.cleaner import normalize_topic_name
    
    active_topics = collect_active_topics(today)
    # 兜底: 从 zt_stocks 按板块分组取题材列表
    if not active_topics or len(active_topics) < 5:
        sector_rows = query(
            "SELECT sector as name, COUNT(*) as zt_count, MAX(board_num) as max_board FROM zt_stocks WHERE date=? AND sector!='' GROUP BY sector ORDER BY COUNT(*) DESC LIMIT 20",
            (today,)
        )
        if sector_rows:
            active_topics = [{'name': r['name'], 'zt_count': r['zt_count'], 'max_board': r['max_board']} for r in sector_rows]
    
    # 再兜底: 从旧分析表取
    if not active_topics or len(active_topics) < 3:
        rows = query("SELECT topic_name FROM topics ORDER BY total_score DESC LIMIT 15")
        active_topics = [{'name': r['topic_name'], 'zt_count': 0, 'max_board': 0} for r in rows]
    
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).strftime("%Y-%m-%d")
    day3 = (date.fromisoformat(today) - timedelta(days=3)).strftime("%Y-%m-%d")
    day7 = (date.fromisoformat(today) - timedelta(days=7)).strftime("%Y-%m-%d")
    
    results = []
    for t in active_topics[:20]:
        name = normalize_topic_name(t['name'])
        execute("DELETE FROM platform_heat WHERE topic_name=? AND stat_date=?", (name, today))
        
        # ── 韭研公社 ──
        jygs_today = query(
            "SELECT COUNT(*) as c FROM posts WHERE platform='jy' AND date=? AND (title LIKE ? OR content LIKE ?)",
            (today, f'%{name}%', f'%{name}%')
        )[0]['c']
        jygs_yesterday = query(
            "SELECT COUNT(*) as c FROM posts WHERE platform='jy' AND date=? AND (title LIKE ? OR content LIKE ?)",
            (yesterday, f'%{name}%', f'%{name}%')
        )[0]['c']
        day3_c = query(
            "SELECT COUNT(*) as c FROM posts WHERE platform='jy' AND date>=? AND date<=? AND (title LIKE ? OR content LIKE ?)",
            (day3, today, f'%{name}%', f'%{name}%')
        )[0]['c']
        day3_avg = day3_c / 3 if day3_c > 0 else 0
        day7_c = query(
            "SELECT COUNT(*) as c FROM posts WHERE platform='jy' AND date>=? AND date<=? AND (title LIKE ? OR content LIKE ?)",
            (day7, today, f'%{name}%', f'%{name}%')
        )[0]['c']
        day7_avg = day7_c / 7 if day7_c > 0 else 0
        
        insert('platform_heat', {
            'topic_id': 0, 'topic_name': name, 'platform': 'jygs',
            'stat_date': today, 'mention_count': jygs_today,
            'article_count': jygs_today, 'comment_count': 0,
            'like_count': 0, 'favorite_count': 0, 'share_count': 0, 'hot_rank': 0,
            'heat_change_1d': round(((jygs_today - jygs_yesterday) / max(jygs_yesterday, 1)) * 100, 1),
            'heat_change_3d': round(((jygs_today - day3_avg) / max(day3_avg, 1)) * 100, 1) if day3_avg > 0 else 0,
            'heat_change_7d': round(((jygs_today - day7_avg) / max(day7_avg, 1)) * 100, 1) if day7_avg > 0 else 0,
        })
        
        # ── 雪球 ──
        xq = query(
            "SELECT h.xueqiu_discussion_count FROM heat_data h JOIN topics tp ON h.topic_id=tp.id WHERE tp.topic_name=? ORDER BY h.stat_date DESC LIMIT 1",
            (name,)
        )
        xq_count = xq[0]['xueqiu_discussion_count'] if xq else 0
        if xq_count > 0:
            insert('platform_heat', {
                'topic_id': 0, 'topic_name': name, 'platform': 'xueqiu',
                'stat_date': today, 'mention_count': xq_count,
                'article_count': xq_count, 'comment_count': 0,
                'like_count': 0, 'favorite_count': 0, 'share_count': 0, 'hot_rank': 0,
                'heat_change_1d': 0, 'heat_change_3d': 0, 'heat_change_7d': 0,
            })
        
        # ── 东方财富 ──
        em = query(
            "SELECT code, name, board_num FROM zt_stocks WHERE date=? AND (sector LIKE ? OR reason LIKE ?)",
            (today, f'%{name}%', f'%{name}%')
        )
        if em:
            insert('platform_heat', {
                'topic_id': 0, 'topic_name': name, 'platform': 'eastmoney',
                'stat_date': today, 'mention_count': len(em),
                'article_count': len(em),
                'comment_count': sum(max(0, s.get('board_num', 0) or 0) for s in em),
                'like_count': 0, 'favorite_count': 0, 'share_count': 0, 'hot_rank': 0,
                'heat_change_1d': 0, 'heat_change_3d': 0, 'heat_change_7d': 0,
            })
        
        # ── 同花顺 ──
        ths_rank = 0
        for i, at in enumerate(active_topics[:20]):
            if normalize_topic_name(at['name']) == name:
                ths_rank = i + 1
                break
        if ths_rank > 0:
            insert('platform_heat', {
                'topic_id': 0, 'topic_name': name, 'platform': 'ths',
                'stat_date': today, 'mention_count': t.get('zt_count', 0),
                'article_count': t.get('zt_count', 0),
                'comment_count': 0, 'like_count': 0, 'favorite_count': 0, 'share_count': 0,
                'hot_rank': ths_rank,
                'heat_change_1d': 0, 'heat_change_3d': 0, 'heat_change_7d': 0,
            })
        
        results.append({'topic_name': name, 'jygs_count': jygs_today, 'em_zt': len(em) if em else 0, 'ths_rank': ths_rank, 'xq_count': xq_count})
    
    print(f"  ✅ platform_heat: {len(results)} 个题材已更新")
    return results

