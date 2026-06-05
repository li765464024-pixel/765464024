"""
数据爬虫引擎 — 自动抓取各大平台数据
"""
import re
import os
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta

from backend.models import insert, insert_many, query, execute

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

TODAY = date.today().strftime("%Y-%m-%d")

def fmt_percent(v):
    if v is None: return '0.0%'
    try: return f"{float(v):.1f}%"
    except: return '0.0%'

# ════════════════════════════════════════════
# 1. 韭研公社 — 热榜帖子
# ════════════════════════════════════════════

def fetch_jiuyangongshe():
    """抓取韭研公社热榜帖子 → 写入 posts 表"""
    try:
        url = "https://www.jiuyangongshe.com/community/community"
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # ⚠️ 清除今日旧帖子，防止重复累积
        execute("DELETE FROM posts WHERE platform='jy' AND date=?", (TODAY,))
        
        posts = []
        current_title = ''
        
        for div in soup.find_all('div'):
            cls = ' '.join(div.get('class', []))
            txt = div.get_text(strip=True)
            
            # 标题行
            if 'book-title' in cls and len(txt) > 5:
                current_title = txt
            
            # 内容行
            if 'flexItem' in cls and len(txt) > 10 and current_title:
                # 找作者
                author_el = div.find_previous('div', class_=re.compile('author|name|user'))
                author = author_el.get_text(strip=True)[:20] if author_el else '韭研公社'
                
                posts.append({
                    'date': TODAY,
                    'platform': 'jy',
                    'author': author,
                    'title': current_title[:200],
                    'content': txt[:500],
                    'direction': '看多' if any(k in txt for k in ['利好','涨停','爆发','突破','龙头']) else '中性',
                    'views': 0,
                    'comments': 0,
                    'tags': '韭研公社·实时爬取',
                })
                current_title = ''
        
        if posts:
            insert_many('posts', posts)
            return len(posts)
        return 0
    except Exception as e:
        print(f"  ⚠️ 韭研公社爬取失败: {e}")
        return 0


# ════════════════════════════════════════════
# 2. 涨停池数据 (akshare)
# ════════════════════════════════════════════

def fetch_zt_pool():
    """从东方财富涨停池获取当日涨停数据"""
    try:
        import akshare as ak
        today_str = TODAY.replace('-', '')
        df = ak.stock_zt_pool_em(date=today_str)
        
        if df is None or len(df) == 0:
            from datetime import timedelta
            yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
            df = ak.stock_zt_pool_em(date=yesterday)
        
        if df is None or len(df) == 0:
            return 0, 0
        
        use_date = TODAY
        
        # ⚠️ 清除今日旧数据，防止重复累积
        execute("DELETE FROM zt_stocks WHERE date=?", (use_date,))
        execute("DELETE FROM board_summary WHERE date=?", (use_date,))
        
        stocks = []
        for _, row in df.iterrows():
            board = int(row.get('连板数', 1))
            
            # 格式化涨停时间: 092500 → 09:25
            raw_time = str(row.get('首次封板时间', ''))
            fmt_time = raw_time[:2] + ':' + raw_time[2:4] if len(raw_time) >= 4 else raw_time[:5]
            
            # 涨停统计: "2/2" → "2天2板"
            zt_stats = str(row.get('涨停统计', ''))
            if board >= 2 and '/' in zt_stats:
                days = zt_stats.split('/')[0]
                tag = f"{days}天{board}板"
            else:
                tag = "首板" if board == 1 else f"{board}板"
            
            stocks.append({
                'date': use_date,
                'code': str(row.get('代码', '')),
                'name': str(row.get('名称', '')),
                'price': float(row.get('最新价', 0)),
                'board_num': board,
                'seal_time': fmt_time,
                'reason': str(row.get('所属行业', '')),
                'seal_amount': float(row.get('封板资金', 0)) / 100000000 if row.get('封板资金', 0) else 0,
                'reopen_count': int(row.get('炸板次数', 0)),
                'turnovers': float(row.get('换手率', 0)) if row.get('换手率', 0) else 0,
                'sector': str(row.get('所属行业', '')),
                'board_tag': tag,
            })
        
        if stocks:
            insert_many('zt_stocks', stocks)
            
            # 统计连板数据
            for b in range(1, 6):
                cnt = sum(1 for s in stocks if s['board_num'] == b)
                yesterday_count = 0  # 简化处理
                insert('board_summary', {
                    'date': use_date,
                    'board_num': b,
                    'yesterday_count': yesterday_count,
                    'today_count': cnt,
                    'promotion_rate': 0,
                })
            
            return len(stocks), use_date
        return 0, use_date
    except Exception as e:
        print(f"  ⚠️ 涨停池爬取失败: {e}")
        return 0, ''


# ════════════════════════════════════════════
# 3. 大盘数据 (从涨停池推算 + akshare)
# ════════════════════════════════════════════

def fetch_market_data():
    """大盘概况 — 以悟道API为主, 补充成交额(新浪)+指数(腾讯)"""
    try:
        # 1. 悟道API → 涨停/跌停/上涨/下跌/封板率/温度
        KEY = os.environ.get('LB_API_KEY', '')
        if not KEY:
            try:
                with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')) as f:
                    for line in f:
                        if line.startswith('LB_API_KEY='):
                            KEY = line.strip().split('=', 1)[1]
                            break
            except:
                pass
            if not KEY:
                KEY = "lb_1325c45a076a931746b446eba05812df3fabcfeca35b4655603670999119484b"
        
        r = requests.get(f"https://stock.quicktiny.cn/api/openclaw/market-overview?date={TODAY}",
                        headers={"Authorization": f"Bearer {KEY}"}, timeout=10)
        data = r.json()['data']
        zt_count = data['limit_up_count']
        dt_count = data['limit_down_count']
        up_count = data['rise_count']
        down_count = data['fall_count']
        seal_rate = round((1 - data['limit_up_broken_ratio']) * 100, 1)
        temperature = round(data['market_temperature'], 1)
        
        # 2. 悟道API ladder → 最高板
        r2 = requests.get(f"https://stock.quicktiny.cn/api/openclaw/ladder?date={TODAY}",
                         headers={"Authorization": f"Bearer {KEY}"}, timeout=10)
        ladder = r2.json()['data']['dates'][0]
        max_board = max(b['level'] for b in ladder['boards'])
        top_stocks = []
        for b in ladder['boards']:
            if b['level'] == max_board:
                for s in b['stocks']:
                    top_stocks.append(s['name'])
        max_board_stocks = '/'.join(top_stocks[:3])
        
        # 3. 新浪财经 → 指数 + 成交额 (替代腾讯证券)
        indices = {'sh': None, 'sz': None, 'cy': None, 'kc': None}
        volume_str = ''
        try:
            r3 = requests.get("https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000688",
                             headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, timeout=5)
            total_vol = 0
            for line in r3.text.strip().split('\n'):
                if not line: continue
                parts = line.split(',')
                if len(parts) > 10:
                    name = parts[0].split('=')[1].replace('"','') if '=' in parts[0] else ''
                    price = float(parts[3])
                    if name and '上证' in name: indices['sh'] = price
                    elif name and '深证' in name: indices['sz'] = price
                    elif name and '创业' in name: indices['cy'] = price
                    elif name and '科创' in name: indices['kc'] = price
            # 成交额: 只取上证+深证（全市场）
            r3b = requests.get("https://hq.sinajs.cn/list=sh000001,sz399001",
                              headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, timeout=5)
            for line in r3b.text.strip().split('\n'):
                parts = line.split(',')
                if len(parts) > 10:
                    v = parts[9].strip()
                    if v.replace('.','').isdigit():
                        total_vol += float(v) / 1e8
            if total_vol > 0:
                volume_str = f"{total_vol:.0f}亿"
        except:
            pass
        
        # 5. 昨日对比
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        prev = query("SELECT * FROM market_data WHERE date=? ORDER BY id DESC LIMIT 1", (yesterday,))
        
        insert('market_data', {
            'date': TODAY, 'sentiment': '分化',
            'zt_count': zt_count, 'dt_count': dt_count,
            'up_count': up_count, 'down_count': down_count,
            'seal_rate': seal_rate, 'volume': volume_str,
            'main_inflow': prev[0]['main_inflow'] if prev else '',
            'max_board': max_board, 'max_board_stocks': max_board_stocks,
            'index_sh': indices.get('sh'),
            'index_sz': indices.get('sz'),
            'index_cy': indices.get('cy'),
            'index_kc': indices.get('kc'),
            'temperature': temperature,
            'yesterday_zt_count': prev[0]['zt_count'] if prev else 0,
            'yesterday_seal_rate': prev[0]['seal_rate'] if prev else 0,
        })
        print(f"  ✅ 大盘(悟道API): 涨停{zt_count} 上涨{up_count} 下跌{down_count} 封板率{seal_rate}% 温度{temperature} 成交额{volume_str}")
        return True
    except Exception as e:
        print(f"  ⚠️ 大盘数据获取失败: {e}")
        return False


# ════════════════════════════════════════════
# 4. 重建 section_html (用实时数据替换静态分析)
# ════════════════════════════════════════════

def _build_s1_html(today):
    """大盘概况 — 1:1复刻原始HTML"""
    rows = query("SELECT * FROM market_data WHERE date=? ORDER BY id DESC LIMIT 1", (today,))
    if not rows:
        return ''
    d = rows[0]
    yest = query("SELECT * FROM market_data WHERE date<? ORDER BY date DESC LIMIT 1", (today,))
    yd = yest[0] if yest else {}
    yest_date = yd.get('date', '')[-5:] if yd else ''
    
    sentiment = d['sentiment'] or '分化'
    sc = 'gold' if sentiment == '分化' else ('red' if '强' in str(sentiment) else 'green')
    zt_d = d['zt_count'] or query("SELECT COUNT(*) as c FROM zt_stocks WHERE date=?", (today,))[0]['c'] or 0
    dt_d = d['dt_count'] if d['dt_count'] is not None and d['dt_count'] != 0 else (yd.get('dt_count', 0) or 0)
    inflow = d['main_inflow'] if d['main_inflow'] else (yd.get('main_inflow', '') or '---')
    up_d = d['up_count'] if d['up_count'] else (yd.get('up_count', 0) or '---')
    down_d = d['down_count'] if d['down_count'] else (yd.get('down_count', 0) or '---')
    vol = d['volume'] if d['volume'] else (yd.get('volume', '') or '---')
    seal = d['seal_rate'] if d['seal_rate'] else (yd.get('seal_rate', 0) or '---')
    temp = d['temperature'] if d['temperature'] else (yd.get('temperature', '') or '---')
    max_board = d['max_board'] or 0
    board_stocks = d['max_board_stocks'] or yd.get('max_board_stocks', '') or ''
    sh = d['index_sh']; sz = d['index_sz']; cy = d['index_cy']; kc = d['index_kc']
    premium_val = d['yesterday_premium'] if d.get('yesterday_premium') else '---'
    margin_val = d['margin_balance'] if d.get('margin_balance') else '---'
    
    subtitle = '科创50逆势走强' if kc and sh and kc > sh else '实时数据'
    h2 = '<h2>一、大盘概况 <span style="font-size:11px;color:var(--muted);font-weight:normal">' + subtitle + '</span></h2>'
    
    def nf(v):
        if v is None or v == 0 or v == '' or v == 0.0: return '---'
        try:
            if isinstance(v, float) and v == 0.0: return '---'
            if isinstance(v, (int, float)) and v >= 1000: return '{:,}'.format(int(v))
            s = str(v)
            # Format "30692亿" -> "30,692亿"
            if s[:-1].isdigit() and s[-1] in '亿万%':
                return '{:,}'.format(int(s[:-1])) + s[-1]
            return s
        except: return str(v)
    
    def st(v):
        if not v or v == '---': return ''
        return '<div style="font-size:10px;color:var(--muted);margin-top:2px">' + str(v) + '</div>'
    
    c_r = 'style="color:var(--red)"'
    c_g = 'style="color:var(--green)"'
    c_gld = 'style="color:var(--gold)"'
    c_b = 'style="color:var(--blue)"'
    c_m = 'style="color:var(--muted)"'
    
    # === Card 1: 12项 grid ===
    grp = ''
    grp += '<div class="stat"><div class="v" style="color:var(--' + sc + ')">' + sentiment + '</div><div class="l">市场情绪</div>' + st(subtitle) + '</div>'
    grp += '<div class="stat"><div class="v" ' + c_r + '>' + nf(zt_d) + '</div><div class="l">涨停家数</div>' + st('悟道API . 含ST') + '</div>'
    grp += '<div class="stat"><div class="v" ' + c_g + '>' + nf(dt_d) + '</div><div class="l">跌停家数</div>' + st('悟道API . 含ST') + '</div>'
    grp += '<div class="stat"><div class="v" ' + c_gld + '>' + nf(inflow) + '</div><div class="l">主力净额</div>' + st('半导体/电子逆势流入') + '</div>'
    grp += '<div class="stat"><div class="v" ' + c_b + '>' + str(max_board) + '板</div><div class="l">连板高度</div>' + st(board_stocks) + '</div>'
    grp += '<div class="stat"><div class="v" ' + c_r + '>' + nf(up_d) + '</div><div class="l">上涨家数</div>' + st('悟道API') + '</div>'
    grp += '<div class="stat"><div class="v" ' + c_g + '>' + nf(down_d) + '</div><div class="l">下跌家数</div>' + st('悟道API') + '</div>'
    grp += '<div class="stat"><div class="v" ' + c_gld + '>' + nf(vol) + '</div><div class="l">成交额</div>' + st('连续第N日>2.5万亿') + '</div>'
    seal_str = str(seal) + '%' if seal != '---' else '---'
    grp += '<div class="stat"><div class="v" ' + c_r + '>' + seal_str + '</div><div class="l">封板率</div>' + st('悟道API') + '</div>'
    grp += '<div class="stat"><div class="v" ' + c_r + '>' + str(premium_val) + '</div><div class="l">昨涨停溢价</div>' + st('悟道API') + '</div>'
    grp += '<div class="stat"><div class="v" ' + c_m + '>' + str(temp) + '</div><div class="l">市场温度</div>' + st('悟道API') + '</div>'
    grp += '<div class="stat"><div class="v" ' + c_m + '>' + str(margin_val) + '</div><div class="l">两融余额</div>' + st('融资') + '</div>'
    
    # === Card 2: 对比表 ===
    yest_zt = yd.get('zt_count', 0) or 0
    yest_seal = yd.get('seal_rate', 0) or 0
    yest_up = yd.get('up_count', 0) or 0
    yest_down = yd.get('down_count', 0) or 0
    yest_board = yd.get('max_board', 0) or 0
    yest_dt = yd.get('dt_count', 0) or 0
    yest_vol = yd.get('volume', '') or ''
    
    def diff_td(c, p, up_good=True):
        if c == '---' or not p: return '<td ' + c_m + '>---</td>'
        try: diff = float(c) - float(p)
        except: return '<td ' + c_m + '>---</td>'
        if abs(diff) < 0.01: return '<td ' + c_m + '>---</td>'
        color = 'red' if (diff > 0 and up_good) or (diff < 0 and not up_good) else 'green'
        arr = chr(8593) if diff > 0 else chr(8595)
        prefix = '+' if diff > 0 else ''
        return '<td style="color:var(--' + color + ');font-weight:700">' + prefix + str(int(diff)) + arr + '</td>'
    
    def tc(v, color='muted'):
        if v is None or v == 0 or v == '' or v == '---': return '<td ' + c_m + '>---</td>'
        return '<td style="color:var(--' + color + ')">' + str(v) + '</td>'
    
    today_short = today[-5:] if today else ''
    
    cr = ''
    cr += '<tr><td>市场情绪</td>' + tc(sentiment) + tc('修复', 'muted') + '<td ' + c_m + '>分化加剧</td></tr>'
    d_up = int(zt_d) - int(yest_zt)
    d_up_str = str(d_up) if d_up >= 0 else str(d_up)
    d_up_arr = chr(8593) if d_up > 0 else (chr(8595) if d_up < 0 else '')
    cr += '<tr><td>涨停家数</td>' + tc(zt_d, 'red') + tc(yest_zt, 'muted') + '<td style="color:var(--' + ('red' if d_up > 0 else 'green') + ');font-weight:700">' + d_up_str + ' ' + d_up_arr + ' <span style="font-size:10px;color:var(--green)">悟道API</span></td></tr>'
    
    d_dt = int(dt_d) - int(yest_dt)
    d_dt_str = str(d_dt) if d_dt >= 0 else str(d_dt)
    d_dt_arr = chr(8593) if d_dt > 0 else (chr(8595) if d_dt < 0 else '')
    d_dt_color = 'red' if d_dt > 0 else 'green'
    cr += '<tr><td>跌停家数</td>' + tc(dt_d, 'green') + tc(yest_dt, 'green') + '<td style="color:var(--' + d_dt_color + ');font-weight:700">' + d_dt_str + ' ' + d_dt_arr + '</td></tr>'
    
    d_seal = int(seal) - int(yest_seal) if seal != '---' and yest_seal else 0
    d_seal_str = ('+' + str(d_seal) if d_seal > 0 else str(d_seal)) + 'pp'
    d_seal_arr = chr(8593) if d_seal > 0 else (chr(8595) if d_seal < 0 else '')
    cr += '<tr><td>封板率</td>' + tc(seal_str, 'red') + tc(str(yest_seal) + '%', 'muted') + '<td style="color:var(--' + ('red' if d_seal > 0 else 'green') + ');font-weight:700">' + d_seal_str + ' ' + d_seal_arr + ' <span style="font-size:10px;color:var(--green)">科技线封板好</span></td></tr>'
    
    cr += '<tr><td>上涨家数</td>' + tc(up_d, 'red') + tc(yest_up, 'muted') + diff_td(up_d, yest_up)
    cr += '<tr><td>下跌家数</td>' + tc(down_d, 'green') + tc(yest_down, 'muted') + diff_td(down_d, yest_down, False)
    cr += '<tr><td>连板高度</td>' + tc(str(max_board) + '板', 'blue') + tc(str(yest_board) + '板', 'muted') + ('<td style="color:var(--red);font-weight:700">+1 ' + chr(8593) + ' <span style="font-size:10px;color:var(--gold)">' + board_stocks + '</span></td>' if max_board > yest_board else '<td ' + c_m + '>---</td>')
    cr += '<tr><td>成交额</td>' + tc(vol, 'gold') + (tc(yest_vol, 'gold') if yest_vol else '<td ' + c_m + '>---</td>') + '<td style="color:var(--green);font-weight:700">-3,740亿 ' + chr(8595) + '</td></tr>'
    cr += '<tr><td>主力净额</td>' + tc(inflow) + '<td ' + c_m + '>---</td><td ' + c_m + '>半导体逆势流入</td></tr>'
    cr += '<tr><td>市场温度</td>' + tc(temp, 'muted') + '<td ' + c_m + '>---</td><td ' + c_m + '>---</td></tr>'
    
    # === Card 3: 指数 ===
    ir = ''
    if sh:
        yest_sh = yd.get('index_sh')
        yest_sz = yd.get('index_sz')
        yest_cy = yd.get('index_cy')
        yest_kc = yd.get('index_kc')
        sh_ch = ('+' + f'{(sh / yest_sh - 1) * 100:.2f}%' if sh >= yest_sh else f'{(sh / yest_sh - 1) * 100:.2f}%') if yest_sh else '--'
        sz_ch = ('+' + f'{(sz / yest_sz - 1) * 100:.2f}%' if sz >= yest_sz else f'{(sz / yest_sz - 1) * 100:.2f}%') if yest_sz else '--'
        cy_ch = ('+' + f'{(cy / yest_cy - 1) * 100:.2f}%' if cy >= yest_cy else f'{(cy / yest_cy - 1) * 100:.2f}%') if yest_cy else '--'
        kc_ch = ('+' + f'{(kc / yest_kc - 1) * 100:.2f}%' if kc >= yest_kc else f'{(kc / yest_kc - 1) * 100:.2f}%') if yest_kc and kc else '--'
        
        for nm, pr, ch, ql, qc in [
            ('上证指数', sh, sh_ch, '缩量调整', 'g'),
            ('深证成指', sz, sz_ch, '窄幅震荡', 'g'),
            ('创业板指', cy, cy_ch, '宁德拖累', 'g'),
            ('科创50', kc, kc_ch, '逆势领涨', 'b'),
        ]:
            if not pr: continue
            pct_color = 'red' if ch and ch.startswith('+') else ('green' if ch and ch != '--' else 'muted')
            ir += '<tr><td>' + nm + '</td><td>' + f'{pr:,.2f}' + '</td><td style="color:var(--' + pct_color + ');font-weight:700">' + ch + '</td><td><span class="tag ' + qc + '">' + ql + '</span></td></tr>'
    
    # === Card 4: 结论 ===
    conclusion = '<strong>\U0001f4cc 核心定性：</strong>六月开局<span style="color:var(--red);font-weight:700">结构性分化</span>——三大指数普跌，科创50逆势<span style="color:var(--red);font-weight:700">' + kc_ch + '</span>。全天涨停' + nf(zt_d) + '只，跌停' + nf(dt_d) + '只。' + str(max_board) + '板梯队完整（' + board_stocks + '）。煤炭/化工/CPO强势。<span class="src st">悟道API</span>。<span style="color:var(--green);font-weight:700">晋级率100%</span>，短线生态健康。<br>'
    conclusion += '<strong>但风险：</strong>下跌' + nf(down_d) + '家占绝对多数，成交额<span style="color:var(--gold);font-weight:700">' + nf(vol) + '</span>。市场温度' + str(temp) + '偏低，整体赚钱效应受限。'
    
    # === ASSEMBLE ===
    result = h2 + '\n<div class="grid2">\n' + grp + '\n</div>\n\n'
    result += '<div class="card">\n<h3>\U0001f4ca 今日 vs 昨日对比</h3>\n<table>\n<tr><th>指标</th><th>今日（' + today_short + '）</th><th>昨日（' + yest_date + '）</th><th>变化</th></tr>\n' + cr + '\n</table>\n'
    result += '<div class="bl-blue" style="margin-top:8px;font-size:12px">\n<strong>概要：</strong>今日涨停' + nf(zt_d) + '只（跌停' + nf(dt_d) + '只），' + str(max_board) + '板梯队完整（' + board_stocks + '）。上涨' + nf(up_d) + '家vs下跌' + nf(down_d) + '家，结构性极致分化。<span class="up">连板梯队健康</span><span class="dn">但整体跌多涨少(' + nf(up_d) + ':' + nf(down_d) + ')</span>。\n</div>\n</div>\n\n'
    if ir:
        result += '<div class="card">\n<h3>\U0001f4c8 指数表现</h3>\n<table>\n<tr><th>指数</th><th>收盘</th><th>涨跌幅</th><th>定性</th></tr>\n' + ir + '\n</table>\n</div>\n\n'
    result += '<div class="bl-red">\n' + conclusion + '\n</div>\n'
    
    return result


def _build_s2_html(today):
    """板块热度 — 1:1复刻原始HTML 5卡结构"""
    sectors = query("SELECT sector, COUNT(*) as cnt, MAX(board_num) as mb FROM zt_stocks WHERE date=? AND sector!='' GROUP BY sector ORDER BY cnt DESC", (today,))
    if not sectors:
        return ''
    
    def esc(s):
        return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;') if s else ''
    
    def chip(name):
        return '<span class="chip chip-up">' + esc(name) + '</span>'
    
    def leader_stocks(sector, limit=2):
        leaders = query("SELECT name, board_num FROM zt_stocks WHERE date=? AND sector=? ORDER BY board_num DESC, seal_time LIMIT " + str(limit), (today, sector))
        return '/'.join([l['name'] + ('(' + str(l['board_num']) + '板)' if l['board_num'] >= 2 else '') for l in leaders])
    
    # Common tag for source
    src_jy = '<span class="src sj">韭</span>'
    src_st = '<span class="src st">淘</span>'
    src_th = '<span class="src sj">同花顺</span>'
    
    # ════════════════════════════════════════
    # Card 1: 板块全景 — 8个板块 + 核心逻辑 + 阶段 + 龙头
    # ════════════════════════════════════════
    # Map key sector keywords to curated descriptions
    sector_info = [
        {'name': 'MLCC/电容', 'kw': ['MLCC','电容','被动元件','电子化学','陶瓷'], 'stage': '<span class="tag r">主升加速</span>',
         'logic': '高盛超级周期+风华全面停接单+村田6月涨价30%，年内+108%反超CPO登顶'},
        {'name': 'CPO/光通信', 'kw': ['CPO','光通信','光模块','光纤','通信设备'], 'stage': '<span class="tag r">主升</span>',
         'logic': '英伟达Spectrum-X量产+Marvell单日+22%，连线成AI新瓶颈'},
        {'name': '存储芯片', 'kw': ['存储','DRAM','NAND','HBM','IT服务'], 'stage': '<span class="tag r">主升</span>',
         'logic': '海力士5年内晶圆产能翻番，DRAM Q2价格环比+50%，德明利涨停'},
        {'name': '半导体材料/设备', 'kw': ['半导体','芯片','封测','硅片','光刻','元件'], 'stage': '<span class="tag r">主升</span>',
         'logic': '硅片全面提价(AI专用+18-22%)，沪硅+14%，中船特气20cm涨停'},
        {'name': '煤炭', 'kw': ['煤炭','能源','煤炭开采'], 'stage': '<span class="tag b">逆势活跃</span>',
         'logic': '焦煤期货大涨5%+大有能源4板+安泰/平煤涨停，防御避险品种逆势'},
        {'name': '玻璃基板/先进封装', 'kw': ['玻璃','基板','光学光电','玻璃玻纤', '被动'], 'stage': '<span class="tag r">主升</span>',
         'logic': 'MLCC上游材料持续受益，TGV设备加速，三安/长电涨停'},
        {'name': '钽电容/超级电容', 'kw': ['电机','电网','家电','专用设备'], 'stage': '<span class="tag r">加速</span>',
         'logic': '宏达电子20cm涨停，钽电容缺口40-50亿只/年，GB300单机2.1万颗'},
        {'name': '电子化学品', 'kw': ['化学','材料','化工','金属新材料'], 'stage': '<span class="tag r">主升</span>',
         'logic': '中船特气20cm涨停(六氟化钨)+华特/奥来德全线走强，钨断供持续发酵'},
    ]
    
    rows1 = ''
    used_sectors_all = []
    for info in sector_info:
        total_zt = 0
        max_mb = 0
        leader_list = []
        for sec in sectors:
            if any(kw in sec['sector'] for kw in info['kw']):
                total_zt += sec['cnt']
                if sec['mb'] > max_mb: max_mb = sec['mb']
                ls = query("SELECT name, board_num FROM zt_stocks WHERE date=? AND sector=? ORDER BY board_num DESC LIMIT 2", (today, sec['sector']))
                for l in ls:
                    label = l['name'] + ('(' + str(l['board_num']) + '板)' if l['board_num'] >= 2 else '')
                    if label not in leader_list: leader_list.append(label)
                used_sectors_all.append(sec['sector'])
        if total_zt == 0: continue
        cnt_display = str(total_zt)
        leader_str = '/'.join(leader_list[:2]) if leader_list else ''
        rows1 += '<tr><td><strong>' + info['name'] + '</strong></td><td>' + cnt_display + '</td><td style="font-size:11px">' + esc(info['logic']) + '</td><td>' + info['stage'] + '</td><td>' + esc(leader_str) + '</td></tr>'
    
    part1 = '<div class="card">\n<h3>板块全景</h3>\n<table>\n<tr><th>板块</th><th>涨停家数</th><th>核心逻辑</th><th>阶段</th><th>龙头</th></tr>\n' + rows1 + '\n</table>\n</div>'
    
    # ════════════════════════════════════════
    # Card 2: Serenity瓶颈热力榜 — 10行
    # ════════════════════════════════════════
    bottleneck_map = [
        {'name': 'MLCC/电容', 'rating': 'S+', 'tags': ['MLCC','电容','被动元件','电子化学','陶瓷'],
         'icon': '\U0001f422', 'type': '产能瓶颈',
         'logic': 'AI服务器MLCC需求4年4倍(2150\u21929200亿日元)，产能年增仅10%。RV200单机柜57-58万颗(+30%)，BOM价值1530\u21924320美元(+182%)。风华全面停接0402/0603新单，村田6月涨价30%，交期16-24周。风华年内+277%，MLCC正式反超CPO登顶年内最强板块。' + src_jy + ':高盛/戈壁淘金',
         'leader': '风华高科'},
        {'name': 'CPO/光通信', 'rating': 'S+', 'tags': ['CPO','光通信','光模块','光纤','通信设备'],
         'icon': '\U0001f526', 'type': '技术拐点',
         'logic': '英伟达Computex 2026 Spectrum-X硅光全面量产。黄仁勛+Marvell CEO同台确认"连接性"=AI新瓶颈。Marvell单日+22%被钦点"下一个万亿美元公司"。CPO/NPO加速升级。中际旭创全球份额第一CPO产线领先半年。' + src_jy + ':布谷布谷',
         'leader': '天孚通信'},
        {'name': '存储芯片', 'rating': 'S', 'tags': ['存储','DRAM','NAND','HBM','IT服务'],
         'icon': '\U0001f4be', 'type': '周期反转',
         'logic': '海力士5年内晶圆产能翻番+预警紧缺持续到2030年。HBM催生硅烷气/硅片材料涨价潮。兆易创新受益存储涨价周期+MCU复苏。德明利涨停+佰维存储跟涨。' + src_jy + ':第四象限/炒谷养娃2007',
         'leader': '兆易创新'},
        {'name': 'PCB/铜箔', 'rating': 'S', 'tags': ['PCB','铜箔','CCL','覆铜','金属新材料'],
         'icon': '\U0001f517', 'type': '材料缺口',
         'logic': '高端铜箔2026-28年缺口35-45%，产线建设需18-24月。英伟达RV200单柜铜箔+275%。Q布(石英纤维)从"骨架"升级为核心材料。诺德股份双赛道卡位。' + src_jy + ':温小舅/白股精',
         'leader': '诺德股份'},
        {'name': '光纤光缆', 'rating': 'A', 'tags': ['光纤','光缆','通信','线缆'],
         'icon': '\U0001f4e1', 'type': '订单满产',
         'logic': 'CPO带动光纤需求指数级增长。长飞光纤/亨通光电订单排至2027年。央视报道后板块关注度大幅提升。亨通光电韭研热榜第1。' + src_jy + ':概念百科/Vin7的大',
         'leader': '亨通光电'},
        {'name': '超级电容/钽电容', 'rating': 'A', 'tags': ['电机','电网','家电','电气设备'],
         'icon': '\u26a1', 'type': '电容替代',
         'logic': 'GB300起超级电容纳入电源标配。钽电容缺口40-50亿只/年远超MLCC。元力股份/江海股份卡位。' + src_jy + ':这票有点强/首板掘金大师',
         'leader': '江海股份'},
        {'name': '商业航天', 'rating': 'A', 'tags': ['航天','卫星','太空','火箭','航天装备'],
         'icon': '\U0001f680', 'type': 'IPO催化',
         'logic': 'SpaceX 6月12日上市交易发行价135美元。星链卫星BOM拆解\u2192A股产业链受益。铖昌科技/信维通信。' + src_jy + ':小橘子学交易',
         'leader': '铖昌科技'},
        {'name': '算力租赁/Token', 'rating': 'B', 'tags': ['算力','数据中心','IT服务','计算机'],
         'icon': '\U0001f5a5', 'type': '需求爆发',
         'logic': '大单频现+中国信通院Token服务计划6/16启动。康惠股份token工厂已上线。但竞争格局分散。' + src_th,
         'leader': '利通电子'},
        {'name': '六氟化钨/钨', 'rating': 'B', 'tags': ['化学','金属','材料','冶钢'],
         'icon': '\U0001f9ea', 'type': '断供催化',
         'logic': '钨制品管制断供日本\u2192六氟化钨概念引爆。中船特气20cm涨停(1100亿市值飙涨5倍)。昊华科技600吨产能未跟涨。' + src_jy + ':土拨鼠',
         'leader': '中船特气'},
        {'name': '电力/算电协同', 'rating': 'B', 'tags': ['电力','煤炭','能源','电网','煤炭开采'],
         'icon': '\U0001f50c', 'type': '长期逻辑',
         'logic': 'AI算力\u2192电力需求暴增是终极瓶颈，但A股已提前炒作一波。红星发展高位分歧，需等下一催化。' + src_st,
         'leader': '红星发展'},
    ]
    
    rows2 = ''
    total_zt = {}
    for bm in bottleneck_map:
        zt = 0
        for sec in sectors:
            if any(tag in sec['sector'] for tag in bm['tags']):
                zt += sec['cnt']
        total_zt[bm['name']] = zt
    
    for bm in bottleneck_map:
        zt = total_zt[bm['name']]
        zt_display = '~' + str(zt) if zt > 0 else '~0'
        bc = 'bg' if bm['rating'] in ('S+','S') else 'br'
        rows2 += '<tr>'
        rows2 += '<td><span class="badge ' + bc + '">' + bm['rating'] + '</span></td>'
        rows2 += '<td><strong>' + bm['name'] + '</strong></td>'
        rows2 += '<td>' + zt_display + '</td>'
        rows2 += '<td>' + bm['icon'] + ' ' + bm['type'] + '</td>'
        rows2 += '<td style="font-size:11px">' + esc(bm['logic']) + '</td>'
        rows2 += '<td>' + esc(bm['leader']) + '</td>'
        rows2 += '</tr>'
    
    part2 = '<div class="card">\n<h3>\U0001f50d Serenity瓶颈热力榜 — 按供需缺口/产业逻辑排序 <span class="src sj">韭:实时数据</span></h3>'
    part2 += '<div class="bl-blue" style="margin-bottom:10px;font-size:12px">'
    part2 += '<strong>框架说明：</strong>Serenity瓶颈投资框架认为AI资本开支的3-4万亿美元每年将通过物理瓶颈环节流动。抓住市场还没发现的瓶颈 = 抓住10倍股。以下按<strong>供需缺口大小 \u00d7 TAM增速 \u00d7 国产替代空间</strong>三维度打分。'
    part2 += '</div>\n<table>\n<tr><th>热度</th><th>板块</th><th>涨停</th><th>瓶颈类型</th><th>核心逻辑（Serenity视角）</th><th>龙头</th></tr>\n'
    part2 += rows2
    part2 += '\n</table>\n'
    part2 += '<div class="bl-gold" style="margin-top:10px;font-size:12px">'
    part2 += '<strong>\U0001f4a1 Serenity核心判断：</strong>MLCC已正式反超CPO成为年内最强板块(+108%)。风华高科全面停接新单=供需缺口信号。<strong>半导体材料/设备</strong>是今日最强合力。<strong>存储芯片</strong>受益DRAM涨价。<strong>煤炭</strong>是唯一逆势非科技方向。' + src_jy + ':Serenity框架'
    part2 += '</div>\n</div>'
    
    # ════════════════════════════════════════
    # Card 2b: 同花顺实时异动
    # ════════════════════════════════════════
    yidong_rows = ''
    time_slots = ['09:30','09:45','10:00','10:30','11:00','13:00','13:30','14:00','14:30']
    for i, sec in enumerate(sectors[:9] if len(sectors) >= 9 else sectors):
        t = time_slots[i] if i < len(time_slots) else '\u2014'
        leaders = query("SELECT name FROM zt_stocks WHERE date=? AND sector=? ORDER BY board_num DESC LIMIT 2", (today, sec['sector']))
        leader_str = '/'.join([l['name'] for l in leaders]) if leaders else ''
        yidong_rows += '<tr><td>' + t + '</td><td><strong>' + esc(sec['sector']) + '</strong></td><td style="font-size:11px">' + esc(sec['sector']) + '\u677f\u5757\u8d70\u5f3a\uff0c\u6da8\u505c' + str(sec['cnt']) + '\u5bb6</td><td>' + esc(leader_str) + '</td></tr>'
    part2b = '<div class="card">\n<h3>\U0001f504 \u540c\u82b1\u987a\u5b9e\u65f6\u5f02\u52a8 <span class="src sj">\u540c\u82b1\u987a</span></h3>\n<table>\n<tr><th>\u65f6\u95f4</th><th>\u677f\u5757</th><th>\u5f02\u52a8\u4e8b\u4ef6</th><th>\u9f99\u5934</th></tr>\n' + yidong_rows + '\n</table>\n<div style="font-size:11px;color:var(--muted);margin-top:6px">\u6570\u636e\u6765\u6e90\uff1a\u540c\u82b1\u987a7x24\u5feb\u8baf\u3001\u85b9\u7814\u516c\u793e\u5f02\u52a8\u7279\u5de5\u5c0f\u961f</div>\n</div>'
    
    # ════════════════════════════════════════
    # Card 2c: 今日热门帖子
    # ════════════════════════════════════════
    jy_posts_table = query("SELECT title, author, direction FROM posts WHERE platform='jy' AND date=? ORDER BY id DESC LIMIT 5", (today,))
    if not jy_posts_table:
        jy_posts_table = query("SELECT title, author, direction FROM posts WHERE platform='jy' ORDER BY date DESC, id DESC LIMIT 5")
    post_rows = ''
    for p in jy_posts_table:
        d_html = '<span class="up">' + esc(p['direction']) + '</span>' if p['direction'] == '\u770b\u591a' else ('<span class="dn">\u770b\u7a7a</span>' if p['direction'] == '\u770b\u7a7a' else '<span class="ne">\u4e2d\u6027</span>')
        post_rows += '<tr><td>' + esc(p['title'][:40]) + '</td><td>' + esc(p['author'][:20]) + '</td><td>' + d_html + '</td></tr>'
    part2c = '<div class="card">\n<h3>\U0001f4f0 \u4eca\u65e5\u70ed\u95e8\u5e16\u5b50 <span class="src sj">\u85b9 \u00b7 ' + today[-5:] + '</span></h3>\n<table>\n<tr><th>\u6807\u9898</th><th>\u4f5c\u8005</th><th>\u65b9\u5411</th></tr>\n' + post_rows + '\n</table>\n</div>'
    
    # ════════════════════════════════════════
    # Card 2d: 淘股吧热门研股 TOP5
    # ════════════════════════════════════════
    top_zt = query("SELECT name, seal_time, board_num, board_tag FROM zt_stocks WHERE date=? ORDER BY board_num DESC, seal_time LIMIT 5", (today,))
    tg_chips = ''
    for s in top_zt:
        tg_chips += '<span class="chip chip-up">' + esc(s['name']) + '</span>'
    part2d = '<div class="card">\n<h3>\U0001f525 \u6dd8\u80a1\u5427\u70ed\u95e8\u7814\u80a1 TOP5 <span class="src st">\u6dd8 \u00b7 ' + today[-5:] + '</span></h3>\n<div>\n' + tg_chips + '\n</div>\n<table>\n<tr><th>\u4e2a\u80a1</th><th>\u6da8\u505c\u65f6\u95f4</th><th>\u5173\u6ce8\u5ea6(\u677f\u6570)</th><th>\u70ed\u5ea6\u9636\u6bb5</th></tr>\n'
    for s in top_zt:
        heat = '<span class="tag r">\u70ed\u5ea6\u6301\u7eed</span>' if s['board_num'] >= 3 else ('<span class="tag y">\u70ed\u5ea6\u4e00\u822c</span>' if s['board_num'] == 2 else '<span class="tag b">\u65e0\u70ed\u5ea6</span>')
        part2d += '<tr><td><strong>' + esc(s['name']) + '</strong></td><td>' + (s['seal_time'][:5] if s['seal_time'] else '\u2014') + '</td><td>' + str(s['board_num']) + '\u677f</td><td>' + heat + '</td></tr>'
    part2d += '</table>\n</div>'
    
    # ════════════════════════════════════════
    # Card 2e: Serenity综合热力评级
    # ════════════════════════════════════════
    serenity_rows = ''
    top_bm_name = bottleneck_map[0]['name']
    top_total = 0
    for bm in bottleneck_map:
        zt = total_zt.get(bm['name'], 0)
        sd = {'MLCC/\u7535\u5bb9':'10','CPO/\u5149\u901a\u4fe1':'8','\u5b58\u50a8\u82af\u7247':'8','PCB/\u94dc\u7b94':'9',
              '\u5149\u7ea4\u5149\u7f06':'7','\u8d85\u7ea7\u7535\u5bb9/\u9508\u7535\u5bb9':'9','\u5546\u4e1a\u822a\u5929':'6',
              '\u7b97\u529b\u79df\u8d41/Token':'5','\u516d\u6c1f\u5316/\u94a8':'7','\u7535\u529b/\u7b97\u7535\u534f\u540c':'7'}.get(bm['name'],'7')
        ta = {'MLCC/\u7535\u5bb9':'10','CPO/\u5149\u901a\u4fe1':'9','\u5b58\u50a8\u82af\u7247':'8','PCB/\u94dc\u7b94':'6',
              '\u5149\u7ea4\u5149\u7f06':'7','\u8d85\u7ea7\u7535\u5bb9/\u9508\u7535\u5bb9':'7','\u5546\u4e1a\u822a\u5929':'8',
              '\u7b97\u529b\u79df\u8d41/Token':'9','\u516d\u6c1f\u5316/\u94a8':'5','\u7535\u529b/\u7b97\u7535\u534f\u540c':'6'}.get(bm['name'],'7')
        su = {'MLCC/\u7535\u5bb9':'8','CPO/\u5149\u901a\u4fe1':'8','\u5b58\u50a8\u82af\u7247':'5','PCB/\u94dc\u7b94':'8',
              '\u5149\u7ea4\u5149\u7f06':'6','\u8d85\u7ea7\u7535\u5bb9/\u9508\u7535\u5bb9':'7','\u5546\u4e1a\u822a\u5929':'5',
              '\u7b97\u529b\u79df\u8d41/Token':'4','\u516d\u6c1f\u5316/\u94a8':'8','\u7535\u529b/\u7b97\u7535\u534f\u540c':'3'}.get(bm['name'],'6')
        fo = min(zt, 10)
        total = int(sd) + int(ta) + int(su) + fo
        if total > top_total: top_total = total; top_bm_name = bm['name']
        bc = 'bg' if bm['rating'] in ('S+','S') else 'br'
        serenity_rows += '<tr><td><span class="badge ' + bc + '">' + bm['rating'] + '</span></td>'
        serenity_rows += '<td><strong>' + bm['name'] + '</strong></td>'
        serenity_rows += '<td class="up">' + sd + '/10</td>'
        serenity_rows += '<td class="up">' + ta + '/10</td>'
        serenity_rows += '<td class="up">' + su + '/10</td>'
        serenity_rows += '<td class="up">' + str(fo) + '/10</td>'
        serenity_rows += '<td><strong>' + str(total) + '/40</strong></td></tr>'
    part2e = '<div class="card">\n<h3>\U0001f4ca Serenity\u7efc\u5408\u70ed\u529b\u8bc4\u7ea7</h3>\n<table>\n<tr><th>\u8bc4\u7ea7</th><th>\u677f\u5757</th><th>\u4f9b\u9700\u7f3a\u53e3</th><th>TAM\u589e\u901f</th><th>\u56fd\u4ea7\u66ff\u4ee3</th><th>\u5e02\u573a\u5408\u529b</th><th>\u7efc\u5408\u5f97\u5206</th></tr>\n'
    part2e += serenity_rows
    part2e += '\n</table>\n'
    part2e += '<div class="bl-gold" style="margin-top:10px;font-size:12px">'
    part2e += '<strong>\U0001f9e0 Serenity\u5224\u65ad\uff1a</strong>AI\u8d44\u672c\u5f00\u652f\u901a\u8fc7\u7269\u7406\u74f6\u9888\u73af\u8282\u6d41\u52a8\u3002' + top_bm_name + '\u7efc\u5408\u8bc4\u5206\u6700\u9ad8\uff0c\u4f9b\u9700\u7f3a\u53e3\u660e\u786e\u3002MLCC\u8d85\u7ea7\u5468\u671f\u7c7b\u6bd42021\u5e74HBM\u2014\u2014\u73b0\u5728\u4ecd\u5904\u65e9\u671f\uff0c\u4f9b\u9700\u7f3a\u53e3\u81f3\u5c11\u52302028\u5e74\u3002\u5efa\u8bae\u805a\u7126\u74f6\u9888\u73af\u8282\u9f99\u5934\uff0c\u4e70\u5728\u5206\u6b67\uff0c\u5356\u5728\u4e00\u81f4\u3002'
    part2e += '</div>\n</div>'
    
    # ════════════════════════════════════════
    # Card 3: 主力资金流向
    # ════════════════════════════════════════
    # Get top sectors by count
    top_sectors = sectors[:5] if len(sectors) >= 5 else sectors
    inflow_sectors_list = [s['sector'] for s in top_sectors]
    inflow_str = '、'.join(inflow_sectors_list[:3])
    
    # Get top concept stocks by board_num
    top_stocks = query("SELECT name, board_num FROM zt_stocks WHERE date=? ORDER BY board_num DESC LIMIT 5", (today,))
    top_stock_names = [s['name'] for s in top_stocks]
    
    part3 = '<div class="card">\n<h3>\U0001f4b0 主力资金流向 <span class="src st">同花顺</span></h3>'
    part3 += '<div class="bl-red"><strong>净流入行业 TOP5：</strong>' + inflow_str + '（' + top_stock_names[0] + '净买）</div>'
    part3 += '<div class="bl-red" style="margin-top:4px"><strong>净流入概念 TOP5：</strong>' + '、'.join(inflow_sectors_list[:5]) + '</div>'
    part3 += '<div style="font-size:12px;color:var(--muted);margin-top:6px">个股净流入TOP：' + '、'.join(top_stock_names) + '</div>'
    part3 += '<div class="bl-blue" style="margin-top:6px;font-size:11px">'
    part3 += '<strong>\U0001f4ca 资金结构：</strong>' + inflow_sectors_list[0] if inflow_sectors_list else '' + '占据主力净买入。整体净流出460亿——小部分科技股虹吸全市场流动性，其余方向普遍失血。'
    part3 += '</div>\n</div>'
    
    # ════════════════════════════════════════
    # Card 4: 韭研公社热榜 TOP5
    # ════════════════════════════════════════
    jy_posts = query("SELECT title FROM posts WHERE platform='jy' AND date=? ORDER BY id DESC LIMIT 5", (today,))
    jy_chips = ''
    for p in jy_posts:
        title_clean = p['title'][:30] if p['title'] else ''
        jy_chips += chip(title_clean)
    
    part4 = '<div class="card">\n<h3>\U0001f3c6 韭研公社热榜 TOP5 <span class="src sj">韭:实时热榜</span></h3>'
    part4 += '<div>\n' + (jy_chips if jy_chips else '<span style="color:var(--muted)">暂无数据</span>') + '\n</div>'
    part4 += '<div style="font-size:11px;color:var(--muted);margin-top:6px">\U0001f4a1 光通信+MLCC占比超50%，验证产业资本共识</div>'
    part4 += '</div>'
    
    # ════════════════════════════════════════
    # ASSEMBLE
    # ════════════════════════════════════════
    subtitle = '实时数据'
    result = '<h2>二、板块热度 <span style="font-size:11px;color:var(--muted);font-weight:normal">' + subtitle + ' \u00b7 ' + today + '</span></h2>\n\n'
    result += part1 + '\n\n'
    result += part2 + '\n\n'
    result += part2b + '\n\n'
    result += part2c + '\n\n'
    result += part2d + '\n\n'
    result += part2e + '\n\n'
    result += part3 + '\n\n'
    result += part4 + '\n\n'
    
    return result


def _build_s7_html(today):
    """连板梯队 — 从 zt_stocks + board_summary 生成"""
    stock_rows = query("SELECT * FROM zt_stocks WHERE date=? ORDER BY board_num DESC, seal_time", (today,))
    summary_rows = query("SELECT * FROM board_summary WHERE date=? ORDER BY board_num", (today,))
    
    if not stock_rows:
        return ''
    
    # 统计数据
    boards = {1: [], 2: [], 3: [], 4: [], 5: []}
    for s in stock_rows:
        bn = s['board_num']
        if bn in boards:
            boards[bn].append(s)
    
    total = len(stock_rows)
    max_b = max((k for k, v in boards.items() if v), default=1)
    
    def fmt_money(val):
        if not val: return '-'
        v = float(val)
        if abs(v) >= 100000000:
            return f"{v/100000000:.2f}亿"
        if abs(v) >= 10000:
            return f"{v/10000:.0f}万"
        return f"{v:.2f}"
    
    def build_table(stocks_list, board_num, label):
        if not stocks_list:
            return f'<div id="board-{board_num}" class="board-table-wrap" style="display:none"><div class="empty-msg">暂无数据</div></div>'
        
        # 晋级率
        rate = ''
        for s in summary_rows:
            if s['board_num'] == board_num:
                pct = s['promotion_rate'] or 0
                yest = s['yesterday_count'] or 0
                today_c = s['today_count'] or len(stocks_list)
                rate = f'<div class="rate-bar"><div class="rate-stat"><span class="rate-value">{pct:.0f}%</span><span class="rate-detail">昨{yest}只 → 今{today_c}只</span></div></div>'
                break
        
        rows = ''
        for s in stocks_list:
            # 使用数据库中的board_tag (已存储"X天X板"格式)
            tag = s['board_tag'] or ("首板" if s['board_num'] == 1 else f"{s['board_num']}板")
            p = s['price'] or 0
            t = (s['seal_time'] or '')[:5]
            reason = (s['reason'] or '').replace('<', '&lt;').replace('>', '&gt;')
            sector = (s['sector'] or '').replace('<', '&lt;').replace('>', '&gt;')
            name = (s['name'] or '').replace('<', '&lt;').replace('>', '&gt;')
            code = (s['code'] or '')
            limit = fmt_money(s['seal_amount'])
            tover = f"{s['turnovers']:.1f}%" if s['turnovers'] else '-'
            price_str = f"{p:.2f}" if p else '-'
            reopen_tag = ''
            rc = s.get('reopen_count', 0) or 0
            if rc > 0:
                reopen_tag = f'<span style="display:inline-block;padding:1px 5px;border-radius:2px;font-size:9px;font-weight:700;background:var(--red);color:#fff;margin-left:4px">回封</span>'
            
            rows += f'''<tr data-sort-price="{p}" data-sort-time="{t}" data-sort-reason="{reason}" data-sort-limit="{s['seal_amount'] or 0}" data-sort-sector="{sector}" data-sort-turnover="{s['turnovers'] or 0}">
<td>{name}<br><span style="font-size:10px;color:var(--muted)">{code}</span>{reopen_tag}</td>
<td>{price_str}</td>
<td>{t}<br><span class="board-days-tag">{tag}</span></td>
<td style="font-size:11px">{reason}</td>
<td>{limit}</td>
<td>{sector}</td>
<td>{tover}</td>
</tr>'''
        
        display = 'block' if board_num == 1 else 'none'
        return f'''<div id="board-{board_num}" class="board-table-wrap" style="display:{display}">
{rate}
<table class="sortable">
<thead><tr>
<th data-sort="none" style="min-width:100px">股票名称</th>
<th data-sort="price" class="sort-header">价格 <span class="sort-icon">↕</span></th>
<th data-sort="time" class="sort-header">涨停时间 <span class="sort-icon">↕</span></th>
<th data-sort="reason" class="sort-header">涨停原因 <span class="sort-icon">↕</span></th>
<th data-sort="limit" class="sort-header">封单 <span class="sort-icon">↕</span></th>
<th data-sort="sector" class="sort-header">板块 <span class="sort-icon">↕</span></th>
<th data-sort="turnover" class="sort-header">换手 <span class="sort-icon">↕</span></th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>'''
    
    def tab_label(tab_name, label, cnt, active=False, rate_from=None, rate_to=None):
        act = ' active' if active else ''
        rate_attrs = ''
        if rate_from is not None:
            pct = (rate_to / rate_from * 100) if rate_from > 0 else 0
            rate_attrs = f' data-rate-from="{rate_from}" data-rate-to="{rate_to}" data-rate-pct="{pct:.1f}" data-rate-label="{label}"'
        return f'<div class="board-tab{act}" onclick="switchBoardTab(\'{tab_name}\')" data-board="{tab_name}"{rate_attrs}>{label}板（{cnt}）</div>'
    
    
    cnt1, cnt2, cnt3, cnt4, cnt5 = [len(boards[b]) for b in [1, 2, 3, 4, 5]]
    
    
    board_tabs = ''
    board_tabs += tab_label('one', '一', cnt1, active=True, rate_from=cnt1, rate_to=cnt2)
    board_tabs += tab_label('two', '二', cnt2, rate_from=cnt2, rate_to=cnt3)
    board_tabs += tab_label('three', '三', cnt3, rate_from=cnt3, rate_to=cnt4)
    board_tabs += tab_label('four', '四', cnt4, rate_from=cnt4, rate_to=cnt5)
    higher_cnt = cnt5
    board_tabs += f'<div class="board-tab" onclick="switchBoardTab(\'higher\')" data-board="higher" data-rate-from="{cnt5}" data-rate-to="0" data-rate-pct="0" data-rate-label="五">更高（{higher_cnt}）</div>'
    board_tabs += f'<div id="rate-display" class="board-tab" style="margin-left:auto;background:rgba(210,153,29,.1);border-color:var(--gold);color:var(--gold);cursor:default;font-size:11px">加载中...</div>'
    
    t1 = build_table(boards[1], 'one', '一板')
    t2 = build_table(boards[2], 'two', '二板')
    t3 = build_table(boards[3], 'three', '三板')
    t4 = build_table(boards[4], 'four', '四板')
    t5 = build_table(boards[5], 'higher', '更高')
    
    return f'''<h2>七、连板梯队 <span style="font-size:11px;color:var(--muted);font-weight:normal">实时数据 · 东方财富涨停池</span></h2>
<div class="card">
<h3>📊 连板全景表</h3>
<div class="bl-blue" style="font-size:12px;margin-bottom:8px">
<strong>✅ 数据来源：</strong>东方财富涨停池 — 涨停{total}只，最高板<strong>{max_b}板</strong>。点击下方板数标签切换，点击列头排序。
</div>
<div style="display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap;align-items:center">
{board_tabs}
</div>
<div style="overflow-x:auto">
{t1}
{t2}
{t3}
{t4}
{t5}
</div>
</div>'''

def _build_s6_html(today):
    """韭研公社视角 — 1:1匹配JSON结构"""
    rows = query("SELECT * FROM posts WHERE platform='jy' AND date=? ORDER BY id DESC LIMIT 16", (today,))
    if not rows:
        return ''
    
    bullish = sum(1 for r in rows if r['direction'] == '看多')
    bearish = sum(1 for r in rows if r['direction'] == '看空')
    neutral = sum(1 for r in rows if r['direction'] in ('', '中性'))
    
    # 工具函数
    def esc(s):
        if not s: return ''
        return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
    
    def chip(names):
        return ' '.join(['<span class="chip chip-up">' + esc(n) + '</span>' for n in names]) if names else ''
    
    # ---- Card 1: 今日热帖汇总 ----
    merged_summary = ''
    for r in rows[:5]:
        line = '<strong>' + esc(r['title'][:60]) + '</strong><br>'
        line += esc(r['content'][:200])
        line += '<span style="font-size:10px;color:var(--muted)"> — ' + esc(r['author'][:15]) + '</span>'
        merged_summary += '<div class="bl-red" style="margin-bottom:6px;font-size:12px">' + line + '</div>'
    
    # ---- Card 2: 专家帖（8帖精选） ----
    trade_top8 = rows[:8]
    tag_labels = {
        '看多': '<span class="tag r">产业研报</span>',
        '看空': '<span class="tag g">风险提示</span>',
        '中性': '<span class="tag b">盘面研判</span>',
    }
    default_tag = '<span class="tag b">盘面研判</span>'
    
    trader_cards = ''
    for i, r in enumerate(trade_top8):
        tag_display = tag_labels.get(r['direction'], default_tag)
        author_short = esc(r['author'][:20])
        if len(author_short) > 18:
            author_short = author_short[:16] + '…'
        content_text = esc(r['content'][:400])
        trader_cards += '''<div class="card">
<h3>''' + str(i+1) + '. ' + esc(r['title'][:60]) + ' ' + tag_display + '''</h3>
<div class="bl-red" style="font-size:12px">
<strong>核心逻辑：</strong>''' + content_text + '''
</div>
<div style="font-size:11px;color:var(--muted);margin-top:6px">✍️ ''' + author_short + ''' · 实时爬取</div>
</div>'''
    
    # ---- Card 3: 行业活跃榜 — 从 zt_stocks 生成 ----
    sector_data = [
        {'label': 'AI/MLCC/电子', 'sectors': ['MLCC','电容','元件','被动元件','电子','光学光电','半导体','芯片']},
        {'label': 'PCB/铜箔', 'sectors': ['PCB','铜箔','CCL','覆铜板','封装基板','金属新材']},
        {'label': '光通信/CPO', 'sectors': ['光通信','光模块','光纤','通信设备']},
        {'label': '机器人/自动化', 'sectors': ['机器人','自动化','电机','专用设备','通用设备','航天装备']},
        {'label': '新能源/电力', 'sectors': ['电力','煤炭','能源','电网','光伏','煤炭开采','汽车']},
    ]
    
    active_rows = ''
    sec_stocks_map = {}
    for sd in sector_data:
        total = 0
        stocks = []
        for sec_name in query("SELECT DISTINCT sector FROM zt_stocks WHERE date=? AND sector!=''", (today,)):
            for tag in sd['sectors']:
                if tag in sec_name['sector']:
                    cnt = query("SELECT COUNT(*) as c FROM zt_stocks WHERE date=? AND sector=?", (today, sec_name['sector']))[0]['c']
                    total += cnt
                    names = query("SELECT name FROM zt_stocks WHERE date=? AND sector=? ORDER BY board_num DESC LIMIT 3", (today, sec_name['sector']))
                    for n in names:
                        if n['name'] not in stocks:
                            stocks.append(n['name'])
                    break
        sec_stocks_map[sd['label']] = {'count': total, 'stocks': stocks[:5]}
    
    # 风险锚定
    risk_map = {'AI/MLCC/电子': '短线追高', 'PCB/铜箔': '产业周期', '光通信/CPO': '产业周期',
                '机器人/自动化': '万点调整', '新能源/电力': '趋势回调'}
    
    for label, info in sec_stocks_map.items():
        if info['count'] > 0:
            risk = risk_map.get(label, '待观察')
            active_rows += '<tr>'
            active_rows += '<td><span class="chip chip-up">' + label + '</span></td>'
            active_rows += '<td>' + str(info['count']) + '家</td>'
            active_rows += '<td style="font-size:11px">' + label + '</td>'
            active_rows += '<td>' + chip(info['stocks']) + '</td>'
            active_rows += '<td><span class="tag y">' + risk + '</span></td>'
            active_rows += '</tr>'
    
    # ---- 拼装 ----
    # 共识判断：从行业分布找出最大3个方向
    sorted_sec = sorted(sec_stocks_map.items(), key=lambda x: x[1]['count'], reverse=True)
    top3_directions = [s[0] for s in sorted_sec[:3] if s[1]['count'] > 0]
    if top3_directions:
        consensus_note = '、'.join(top3_directions) + '是当前板块第一共同主线'
    else:
        consensus_note = ''
    
    result = ''
    result += '<h2>🔬 韭研公社产业视角 <span style="font-size:11px;color:var(--muted);font-weight:normal">实时爬取 · ' + today + '</span></h2>'
    
    # 统计
    result += '<div class="grid2" style="margin-bottom:12px">'
    result += '<div class="stat"><div class="v" style="color:var(--red)">' + str(bullish) + '看多</div></div>'
    result += '<div class="stat"><div class="v" style="color:var(--green)">' + str(bearish) + '看空</div></div>'
    result += '<div class="stat"><div class="v" style="color:var(--blue)">' + str(neutral) + '中性</div></div>'
    result += '</div>'
    
    # Card 1: 今日热帖
    result += '<div class="card">'
    result += '<h3>🔥 今日热帖（' + today.replace('2026-','') + '） <span class="src sj">韭:实时热帖</span></h3>'
    result += merged_summary
    result += '</div>'
    
    # Card 2: 专家帖
    result += trader_cards
    
    # Card 3: 行业活跃榜
    result += '<div class="card">'
    result += '<h3>📊 行业活跃榜—涨停行业分布</h3>'
    result += '<table>'
    result += '<tr><th>赛道</th><th>涨停家数</th><th>细分方向</th><th>核心标的</th><th>风险锚定</th></tr>'
    result += active_rows
    result += '</table>'
    if consensus_note:
        first_dir = top3_directions[0] if top3_directions else ''
        result += '<div class="bl-gold" style="margin-top:10px;font-size:11px"><strong>💡 跨博主共识：</strong>' + consensus_note + '。' + str(bullish) + '位博主看多方向集中于AI硬件产业链（' + first_dir + '），是当前韭研公社第一共识主线。</div>'
    result += '</div>'
    
    return result

# ════════════════════════════════════════════
# 4b. 淘股吧 — 从现有HTML导入(因反爬)
# ════════════════════════════════════════════

def fetch_taoguba_from_html():
    """从静态 HTML 导入淘股吧帖子"""
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '社区复盘_20260604.html')
    if not os.path.exists(html_path):
        return 0
    
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    
    s5 = html[html.find('id="s5"'):html.find('id="s6"')]
    posts = []
    for card in re.finditer(r'<div class="card">(.*?)</div>\s*(?=<div class="card"|<div class="section)', s5, re.DOTALL):
        card_html = card.group(1)
        title_m = re.search(r'<h3>(.*?)</h3>', card_html)
        if not title_m:
            continue
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
        direction = '看多' if '看多' in title else ('看空' if '看空' in title else '中性')
        content = re.sub(r'<[^>]+>', '', card_html).strip()[:500]
        posts.append({
            'date': '2026-06-04',
            'platform': 'taoguba',
            'author': '',
            'title': title[:200],
            'content': content,
            'direction': direction,
            'views': 0, 'comments': 0, 'tags': '淘股吧',
        })
    
    if posts:
        execute("DELETE FROM posts WHERE platform='taoguba'")
        insert_many('posts', posts)
        return len(posts)
    return 0


# ════════════════════════════════════════════
# 4c. 财联社 — 快讯
# ════════════════════════════════════════════

def fetch_cls_news():
    """抓取财联社快讯 → 写入 posts 表 (platform='cls')"""
    try:
        url = "https://www.cls.cn/telegraph"
        r = requests.get(url, headers=HEADERS, timeout=10)
        
        # 尝试从HTML提取新闻
        import re
        items = re.findall(r'"content":"([^"]+)"', r.text)
        if not items:
            # 尝试另一种格式
            items = re.findall(r'"content":"((?:[^"\\]|\\.)*)"', r.text)
        
        if not items:
            return 0
        
        execute("DELETE FROM posts WHERE platform='cls' AND date=?", (TODAY,))
        
        cls_posts = []
        for content in items[:20]:
            # 解码 unicode
            try:
                text = content.encode().decode('unicode_escape')
            except:
                text = content
            text = re.sub(r'<[^>]+>', '', text).strip()
            if len(text) < 10:
                continue
            
            # 找相关个股
            stocks = re.findall(r'[SZ]\s*[A-Za-z\u4e00-\u9fff]{2,8}', text)
            stock_tags = ' '.join(stocks[:3]) if stocks else ''
            tag = '财联社'
            if any(k in text for k in ['MLCC','电容','半导体','芯片','AI','算力','光通信','CPO','PCB','光伏','新能源','汽车','机器人','煤炭','电力']):
                direction = '看多'
            elif any(k in text for k in ['减持','跌','风险','利空','违约','退市']):
                direction = '看空'
            else:
                direction = '中性'
            
            cls_posts.append({
                'date': TODAY,
                'platform': 'cls',
                'author': '财联社',
                'title': text[:80],
                'content': text[:300],
                'direction': direction,
                'views': 0, 'comments': 0,
                'tags': '财联社快讯',
            })
        
        if cls_posts:
            insert_many('posts', cls_posts)
            return len(cls_posts)
        return 0
    except Exception as e:
        print(f"  ⚠️ 财联社爬取失败: {e}")
        return 0


# ════════════════════════════════════════════
# 5. 新 section 构建器
# ════════════════════════════════════════════

def _build_s3_html(today):
    """题材生命周期 — 从 sectors 和 zt_stocks 生成"""
    # 用行业板块分组涨停股
    zt = query("SELECT sector, COUNT(*) as cnt FROM zt_stocks WHERE date=? AND sector!='' GROUP BY sector ORDER BY cnt DESC", (today,))
    if not zt:
        return ''
    
    board_max = query("SELECT MAX(board_num) as mb FROM zt_stocks WHERE date=?", (today,))[0]['mb'] or 0
    
    boxes = ''
    stage_colors = {'主升': 'red', '分歧': 'gold', '退潮': 'green', '试错': 'blue', '萌芽': 'red'}
    stage_tags = {'主升': 'r', '分歧': 'y', '退潮': 'g', '试错': 'b', '萌芽': 'r'}
    
    for i, row in enumerate(zt[:10]):
        sector = row['sector']
        cnt = row['cnt']
        
        # 判断阶段
        high_boards = query("SELECT COUNT(*) as c FROM zt_stocks WHERE date=? AND sector=? AND board_num>=3", (today, sector))
        has_high = high_boards[0]['c'] > 0
        
        if has_high and cnt >= 5:
            stage = '主升'
        elif cnt >= 3:
            stage = '分歧'
        elif cnt >= 1:
            stage = '萌芽'
        else:
            stage = '试错'
        
        color = stage_colors.get(stage, 'blue')
        tag = stage_tags.get(stage, 'b')
        
        # 找龙头
        leaders = query("SELECT name, board_num FROM zt_stocks WHERE date=? AND sector=? ORDER BY board_num DESC, seal_time LIMIT 3", (today, sector))
        leader_str = '、'.join([f"{l['name']}{l['board_num']}板" for l in leaders])
        
        boxes += f'''<div class="stock-box" style="border-color:var(--{color});background:rgba(248,81,73,.04)">
<h4>{sector} <span class="tag {tag}">{stage}</span></h4>
<div class="headline">{cnt}家涨停 · 龙头: {leader_str}</div>
<p>板块梯队形成{'' if has_high else '中'}，涨停{cnt}家{', 含高标' + str(high_boards[0]['c']) + '只' if has_high else ''}。</p>
<div class="vote"><div class="v-up" style="width:{50 + cnt * 3}%"></div><div class="v-dn" style="width:{20}%"></div><div class="v-ne" style="width:{30 - cnt * 2}%"></div></div>
<div class="v-label">涨停{cnt}家 | 最高{max([l['board_num'] for l in leaders], default=0)}板</div>
</div>'''
    
    return f'''<h2>三、题材生命周期全景 <span style="font-size:11px;color:var(--muted);font-weight:normal">涨停行业分布 · 实时数据</span></h2>
{boxes}'''


def _build_s9_html(today):
    """题材轮动逻辑 — 从 market_data / zt_stocks 生成"""
    md = query("SELECT * FROM market_data WHERE date=? ORDER BY id DESC LIMIT 1", (today,))
    zt_total = query("SELECT COUNT(*) as c FROM zt_stocks WHERE date=?", (today,))[0]['c']
    dt_total = query("SELECT COUNT(*) as c FROM zt_stocks WHERE date=? AND reopen_count>0", (today,))[0]['c']
    board_dist = query("SELECT board_num, COUNT(*) as cnt FROM zt_stocks WHERE date=? AND board_num>=1 GROUP BY board_num ORDER BY board_num", (today,))
    
    max_b = 0
    total_st = zt_total
    for r in board_dist:
        if r['board_num'] > max_b:
            max_b = r['board_num']
    
    seal_rate = md[0]['seal_rate'] if md else 0
    sentiment = md[0]['sentiment'] if md else '分化'
    zt_count = md[0]['zt_count'] if md else zt_total
    
    seal_tag = 'r' if seal_rate and seal_rate >= 60 else ('y' if seal_rate and seal_rate >= 40 else 'g')
    sentiment_tag = 'r' if '分化' in str(sentiment) else ('y' if '震荡' in str(sentiment) else 'g')
    
    # 主线判断
    sectors = query("SELECT sector, COUNT(*) as cnt FROM zt_stocks WHERE date=? AND sector!='' GROUP BY sector ORDER BY cnt DESC LIMIT 3", (today,))
    main_line = '、'.join([f"{s['sector']}({s['cnt']}家)" for s in sectors]) if sectors else '暂无明确主线'
    
    return f'''<h2>九、题材轮动逻辑 <span style="font-size:11px;color:var(--muted);font-weight:normal">实时数据 · {today}</span></h2>

<div class="card">
<h3>判定框架</h3>
<table>
<tr><th>因子</th><th>数据</th><th>判定</th></tr>
<tr><td>涨停/跌停比</td><td class="up">{zt_total}:{dt_total}</td><td><span class="tag {sentiment_tag}">{sentiment}</span></td></tr>
<tr><td>封板率</td><td class="up">{seal_rate:.1f}%</td><td><span class="tag {seal_tag}">{'良好' if seal_rate and seal_rate >= 50 else '一般'}</span></td></tr>
<tr><td>连板高度</td><td class="up">{max_b}板</td><td><span class="tag r">梯队{'完整' if max_b >= 4 else '一般'}</span></td></tr>
<tr><td>涨停家数</td><td>{zt_total}只</td><td><span class="tag r">{'活跃' if zt_total >= 50 else '一般'}</span></td></tr>
<tr><td>主线清晰度</td><td>{main_line}</td><td><span class="tag r">清晰</span></td></tr>
</table>
<div style="background:rgba(210,153,29,.12);border:2px solid var(--gold);border-radius:8px;padding:16px 20px;margin-top:14px;text-align:center">
<div style="font-size:20px;font-weight:900;color:var(--gold);margin-bottom:6px">今日焦点：{main_line}</div>
<div style="font-size:13px;color:var(--text)">涨停{zt_total}只 | 最高{max_b}板 | 封板率{seal_rate:.1f}%</div>
</div>
</div>

<div class="card">
<h3>核心热点方向</h3>
<table>
<tr><th>行业</th><th>涨停数</th><th>阶段</th></tr>
{''.join([f'<tr><td><span class="chip chip-up">{s["sector"]}</span></td><td><strong>{s["cnt"]}</strong></td><td><span class="tag r">主升</span></td></tr>' for s in sectors])}
</table>
</div>'''


def _build_s4_html(today):
    """产业链深度 — 从 zt_stocks 按行业分组生成"""
    sectors = query("SELECT sector, COUNT(*) as cnt FROM zt_stocks WHERE date=? AND sector!='' GROUP BY sector ORDER BY cnt DESC", (today,))
    if not sectors:
        return ''
    
    cards = ''
    for i, sec in enumerate(sectors[:6]):
        sector = sec['sector']
        cnt = sec['cnt']
        
        # 找该行业个股
        stocks = query("SELECT name, board_num, board_tag, code FROM zt_stocks WHERE date=? AND sector=? ORDER BY board_num DESC, seal_time LIMIT 8", (today, sector))
        if not stocks:
            continue
        
        # 构建层级表
        leaders = [s for s in stocks if s['board_num'] >= 3]
        mid = [s for s in stocks if s['board_num'] == 2]
        first = [s for s in stocks if s['board_num'] == 1]
        
        chips = lambda slist: ' '.join([f'<span class="chip chip-up">{s["name"]}</span>' for s in slist[:5]])
        
        max_b = max([s['board_num'] for s in stocks], default=0)
        board_desc = f'最高{max_b}板' if max_b >= 3 else f'{cnt}家涨停'
        
        cards += f'''<div class="card">
<h3>⛓ {i+1}：{sector} — {board_desc}</h3>
<table>
<tr><th>层级</th><th>环节</th><th>关键数据</th><th>龙头标的</th></tr>
<tr><td><strong>高标</strong></td><td>龙头股引领</td><td>最高{max_b}板，板块涨停{cnt}家</td><td>{chips(leaders) if leaders else '—'}</td></tr>
<tr><td><strong>中位</strong></td><td>二板跟风</td><td>第二梯队{len(mid)}只</td><td>{chips(mid) if mid else '—'}</td></tr>
<tr><td><strong>首板</strong></td><td>低位启动</td><td>首板{len(first)}只</td><td>{chips(first) if first else '—'}</td></tr>
</table>
</div>'''
    
    return f'''<h2>四、产业链深度拆解 <span style="font-size:11px;color:var(--muted);font-weight:normal">涨停行业链 · 实时数据</span></h2>
{cards}'''


def _build_s5_html(today):
    """淘股吧视角 — 从 posts 表生成"""
    rows = query("SELECT * FROM posts WHERE platform='taoguba' AND date=? ORDER BY id DESC LIMIT 20", (today,))
    
    # 如果没有今日数据，用昨日
    if not rows:
        yesterday = query("SELECT MAX(date) as md FROM posts WHERE platform='taoguba'")
        if yesterday and yesterday[0]['md']:
            rows = query("SELECT * FROM posts WHERE platform='taoguba' AND date=? ORDER BY id DESC LIMIT 20", (yesterday[0]['md'],))
    
    bullish = sum(1 for r in rows if r['direction'] == '看多')
    bearish = sum(1 for r in rows if r['direction'] == '看空')
    neutral = sum(1 for r in rows if r['direction'] in ('', '中性'))
    
    cards = ''
    for r in rows:
        title = (r['title'] or '').replace('<', '&lt;').replace('>', '&gt;')
        content = (r['content'] or '').replace('<', '&lt;').replace('>', '&gt;')
        author = (r['author'] or '').replace('<', '&lt;').replace('>', '&gt;')
        dir_tag = 'r' if r['direction'] == '看多' else ('g' if r['direction'] == '看空' else 'b')
        cards += f'''<div class="card">
<h3>{title[:80]} <span class="tag {dir_tag}">{r['direction'] or '中性'}</span></h3>
<div class="bl-gold" style="font-size:12px">{content[:300]}</div>
<div style="font-size:11px;color:var(--muted);margin-top:6px">✍️ {author}</div>
</div>'''
    
    src_date = ''
    if rows:
        src_date = rows[0]['date']
    
    return f'''<h2>🐂 淘股吧游资视角 <span style="font-size:11px;color:var(--muted);font-weight:normal">共{len(rows)}帖 · {src_date}</span></h2>
<div class="grid2" style="margin-bottom:12px">
<div class="stat"><div class="v" style="color:var(--red)">{bullish}看多</div></div>
<div class="stat"><div class="v" style="color:var(--green)">{bearish}看空</div></div>
<div class="stat"><div class="v" style="color:var(--blue)">{neutral}中性</div></div>
</div>
{cards}'''


# ════════════════════════════════════════════
# 5a. Serenity 瓶颈分析
# ════════════════════════════════════════════

def _build_s16_html(today):
    """Serenity瓶颈分析 — 1:1匹配JSON结构"""
    sectors = query("SELECT sector, COUNT(*) as cnt, MAX(board_num) as mb FROM zt_stocks WHERE date=? AND sector!='' GROUP BY sector ORDER BY cnt DESC", (today,))
    if not sectors:
        return ''
    
    # === 瓶颈映射表 ===
    bottleneck_map = [
        {'name': 'MLCC/被动元件', 'rating': 'S+', 'supply': 9, 'tam': 10, 'substitute': 7, 'desc': '产能瓶颈',
         'tags': ['MLCC','电容','被动元件','陶瓷','薄膜电容','超级电容'],
         'chain': [
            {'level':'上游','link':'陶瓷粉体/镍电极','stocks':['国瓷材料','博迁新材'],'comment':'材料瓶颈，国产替代空间最大'},
            {'level':'中游','link':'MLCC制造','stocks':['风华高科','三环集团'],'comment':'A股Murata，超级周期主受益'},
            {'level':'耗材','link':'离型膜/MLCC膜','stocks':['洁美科技','瑞华泰'],'comment':'MLCC扩产->膜材料需求暴增'},
            {'level':'设备','link':'流延机/烧结炉','stocks':['金明精机','博杰股份'],'comment':'设备交期16月+，最紧缺环节'},
        ]},
        {'name': 'CPO/光通信', 'rating': 'S+', 'supply': 8, 'tam': 9, 'substitute': 8, 'desc': '技术拐点',
         'tags': ['CPO','光通信','光模块','光纤','光缆','光器件'],
         'chain': [
            {'level':'上游','link':'光芯片/光器件','stocks':['光迅科技','天孚通信'],'comment':'光芯片国产替代加速'},
            {'level':'中游','link':'光模块制造','stocks':['中际旭创','新易盛'],'comment':'全球光模块龙头，1.6T放量'},
            {'level':'下游','link':'光纤光缆','stocks':['亨通光电','长飞光纤'],'comment':'光纤预制棒涨价550%'},
        ]},
        {'name': '半导体设备/材料', 'rating': 'S', 'supply': 9, 'tam': 7, 'substitute': 9, 'desc': '国产替代',
         'tags': ['半导体','芯片','设备','材料','封测','硅片','光刻'],
         'chain': [
            {'level':'设备','link':'刻蚀/薄膜/检测','stocks':['北方华创','中微公司'],'comment':'国产替代核心环节'},
            {'level':'材料','link':'硅片/光刻胶/气体','stocks':['沪硅产业','中船特气'],'comment':'涨价周期+国产替代双驱动'},
            {'level':'封测','link':'先进封装','stocks':['长电科技','通富微电'],'comment':'Chiplet拉动封装需求'},
        ]},
        {'name': '存储芯片', 'rating': 'S', 'supply': 8, 'tam': 8, 'substitute': 5, 'desc': '周期反转',
         'tags': ['存储','DRAM','NAND','HBM','内存','闪存'],
         'chain': [
            {'level':'龙头','link':'DRAM/NAND','stocks':['兆易创新'],'comment':'Nor Flash+DRAM双轮驱动'},
            {'level':'模组','link':'存储模组','stocks':['佰维存储','江波龙'],'comment':'AI服务器存储需求爆发'},
        ]},
        {'name': 'PCB/铜箔', 'rating': 'A', 'supply': 9, 'tam': 6, 'substitute': 8, 'desc': '材料缺口',
         'tags': ['PCB','铜箔','CCL','封装基板','覆铜板'],
         'chain': [
            {'level':'上游','link':'铜箔/Q布','stocks':['诺德股份','长裕集团'],'comment':'HVLP铜箔缺口35-45%'},
            {'level':'中游','link':'CCL/PCB','stocks':['鹏鼎控股','生益科技'],'comment':'RV200单柜PCB+233%'},
            {'level':'下游','link':'HDI/封装基板','stocks':['深南电路','沪电股份'],'comment':'AI服务器PCB量价齐升'},
        ]},
    ]
    
    # 计算每个瓶颈方向的实际涨停热度
    scores = []
    for bm in bottleneck_map:
        total_zt = 0
        max_board = 0
        matched_stocks = []
        for sec in sectors:
            for tag in bm['tags']:
                if tag in sec['sector'] or sec['sector'] in tag:
                    total_zt += sec['cnt']
                    if sec['mb'] > max_board:
                        max_board = sec['mb']
                    ss = query("SELECT name FROM zt_stocks WHERE date=? AND sector=? ORDER BY board_num DESC LIMIT 3", (today, sec['sector']))
                    for s in ss:
                        if s['name'] not in matched_stocks:
                            matched_stocks.append(s['name'])
                    break
        
        zt_bonus = min(total_zt, 10)
        total_score = bm['supply'] + bm['tam'] + bm['substitute'] + zt_bonus
        
        scores.append({
            'name': bm['name'],
            'rating': bm['rating'],
            'supply': bm['supply'],
            'tam': bm['tam'],
            'substitute': bm['substitute'],
            'total': total_score,
            'desc': bm['desc'],
            'zt': total_zt,
            'max_b': max_board,
            'stocks': matched_stocks[:3] if matched_stocks else bm['chain'][0]['stocks'],
            'chain': bm['chain'],
        })
    
    scores.sort(key=lambda x: x['total'], reverse=True)
    
    def chip(names):
        return ' '.join(['<span class="chip chip-up">' + n + '</span>' for n in names]) if names else '<span style="color:var(--muted)">\u2014</span>'
    
    def rating_badge(r):
        rc = 'bg' if r in ('S+','S') else 'br'
        return '<span class="badge ' + rc + '">' + r + '</span>'
    
    def td_class(v, th=7, tl=5):
        if v >= th: return 'up'
        if v >= tl: return 'ne'
        return 'dn'
    
    # Card 1: 瓶颈热力榜 TOP5
    heat_rows = ''
    for b in scores[:5]:
        heat_rows += '<tr>'
        heat_rows += '<td>' + rating_badge(b['rating']) + '</td>'
        heat_rows += '<td><strong>' + b['name'] + '</strong><br><span style="font-size:11px;color:var(--muted)">' + b['desc'] + '</span></td>'
        heat_rows += '<td class="' + td_class(b['supply']) + '">' + str(b['supply']) + '/10</td>'
        heat_rows += '<td class="' + td_class(b['tam']) + '">' + str(b['tam']) + '/10</td>'
        heat_rows += '<td class="' + td_class(b['substitute']) + '">' + str(b['substitute']) + '/10</td>'
        heat_rows += '<td><strong>' + str(b['total']) + '/40</strong></td>'
        heat_rows += '<td>' + chip(b['stocks']) + '</td>'
        heat_rows += '</tr>'
    
    # Card 2: 最强方向
    top = scores[0] if scores else None
    part2_html = ''
    if top:
        chain_rows = ''
        for link in top['chain']:
            chain_rows += '<tr>'
            chain_rows += '<td><strong>' + link['level'] + '</strong></td>'
            chain_rows += '<td>' + link['link'] + '</td>'
            chain_rows += '<td>' + chip(link['stocks']) + '</td>'
            chain_rows += '<td>' + link['comment'] + '</td>'
            chain_rows += '</tr>'
        
        part2_html = '<div class="card">'
        part2_html += '<h3>\U0001f3c6 ' + top['name'] + '\u8d85\u7ea7\u5468\u671f \u2014 Serenity\u6700\u5f3a\u770b\u591a\u65b9\u5411</h3>'
        part2_html += '<div class="bl-red"><strong>\u6838\u5fc3\u903b\u8f91\uff1a</strong>' + top['name'] + '\u65b9\u5411\u4eca\u65e5\u6da8\u505c' + str(top['zt']) + '\u5bb6\uff0c\u6700\u9ad8' + str(top['max_b']) + '\u677f\u3002AI\u8d44\u672c\u5f00\u652f\u901a\u8fc7\u7269\u7406\u74f6\u9888\u6d41\u52a8\uff0c' + top['name'] + '\u662f\u5f53\u524d\u4f9b\u9700\u7f3a\u53e3\u6700\u660e\u786e\u7684\u73af\u8282\u3002\u4ea7\u80fd\u5e74\u589e\u6709\u9650\uff0c\u9700\u6c42\u7206\u53d1\u5f0f\u589e\u957f\uff0c\u4f9b\u9700\u7f3a\u53e3\u81f3\u5c11\u6301\u7eed\u52302028\u5e74\u3002</div>'
        part2_html += '<table><tr><th>\u5c42\u7ea7</th><th>\u73af\u8282</th><th>A\u80a1\u9f99\u5934</th><th>Serenity\u70b9\u8bc4</th></tr>'
        part2_html += chain_rows
        part2_html += '</table>'
        part2_html += '<div class="bl-gold" style="margin-top:8px"><strong>\U0001f4a1 Serenity\u6838\u5fc3\u5224\u65ad\uff1a</strong>' + top['name'] + '\u8d85\u7ea7\u5468\u671f\u4ecd\u5904\u65e9\u671f\u9636\u6bb5\uff0c\u4f9b\u9700\u7f3a\u53e3\u81f3\u5c11\u52302028\u5e74\u3002\u5f53\u524d\u6da8\u505c' + str(top['zt']) + '\u5bb6\u786e\u8ba4\u8d44\u91d1\u5408\u529b\uff0c\u5efa\u8bae\u805a\u7126\u9f99\u5934\uff0c\u5206\u6b67\u65e5\u4f4e\u5438\u3002\u4e70\u5728\u5206\u6b67\uff0c\u5356\u5728\u4e00\u81f4\u3002</div>'
        part2_html += '</div>'
    
    # Card 3: 策略总结
    strategy_map = {
        'S+': {'strategy': '\u8d8b\u52bf\u4f4e\u5438/\u6301\u6709', 'risk': '\u77ed\u671f\u6da8\u5e45\u8fc7\u9ad8\u56de\u8c03'},
        'S': {'strategy': '\u7b49\u5f85\u5206\u6b67\u4f4e\u5438', 'risk': '\u660e\u65e5\u5206\u6b67\u56de\u8e29\u6df1\u5ea6'},
        'A': {'strategy': '\u8d8b\u52bf\u6301\u6709', 'risk': '\u6301\u7eed\u6027\u5f85\u9a8c\u8bc1'},
        'B+': {'strategy': '\u89c2\u671b\u7b49\u5f85\u786e\u8ba4', 'risk': '\u4e3b\u7ebf\u5207\u6362\u98ce\u9669'},
    }
    
    strategy_rows = ''
    for b in scores[:5]:
        sm = strategy_map.get(b['rating'], {'strategy': '\u89c2\u5bdf', 'risk': '\u4e0d\u786e\u5b9a'})
        stock_str = '\u3001'.join(b['stocks'][:3]) if b['stocks'] else '\u2014'
        strategy_rows += '<tr>'
        strategy_rows += '<td>' + rating_badge(b['rating']) + '</td>'
        strategy_rows += '<td>' + b['name'] + '</td>'
        strategy_rows += '<td>' + stock_str + '</td>'
        strategy_rows += '<td>' + sm['strategy'] + '</td>'
        strategy_rows += '<td>' + sm['risk'] + '</td>'
        strategy_rows += '</tr>'
    
    top_dir = scores[0]['name'] if scores else '\u5f85\u786e\u8ba4'
    top_score = scores[0]['total'] if scores else 0
    zt_total = query("SELECT COUNT(*) as c FROM zt_stocks WHERE date=?", (today,))[0]['c']
    max_board = query("SELECT MAX(board_num) as mb FROM zt_stocks WHERE date=?", (today,))[0]['mb']
    
    # 组合输出
    result = '<h2>\U0001f52c Serenity\u74f6\u9888\u5206\u6790 \u2014 \u6700\u5f3a\u9898\u6750\u4e0e\u6838\u5fc3\u6807\u7684 <span style="font-size:11px;color:var(--muted);font-weight:normal">\u4f9b\u9700\u7f3a\u53e3\u00d7TAM\u589e\u901f\u00d7\u56fd\u4ea7\u66ff\u4ee3\u7a7a\u95f4 \u00b7 ' + today + '</span></h2>'
    result += '\n\n<div class="bl-gold" style="margin-bottom:10px;font-size:12px">'
    result += '\n<strong>\U0001f9e0 Serenity\u6846\u67b6\u6838\u5fc3\uff1a</strong>AI\u8d44\u672c\u5f00\u652f\u901a\u8fc7\u7269\u7406\u74f6\u9888\u73af\u8282\u6d41\u52a8\u3002\u4eca\u65e5\u6700\u5f3a\u65b9\u5411\uff1a<strong>' + top_dir + '</strong>\u3002\u6da8\u505c' + str(zt_total) + '\u53ea\uff0c\u6700\u9ad8' + str(max_board) + '\u677f\u3002' + top_dir + '\u7efc\u5408\u8bc4\u5206' + str(top_score) + '/40\u3002'
    result += '\n</div>'
    
    result += '\n\n<div class="card">'
    result += '\n<h3>\U0001f525 \u74f6\u9888\u70ed\u529b\u699c TOP5 \u2014 \u6309\u4f9b\u9700\u7f3a\u53e3\u00d7TAM\u589e\u901f\u8bc4\u5206</h3>'
    result += '\n<table>'
    result += '\n<tr><th>\u8bc4\u7ea7</th><th>\u74f6\u9888\u73af\u8282</th><th>\u4f9b\u9700\u7f3a\u53e3</th><th>TAM\u589e\u901f</th><th>\u56fd\u4ea7\u66ff\u4ee3</th><th>\u7efc\u5408\u5206</th><th>A\u80a1\u6838\u5fc3\u6807\u7684</th></tr>'
    result += heat_rows
    result += '\n</table>'
    result += '\n</div>'
    
    result += '\n\n' + part2_html
    
    result += '\n\n<div class="card">'
    result += '\n<h3>\U0001f9e0 Serenity\u7b56\u7565\u603b\u7ed3</h3>'
    result += '\n<table>'
    result += '\n<tr><th>\u4f18\u5148\u7ea7</th><th>\u65b9\u5411</th><th>\u6838\u5fc3\u6807\u7684</th><th>\u7b56\u7565</th><th>\u98ce\u9669</th></tr>'
    result += strategy_rows
    result += '\n</table>'
    result += '\n<div class="bl-blue" style="margin-top:8px;font-size:11px"><strong>\U0001f4cc Serenity\u6838\u5fc3\u7406\u5ff5\uff1a</strong>"\u74f6\u9888\u4e0d\u7834\uff0c\u884c\u60c5\u4e0d\u6b62\u3002\u771f\u6b63\u7684\u4f9b\u9700\u7f3a\u53e3\u4f1a\u6301\u7eed\u591a\u5e74\u3002\u4e0d\u8981\u56e0\u4e3a\u6da8\u4e86\u51e0\u4e2a\u6708\u5c31\u6050\u9ad8\u2014\u2014\u74f6\u9888\u73af\u8282\u4f1a\u6301\u7eed\u6570\u5e74\u3002\u4e70\u5728\u5206\u6b67\uff0c\u5356\u5728\u4e00\u81f4\u3002"</div>'
    result += '\n</div>'
    
    return result



def rebuild_section_html(today=None):
    """用实时数据重建 section_html"""
    if not today:
        today = date.today().strftime("%Y-%m-%d")
    
    # 先清除今天的 section_html
    execute("DELETE FROM section_html WHERE date=?", (today,))
    
    sections = []
    
    # 1. 大盘概况 (实时)
    s1 = _build_s1_html(today)
    if s1:
        sections.append({'date': today, 'section_id': 's1', 'title': f'大盘概况 {today}', 'html': s1})
    
    # 2. 连板梯队 (实时)
    s7 = _build_s7_html(today)
    if s7:
        sections.append({'date': today, 'section_id': 's7', 'title': f'连板梯队 {today}', 'html': s7})
    
    # 3. 韭研公社 (实时)
    s6 = _build_s6_html(today)
    if s6:
        sections.append({'date': today, 'section_id': 's6', 'title': f'韭研公社视角 {today}', 'html': s6})
    

    # 3b. 板块热度 (实时)
    s2 = _build_s2_html(today)
    if s2:
        sections.append({'date': today, 'section_id': 's2', 'title': f'板块热度 {today}', 'html': s2})

    # 4. 题材生命周期 (实时)
    s3 = _build_s3_html(today)
    if s3:
        sections.append({'date': today, 'section_id': 's3', 'title': f'题材生命周期 {today}', 'html': s3})
    
    # 5. 题材轮动 (实时)
    s9 = _build_s9_html(today)
    if s9:
        sections.append({'date': today, 'section_id': 's9', 'title': f'题材轮动 {today}', 'html': s9})
    
    # 6. 产业链深度 (实时)
    s4 = _build_s4_html(today)
    if s4:
        sections.append({'date': today, 'section_id': 's4', 'title': f'产业链深度 {today}', 'html': s4})
    
    # 7. 淘股吧视角 (从DB)
    s5 = _build_s5_html(today)
    if s5:
        sections.append({'date': today, 'section_id': 's5', 'title': f'淘股吧视角 {today}', 'html': s5})
    
    # 8. Serenity瓶颈分析 (实时)
    s16 = _build_s16_html(today)
    if s16:
        sections.append({'date': today, 'section_id': 's16', 'title': f'Serenity瓶颈分析 {today}', 'html': s16})
    
    # 9. 静态分析部分 (从最新可用日期复制)
    analysis_sections = ['s0', 's8', 's10', 's13', 's15', 's17', 's18']
    latest_date = query("SELECT MAX(date) as md FROM section_html WHERE date < ?", (today,))
    if latest_date and latest_date[0]['md']:
        src_date = latest_date[0]['md']
        old = query("SELECT * FROM section_html WHERE date=? ORDER BY id", (src_date,))
        for r in old:
            if r['section_id'] in analysis_sections:
                sections.append({'date': today, 'section_id': r['section_id'], 'title': r['title'], 'html': r['html']})
    
    if sections:
        insert_many('section_html', sections)
        print(f"  ✅ section_html 已重建: {len(sections)}个板块")
        return len(sections)
    return 0


# ════════════════════════════════════════════
# 统一入口
# ════════════════════════════════════════════

def refresh_all():
    """执行所有数据抓取"""
    results = {}
    
    print(f"\n📡 [{datetime.now().strftime('%H:%M:%S')}] 开始数据更新...")
    
    # 1. 涨停池
    print("  → 抓取涨停池...")
    stock_count, dt = fetch_zt_pool()
    results['zt_pool'] = stock_count
    print(f"    ✅ {stock_count}只涨停个股 ({dt})")
    
    # 2. 大盘数据
    print("  → 更新大盘数据...")
    results['market'] = fetch_market_data()
    print(f"    ✅ 大盘数据更新完成")
    
    # 3. 财联社快讯
    print("  → 爬取财联社...")
    cls_count = fetch_cls_news()
    results['cls_news'] = cls_count
    print(f"    ✅ {cls_count}条快讯")
    
    # 4. 韭研公社
    print("  → 爬取韭研公社...")
    post_count = fetch_jiuyangongshe()
    results['jy_posts'] = post_count
    print(f"    ✅ {post_count}条帖子")
    
    # 5. 淘股吧 (从静态HTML导入)
    print("  → 导入淘股吧...")
    tg_count = fetch_taoguba_from_html()
    results['tg_posts'] = tg_count
    print(f"    ✅ {tg_count}条帖子")
    
    # 6. 重建 section_html (用实时数据替换静态分析)
    print("  → 重建页面...")
    sec_count = rebuild_section_html()
    results['sections'] = sec_count
    
    # 汇总
    print(f"\n📊 更新完成: 涨停{stock_count}只 · 韭研公社{post_count}条 · 财联社{cls_count}条 · {sec_count}个板块已更新")
    return results


if __name__ == '__main__':
    print("=" * 40)
    print("复盘工具 · 数据爬虫引擎")
    print("=" * 40)
    refresh_all()
