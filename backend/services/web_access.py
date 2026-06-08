
"""
web_access 网页数据抓取工具
===========================
封装 web_fetch() 为 Python 可调用的 HTTP 数据采集层
回落策略：agent-browser → requests → 本地DB
"""
import requests
import json
import re
import os
from datetime import date, datetime, timedelta
from typing import Optional

# ── 配置 ──
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

TIMEOUT = 15

def web_fetch(url: str, headers: Optional[dict] = None, timeout: Optional[int] = None) -> str:
    """web_access 核心函数 — 获取URL内容"""
    if headers is None:
        headers = HEADERS
    if timeout is None:
        timeout = TIMEOUT
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.encoding = 'utf-8'
        return r.text
    except Exception as e:
        print(f"  ⚠️ web_fetch 失败 [{url[:50]}]: {e}")
        return ''


# ═══════════════════════════════════════════════
# 1. 东方财富数据源 (API接口，纯HTTP)
# ═══════════════════════════════════════════════

def fetch_eastmoney_zt_pool(date_str: str = None) -> list:
    """东方财富涨停池 — web_fetch 代替 akshare"""
    if not date_str:
        date_str = date.today().strftime('%Y-%m-%d')
    date_compact = date_str.replace('-', '')
    
    url = f"https://push2.eastmoney.com/api/qt/clist/get?cb=&pn=1&pz=200&po=1&np=1&fltt=2&invt=2&fs=m:90+t:2&fields=f12,f14,f3,f62,f184,f66,f15,f168"
    text = web_fetch(url)
    if not text:
        return []
    
    try:
        # 解析 JSONP
        json_str = re.sub(r'^.*?\(|\)\s*$', '', text)
        data = json.loads(json_str)
        items = data.get('data', {}).get('diff', [])
        stocks = []
        for item in items:
            stocks.append({
                'code': str(item.get('f12', '')),
                'name': str(item.get('f14', '')),
                'price': item.get('f3', 0),
                'board_num': item.get('f184', 1),
                'trade_amt': item.get('f62', 0),
                'turnovers': item.get('f66', 0),
                'seal_amount': item.get('f15', 0),
            })
        return stocks
    except Exception as e:
        print(f"  ⚠️ 东方财富涨停池解析失败: {e}")
        return []


def fetch_eastmoney_sectors(date_str: str = None) -> list:
    """东方财富板块行情排行"""
    if not date_str:
        date_str = date.today().strftime('%Y-%m-%d')
    url = "https://push2.eastmoney.com/api/qt/clist/get?cb=&pn=1&pz=80&po=1&np=1&fltt=2&invt=2&fs=m:90+t:3&fields=f12,f14,f3,f62,f104,f105"
    text = web_fetch(url)
    if not text:
        return []
    try:
        json_str = re.sub(r'^.*?\(|\)\s*$', '', text)
        data = json.loads(json_str)
        items = data.get('data', {}).get('diff', [])
        sectors = []
        for item in items[:20]:
            sectors.append({
                'name': str(item.get('f14', '')),
                'change_pct': item.get('f3', 0),
                'amount': item.get('f62', 0),
                'rise_count': item.get('f104', 0),
                'fall_count': item.get('f105', 0),
            })
        return sectors
    except Exception as e:
        print(f"  ⚠️ 东方财富板块解析失败: {e}")
        return []


def fetch_eastmoney_index() -> dict:
    """四大指数 + 成交额"""
    url = "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000688"
    text = web_fetch(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.sina.com.cn",
    })
    indices = {'sh': None, 'sz': None, 'cy': None, 'kc': None, 'volume': ''}
    if not text:
        return indices
    
    total_vol = 0
    for line in text.strip().split('\n'):
        if not line: continue
        parts = line.split(',')
        if len(parts) > 10:
            name = parts[0].split('=')[1].replace('"','') if '=' in parts[0] else ''
            try:
                price = float(parts[3])
                if '上证' in name: indices['sh'] = price
                elif '深证' in name: indices['sz'] = price
                elif '创业' in name: indices['cy'] = price
                elif '科创' in name: indices['kc'] = price
            except: pass
            
            # 成交额
            try:
                raw = parts[9].strip().replace(',', '')
                nums = re.findall(r'[\d.]+', raw)
                if nums:
                    total_vol += float(nums[0]) / 1e8
            except: pass
    
    if total_vol > 0:
        indices['volume'] = f"{total_vol:.0f}亿"
    return indices


# ═══════════════════════════════════════════════
# 2. 腾讯证券数据源
# ═══════════════════════════════════════════════

def fetch_tencent_stocks(codes: list) -> dict:
    """腾讯证券实时行情"""
    code_str = ','.join(codes)
    url = f"http://qt.gtimg.cn/q={code_str}"
    text = web_fetch(url, headers={"User-Agent": "Mozilla/5.0"})
    result = {}
    if not text:
        return result
    for line in text.strip().split('\n'):
        if not line: continue
        try:
            parts = line.split('~')
            if len(parts) > 30:
                name = parts[1]
                code = parts[2]
                price = float(parts[3]) if parts[3] else 0
                change_pct = float(parts[32]) if parts[32] else 0
                result[code] = {'name': name, 'price': price, 'change_pct': change_pct}
        except: pass
    return result


# ═══════════════════════════════════════════════
# 3. 格式化辅助
# ═══════════════════════════════════════════════

def fmt_money(v):
    """格式化金额：亿"""
    if not v: return 0
    try: return round(float(v) / 100000000, 2) if float(v) > 1000000 else round(float(v), 2)
    except: return 0


if __name__ == '__main__':
    print("=== web_access 测试 ===")
    
    idx = fetch_eastmoney_index()
    print(f"指数: sh={idx['sh']} sz={idx['sz']} cy={idx['cy']} kc={idx['kc']} 成交额={idx['volume']}")
    
    sectors = fetch_eastmoney_sectors()
    print(f"板块: {len(sectors)}个")
    for s in sectors[:3]:
        print(f"  {s['name']}: {s['change_pct']}%")
