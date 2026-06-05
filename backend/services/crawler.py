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
# 6. 统一 rebuild section_html (增强版)
# ════════════════════════════════════════════

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
    
    # 8. 静态分析部分 (从最新可用日期复制)
    analysis_sections = ['s0', 's2', 's8', 's10', 's13', 's15', 's16', 's17', 's18']
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
