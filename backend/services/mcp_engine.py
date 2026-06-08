
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
