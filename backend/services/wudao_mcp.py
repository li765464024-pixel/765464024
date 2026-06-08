"""
悟道 MCP 数据采集引擎
通过 MCP 协议调用悟道 52 个工具，为所有 tab 提供数据
"""
import json, os, sys, requests
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

MCP_URL = "https://stock.quicktiny.cn/api/mcp"
KEY = os.environ.get('LB_API_KEY', '') or "lb_1325c45a076a931746b446eba05812df3fabcfeca35b4655603670999119484b"

def mcp_call(tool, arguments=None):
    """调用 MCP 工具"""
    if arguments is None:
        arguments = {}
    try:
        r = requests.post(MCP_URL,
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":tool,"arguments":arguments}},
            timeout=30)
        result = r.json()
        content = result.get('result', {}).get('content', [])
        text = ''.join([c.get('text','') for c in content])
        return text
    except Exception as e:
        return f"【{tool}调用失败:{e}】"

def collect_all(today="2026-06-05"):
    """采集所有数据"""
    data = {}
    
    # 1. 行情组
    data['market_overview'] = mcp_call("market_overview", {"date": today})
    data['stock_rank'] = mcp_call("stock_rank", {"limit": 10})
    
    # 2. 涨停组
    data['limit_stats'] = mcp_call("limit_stats", {"date": today})
    data['limit_up_ladder'] = mcp_call("limit_up_ladder", {"date": today, "includeReasonInfo": True})
    data['board_break_analysis'] = mcp_call("board_break_analysis", {"tradeDate": today})
    data['hot_sectors'] = mcp_call("hot_sectors", {"date": today})
    data['broken_limit_up'] = mcp_call("broken_limit_up", {"date": today})
    data['limit_down'] = mcp_call("limit_down", {"date": today})
    data['limit_up_filter'] = mcp_call("limit_up_filter", {"date": today, "sortBy":"amount","sortOrder":"desc","limit":10})
    
    # 3. 资金组
    data['capital_flow'] = mcp_call("capital_flow", {"flowType":"market", "date": today})
    
    # 4. 情报组
    data['cls_news'] = mcp_call("cls_news", {"date": today, "limit": 10})
    
    # 5. 竞价组
    data['auction_weak_to_strong'] = mcp_call("auction_weak_to_strong", {"tradeDate": today, "origin": "all", "limit": 10})
    
    return data

if __name__ == '__main__':
    data = collect_all()
    for k, v in data.items():
        print(f"\n{'='*40}")
        print(f"【{k}】")
        print(v[:500])
