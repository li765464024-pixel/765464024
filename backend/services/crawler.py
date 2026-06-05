"""
数据爬虫引擎 — 自动抓取各大平台数据
"""
import re
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
            rows += f'''<tr data-sort-price="{p}" data-sort-time="{t}" data-sort-reason="{reason}" data-sort-limit="{s['seal_amount'] or 0}" data-sort-sector="{sector}" data-sort-turnover="{s['turnovers'] or 0}">
<td>{name}<br><span style="font-size:10px;color:var(--muted)">{code}</span></td>
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
    
    def tab_label(tab_name, label, cnt, active=False):
        act = ' active' if active else ''
        return f'<div class="board-tab{act}" onclick="switchBoardTab(\'{tab_name}\')" data-board="{tab_name}">{label}板（{cnt}）</div>'
    
    def rate_label(from_name, to_name, rate, cnt_from, cnt_to):
        """晋级率文本: 一→二 7/70=10.0%"""
        if cnt_from == 0:
            return f'{from_name}→{to_name}: -'
        pct = f'{rate:.1f}%' if rate > 0 else '0%'
        return f'{from_name}→{to_name}: {cnt_to}/{cnt_from}={pct}'
    
    cnt1, cnt2, cnt3, cnt4, cnt5 = [len(boards[b]) for b in [1, 2, 3, 4, 5]]
    
    rate_1_2 = cnt2 / cnt1 * 100 if cnt1 > 0 else 0
    rate_2_3 = cnt3 / cnt2 * 100 if cnt2 > 0 else 0
    rate_3_4 = cnt4 / cnt3 * 100 if cnt3 > 0 else 0
    rate_4_5 = cnt5 / cnt4 * 100 if cnt4 > 0 else 0
    
    rates_str = f'{rate_label("一","二",rate_1_2,cnt1,cnt2)} | {rate_label("二","三",rate_2_3,cnt2,cnt3)} | {rate_label("三","四",rate_3_4,cnt3,cnt4)} | {rate_label("四","五",rate_4_5,cnt4,cnt5)}'
    
    board_tabs = ''
    board_tabs += tab_label('one', '一', cnt1, active=True)
    board_tabs += tab_label('two', '二', cnt2)
    board_tabs += tab_label('three', '三', cnt3)
    board_tabs += tab_label('four', '四', cnt4)
    higher_cnt = cnt5
    board_tabs += f'<div class="board-tab" onclick="switchBoardTab(\'higher\')" data-board="higher">更高（{higher_cnt}）</div>'
    board_tabs += f'<div class="board-tab" style="margin-left:auto;background:rgba(210,153,29,.1);border-color:var(--gold);color:var(--gold);cursor:default;font-size:11px" title="今日晋级率(上板数/基数)">{rates_str}</div>'
    
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
    
    # 4. 静态分析部分 (从最新可用日期复制)
    analysis_sections = ['s0', 's2', 's3', 's4', 's5', 's8', 's9', 's10', 's13', 's15', 's16', 's17', 's18']
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
    
    # 3. 韭研公社
    print("  → 爬取韭研公社...")
    post_count = fetch_jiuyangongshe()
    results['jy_posts'] = post_count
    print(f"    ✅ {post_count}条帖子")
    
    # 4. 重建 section_html (用实时数据替换静态分析)
    print("  → 重建页面...")
    sec_count = rebuild_section_html()
    results['sections'] = sec_count
    
    # 汇总
    print(f"\n📊 更新完成: 涨停{stock_count}只 · 韭研公社{post_count}条 · {sec_count}个板块已更新")
    return results


if __name__ == '__main__':
    print("=" * 40)
    print("复盘工具 · 数据爬虫引擎")
    print("=" * 40)
    refresh_all()
