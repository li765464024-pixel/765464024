"""
数据爬虫引擎 — 自动抓取各大平台数据
"""
import re
import os
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime

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
    """获取大盘概况数据"""
    try:
        # 从涨停池统计
        import akshare as ak
        today_str = TODAY.replace('-', '')
        df = ak.stock_zt_pool_em(date=today_str)
        
        zt_count = len(df) if df is not None else 0
        
        # 封板率估算
        sealed = len(df[df['炸板次数'] == 0]) if df is not None and '炸板次数' in df.columns else 0
        seal_rate = round(sealed / zt_count * 100, 1) if zt_count > 0 else 0
        
        # 板数分布
        max_board = int(df['连板数'].max()) if df is not None and '连板数' in df.columns else 0
        
        insert('market_data', {
            'date': TODAY,
            'sentiment': '分化',
            'zt_count': zt_count,
            'dt_count': 0,
            'up_count': 0,
            'down_count': 0,
            'seal_rate': seal_rate,
            'volume': '',
            'main_inflow': '',
            'max_board': max_board,
            'max_board_stocks': '',
            'temperature': 0,
        })
        return True
    except Exception as e:
        print(f"  ⚠️ 大盘数据获取失败: {e}")
        return False


# ════════════════════════════════════════════
# 4. 重建 section_html (用实时数据替换静态分析)
# ════════════════════════════════════════════

def _build_s1_html(today):
    """大盘概况 — 从 market_data 生成"""
    rows = query("SELECT * FROM market_data WHERE date=? ORDER BY id DESC LIMIT 1", (today,))
    if not rows:
        return ''
    d = rows[0]
    sentiment = d['sentiment'] or '分化'
    sc = 'gold' if sentiment == '分化' else ('red' if '强' in str(sentiment) else 'green')
    return f'''<h2>一、大盘概况 <span style="font-size:11px;color:var(--muted);font-weight:normal">{today} 实时数据</span></h2>
<div class="grid2">
<div class="stat"><div class="v" style="color:var(--{sc})">{sentiment}</div><div class="l">市场情绪</div></div>
<div class="stat"><div class="v" style="color:var(--red)">{d['zt_count'] or 0}</div><div class="l">涨停家数</div><div style="font-size:10px;color:var(--muted);margin-top:2px">东方财富数据</div></div>
<div class="stat"><div class="v" style="color:var(--green)">{d['dt_count'] or 0}</div><div class="l">跌停家数</div></div>
<div class="stat"><div class="v" style="color:var(--gold)">{fmt_percent(d['seal_rate'])}</div><div class="l">封板率</div></div>
<div class="stat"><div class="v" style="color:var(--blue)">{d['max_board'] or 0}板</div><div class="l">最高板</div></div>
<div class="stat"><div class="v" style="color:var(--red)">{d['up_count'] or '-'}</div><div class="l">上涨家数</div></div>
<div class="stat"><div class="v" style="color:var(--green)">{d['down_count'] or '-'}</div><div class="l">下跌家数</div></div>
</div>'''

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
    """韭研公社 — 从 posts 表生成"""
    rows = query("SELECT * FROM posts WHERE platform='jy' AND date=? ORDER BY id DESC LIMIT 20", (today,))
    if not rows:
        return ''
    bullish = sum(1 for r in rows if r['direction'] == '看多')
    bearish = sum(1 for r in rows if r['direction'] == '看空')
    neutral = sum(1 for r in rows if r['direction'] in ('', '中性'))
    
    cards = ''
    for r in rows:
        title = (r['title'] or '')[:80].replace('<', '&lt;').replace('>', '&gt;')
        content = (r['content'] or '')[:300].replace('<', '&lt;').replace('>', '&gt;')
        author = (r['author'] or '').replace('<', '&lt;').replace('>', '&gt;')
        dir_tag = 'r' if r['direction'] == '看多' else ('g' if r['direction'] == '看空' else 'b')
        cards += f'''<div class="card">
<h3>{title} <span class="tag {dir_tag}">{r['direction'] or '中性'}</span></h3>
<div class="bl-gold" style="font-size:12px">{content}</div>
<div style="font-size:11px;color:var(--muted);margin-top:6px">✍️ {author} · 实时爬取</div>
</div>'''
    
    return f'''<h2>🔬 韭研公社视角 <span style="font-size:11px;color:var(--muted);font-weight:normal">实时爬取 · {today}</span></h2>
<div class="grid2" style="margin-bottom:12px">
<div class="stat"><div class="v" style="color:var(--red)">{bullish}看多</div></div>
<div class="stat"><div class="v" style="color:var(--green)">{bearish}看空</div></div>
<div class="stat"><div class="v" style="color:var(--blue)">{neutral}中性</div></div>
</div>
{cards}'''

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
    analysis_sections = ['s0', 's2', 's8', 's10', 's13', 's15', 's17', 's18']
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
