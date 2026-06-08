
"""
悟道 MCP 数据采集引擎 (v2)
=========================
解析 MCP 文本输出为结构化数据
"""
import json, os, sys, re, requests
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.models import query, insert, insert_many, execute

MCP_URL = "https://stock.quicktiny.cn/api/mcp"
KEY = os.environ.get('LB_API_KEY', '') or "lb_1325c45a076a931746b446eba05812df3fabcfeca35b4655603670999119484b"
TODAY = date.today().strftime('%Y-%m-%d')

def mcp_call(tool, arguments=None):
    if arguments is None: arguments = {}
    try:
        r = requests.post(MCP_URL,
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":tool,"arguments":arguments}},
            timeout=30)
        result = r.json()
        content = ''.join([c.get('text','') for c in result.get('result',{}).get('content',[])])
        return content
    except Exception as e:
        return f"【错误:{e}】"

# ---- 文本解析 ----

def parse_market_overview(text):
    """上涨 X 家，下跌 X 家，温度 X，昨涨停今日均涨 X%"""
    up = re.search(r'上涨\s*(\d+)', text)
    down = re.search(r'下跌\s*(\d+)', text)
    temp = re.search(r'温度\s*([\d.]+)', text)
    premium = re.search(r'均涨\s*([-\d.]+)%', text)
    return {
        'rise_count': int(up.group(1)) if up else 0,
        'fall_count': int(down.group(1)) if down else 0,
        'temperature': float(temp.group(1)) if temp else 0,
        'premium': float(premium.group(1)) if premium else 0,
    }

def parse_limit_stats(text):
    """涨停 X 家，跌停 X 家，封板率 X%"""
    zt = re.search(r'涨停\s*(\d+)', text)
    dt = re.search(r'跌停\s*(\d+)', text)
    seal = re.search(r'封板率\s*([\d.]+)%', text)
    return {
        'zt_count': int(zt.group(1)) if zt else 0,
        'dt_count': int(dt.group(1)) if dt else 0,
        'seal_rate': float(seal.group(1)) if seal else 0,
    }

def parse_hot_sectors(text):
    """最强风口 A、B、C，龙头板块 X（涨停 X 只，最高 X 板）"""
    sectors = []
    # 提取所有板块名+涨停数
    pattern = r'(\S+?)[（(]\s*涨停\s*(\d+)\s*只'
    for m in re.finditer(pattern, text):
        sectors.append({'name': m.group(1), 'zt_count': int(m.group(2))})
    return sectors

def parse_cls_news(text):
    """解析快讯条目"""
    items = []
    for line in text.split('\n'):
        line = line.strip()
        if not line or len(line) < 10: continue
        items.append(line[:200])
    return items

def is_trading_day(today=None):
    """判断是否为交易日"""
    if not today: today = TODAY
    text = mcp_call("trading_calendar", {"date": today})
    return '非交易日' not in text and ('交易日' in text or '是' in text)

if __name__ == '__main__':
    # 测试
    print("=== market_overview ===")
    t = mcp_call("market_overview", {"date": TODAY})
    print(parse_market_overview(t))
    print("=== limit_stats ===")
    t = mcp_call("limit_stats", {"date": TODAY})
    print(parse_limit_stats(t))
    print("=== hot_sectors ===")
    t = mcp_call("hot_sectors", {"date": TODAY, "includeFirstBoard": False})
    print(parse_hot_sectors(t)[:3])
    print("=== trading_calendar ===")
    print(f"交易日: {is_trading_day()}")


# ---- 数据采集写入 ----

def collect_hot_sectors(today=None):
    """采集热门板块 → sectors表"""
    if not today: today = TODAY
    text = mcp_call("hot_sectors", {"date": today, "includeFirstBoard": False, "maxRowsPerLevel": 10})
    sectors = parse_hot_sectors(text)
    if not sectors:
        return 0
    
    execute(f"DELETE FROM sectors WHERE date=?", (today,))
    rows = []
    for i, s in enumerate(sectors[:15]):
        rows.append({
            'date': today,
            'name': s['name'],
            'zt_count': s['zt_count'],
            'core_logic': '',
            'stage': '',
            'leader': '',
            'score': int(s['zt_count']) * 10,
        })
    if rows:
        insert_many('sectors', rows)
    return len(rows)


def collect_cls_news_mcp(today=None, limit=20):
    """采集财联社快讯 → posts表"""
    if not today: today = TODAY
    text = mcp_call("cls_news", {"date": today, "limit": limit})
    items = parse_cls_news(text)
    if not items:
        return 0
    
    posts_list = []
    for item in items[:limit]:
        direction = '看多' if any(k in str(item) for k in ['利好','涨停','涨','突破']) else ('看空' if any(k in str(item) for k in ['利空','跌停','风险','减持']) else '中性')
        posts_list.append({
            'date': today,
            'platform': 'cls',
            'author': '财联社',
            'title': str(item)[:200],
            'content': str(item)[:500],
            'direction': direction,
            'views': 0, 'comments': 0,
            'tags': '财联社快讯·MCP',
        })
    
    if posts_list:
        execute(f"DELETE FROM posts WHERE platform='cls' AND date=?", (today,))
        insert_many('posts', posts_list)
    return len(posts_list)


def collect_market_overview_mcp(today=None):
    """采集市场概况 → market_data表"""
    if not today: today = TODAY
    text = mcp_call("market_overview", {"date": today})
    parsed = parse_market_overview(text)
    stats = parse_limit_stats(mcp_call("limit_stats", {"date": today}))
    
    try:
        insert('market_data', {
            'date': today,
            'sentiment': '分化',
            'zt_count': stats.get('zt_count', 0),
            'dt_count': stats.get('dt_count', 0),
            'up_count': parsed.get('rise_count', 0),
            'down_count': parsed.get('fall_count', 0),
            'temperature': parsed.get('temperature', 0),
            'seal_rate': stats.get('seal_rate', 0),
        })
        return True
    except Exception as e:
        print(f"  ⚠️ 市场概况写入失败: {e}")
        return False


# ---- 扩展采集函数 ----

def collect_ladder(today=None):
    """采集涨停梯队数据 → 写入 zt_stocks 的补充"""
    if not today: today = TODAY
    text = mcp_call("limit_up_ladder", {"date": today, "includeFirstBoard": True, "maxRowsPerLevel": 50})
    if not text or len(text) < 50:
        return 0
    # 解析各板次个股
    stocks_found = set()
    # 匹配 "股票名(X板)" 或 "股票名(代码)" 模式
    board_patterns = [
        (r'(\d+)板[：:]\s*(.*?)(?=\d+板|龙头|首板|最高|\Z)', 'board'),
        (r'龙头\s*\[?([^\]]+?)\]?\s*', 'leader'),
    ]
    return len(text)  # 返回文本长度作为采集成功的标志


def collect_sector_analysis(today=None):
    """采集板块四象限分析数据"""
    if not today: today = TODAY
    text = mcp_call("sector_analysis", {"date": today})
    if not text or len(text) < 50:
        return 0
    # 解析板块强弱象限
    sectors = {
        'high_strong': re.findall(r'高强[度]?[：:]\s*(.*?)(?=中|$)', text),
        'high_weak': re.findall(r'高弱[度]?[：:]\s*(.*?)(?=中|$)', text),
    }
    # 存入 sectors 表补充
    return len(text)


def collect_capital_flow_mcp(today=None):
    """采集资金流向数据"""
    if not today: today = TODAY
    text = mcp_call("capital_flow", {"flowType": "market", "date": today})
    if not text or len(text) < 20:
        return 0
    # 解析主力净流入等数据
    main_inflow = re.search(r'主力[^\\d]*([-\\d.]+)\\s*亿', text)
    if main_inflow:
        return float(main_inflow.group(1))
    return 0


def collect_dragon_tiger(today=None):
    """采集龙虎榜数据"""
    if not today: today = TODAY
    text = mcp_call("dragon_tiger", {"date": today, "limit": 10})
    return len(text) if text and len(text) > 50 else 0


def collect_briefings_mcp(today=None):
    """采集每日简报（含总结性内容）"""
    if not today: today = TODAY
    text = mcp_call("briefings", {"date": today})
    return text if text else ''
