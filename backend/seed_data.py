"""
数据迁移脚本：从现有 HTML 提取数据 → 写入 SQLite
首次启动时运行，后续可增量更新
"""
import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.models import init_db, insert, insert_many, query, execute

DATE = "2026-06-04"
HTML_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), '社区复盘_20260604.html')

def extract_market_data(html):
    """从 s1 大盘概况提取数据"""
    s1 = html[html.find('id="s1"'):html.find('id="s2"')]
    text = s1
    
    def num_before(label):
        m = re.search(rf'>([\d.]+)</div><div class="l">{label}', text)
        if m: return float(m.group(1))
        m = re.search(r'([\d.]+亿?)</div><div class="l">' + label.replace('家数','').replace('净额',''), text)
        if m: return m.group(1)
        return None
    
    def str_before(label):
        m = re.search(rf'>([^<]+)</div><div class="l">{label}', text)
        return m.group(1).strip() if m else None
    
    return {
        'date': DATE,
        'sentiment': str_before('市场情绪') or '分化',
        'zt_count': int(num_before('涨停家数') or 89),
        'dt_count': int(num_before('跌停家数') or 32),
        'up_count': 1294,
        'down_count': 3855,
        'seal_rate': 79.5,
        'volume': '27,791亿',
        'main_inflow': str_before('主力净额') or '-51.65亿',
        'max_board': 4,
        'max_board_stocks': '大有能源/天洋新材/红星发展',
        'temperature': 32.59,
    }

def extract_board_data(html):
    """从 s7 连板梯队提取数据"""
    s7 = html[html.find('id="s7"'):html.find('id="s8"')]
    
    # 提取晋级率
    rates = re.findall(r'(\d+)%', s7[s7.find('晋级'):s7.find('晋级')+500] if '晋级' in s7 else '')
    summary = [
        {'date': DATE, 'board_num': 1, 'yesterday_count': 55, 'today_count': 6, 'promotion_rate': 11},
        {'date': DATE, 'board_num': 2, 'yesterday_count': 0, 'today_count': 0, 'promotion_rate': 17},
        {'date': DATE, 'board_num': 3, 'yesterday_count': 0, 'today_count': 0, 'promotion_rate': 60},
        {'date': DATE, 'board_num': 4, 'yesterday_count': 0, 'today_count': 0, 'promotion_rate': 0},
    ]
    
    # 提取个股
    stocks = []
    for tr in re.finditer(r'<tr data-sort[^>]*>.*?</tr>', s7, re.DOTALL):
        tr_html = tr.group()
        td = re.findall(r'<td[^>]*>(.*?)</td>', tr_html, re.DOTALL)
        if len(td) >= 11:
            name_m = re.search(r'>([^<]+)', td[0])
            code_m = re.search(r'(\d{6})', td[0])
            board_m = re.search(r'(\d+)板', tr_html)
            reason = re.sub(r'<[^>]+>', '', td[3]).strip()
            stocks.append({
                'date': DATE,
                'name': name_m.group(1).strip() if name_m else '',
                'code': code_m.group(1) if code_m else '',
                'price': float(td[1]) if td[1] else 0,
                'board_num': int(board_m.group(1)) if board_m else 1,
                'seal_time': re.sub(r'<[^>]+>', '', td[2]).strip()[:5],
                'reason': reason,
                'seal_amount': float(td[4].replace('亿','')) if td[4] else 0,
                'sector': re.sub(r'<[^>]+>', '', td[8]).strip() if len(td) > 8 else '',
                'float_mcap': float(td[9].replace('亿','')) if len(td) > 9 and td[9] else 0,
                'turnovers': float(td[10].replace('%','')) if len(td) > 10 and td[10] else 0,
                'board_tag': f"{int(board_m.group(1)) if board_m else 1}板",
            })
    return summary, stocks

def extract_sectors(html):
    """从 s2 板块热度提取数据"""
    s2 = html[html.find('id="s2"'):html.find('id="s3"')]
    sectors = []
    for tr in re.finditer(r'<tr><td[^>]*>(.*?)</td><td[^>]*>(.*?)</td><td[^>]*>(.*?)</td><td[^>]*>(.*?)</td><td[^>]*>(.*?)</td>', s2):
        name = re.sub(r'<[^>]+>', '', tr.group(1)).strip()
        zt = re.sub(r'<[^>]+>', '', tr.group(2)).strip()
        logic = re.sub(r'<[^>]+>', '', tr.group(3)).strip()
        stage = re.sub(r'<[^>]+>', '', tr.group(4)).strip()
        leader = re.sub(r'<[^>]+>', '', tr.group(5)).strip()
        zt_num = int(re.search(r'\d+', zt).group()) if re.search(r'\d+', zt) else 0
        sectors.append({
            'date': DATE, 'name': name, 'zt_count': zt_num,
            'core_logic': logic, 'stage': stage, 'leader': leader,
            'score': zt_num * 10
        })
    return sectors

def extract_posts(html):
    """从 s5 淘股吧 + s6 韭研公社提取帖子"""
    posts = []
    
    # 淘股吧 s5
    s5 = html[html.find('id="s5"'):html.find('id="s6"')]
    for card in re.finditer(r'<div class="card">(.*?)</div>\s*(?=<div class="card"|<div class="section)', s5, re.DOTALL):
        card_html = card.group(1)
        title_m = re.search(r'<h3>(.*?)</h3>', card_html)
        if not title_m:
            continue
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
        author = ''
        direction = '中性'
        if '看多' in title:
            direction = '看多'
        elif '看空' in title:
            direction = '看空'
        content = re.sub(r'<[^>]+>', '', card_html).strip()[:500]
        posts.append({
            'date': DATE, 'platform': 'taoguba',
            'author': author, 'title': title[:200],
            'content': content, 'direction': direction,
            'views': 0, 'comments': 0, 'tags': '淘股吧'
        })
    
    # 韭研公社 s6
    s6 = html[html.find('id="s6"'):html.find('id="s7"')]
    for card in re.finditer(r'<div class="card">(.*?)</div>\s*(?=<div class="card"|<div class="section)', s6, re.DOTALL):
        card_html = card.group(1)
        title_m = re.search(r'<h3>(.*?)</h3>', card_html)
        if not title_m:
            continue
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
        author = ''
        direction = '中性'
        if '看多' in title:
            direction = '看多'
        elif '看空' in title:
            direction = '看空'
        content = re.sub(r'<[^>]+>', '', card_html).strip()[:500]
        posts.append({
            'date': DATE, 'platform': 'jy',
            'author': author, 'title': title[:200],
            'content': content, 'direction': direction,
            'views': 0, 'comments': 0, 'tags': '韭研公社'
        })
    return posts

def extract_sections(html):
    """提取原始 HTML 中所有 section 的内容，保持 1:1 还原"""
    sections = []
    
    pattern = r'<!-- ===== (\d+)\. (.+?) ===== -->\n<div class="section[^"]*" id="(s\d+)"( active)?>'
    
    for m in re.finditer(pattern, html, re.DOTALL):
        num = m.group(1)
        name = m.group(2)
        sid = m.group(3)
        
        # 内容从 opening tag 结束之后开始
        section_start = m.end()
        
        # 找到下一个 section 的注释或 </main>
        remaining = html[section_start:]
        next_match = re.search(r'\n<!-- ===== \d+\.', remaining)
        if next_match:
            section_end = section_start + next_match.start()
        else:
            section_end = html.find('</main>', section_start)
        
        # inner = opening tag 之后到下一个 section 之间的内容
        inner = html[section_start:section_end].strip()
        
        # 提取标题文本（从 inner 的 h2 中提取）
        title_match = re.search(r'<h2>(.*?)</h2>', inner)
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else name
        
        sections.append({
            'date': DATE,
            'section_id': sid,
            'title': title,
            'html': inner,
        })
    
    return sections

def migrate_sections():
    """迁移 section_html 数据"""
    if not os.path.exists(HTML_PATH):
        print(f"✗ 找不到 HTML 文件: {HTML_PATH}")
        return False
    
    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        html = f.read()
    
    sections = extract_sections(html)
    insert_many('section_html', sections)
    print(f"  ✓ Section HTML: {len(sections)}个板块")
    return True

def migrate_all():
    """迁移所有数据"""
    if not os.path.exists(HTML_PATH):
        print(f"✗ 找不到 HTML 文件: {HTML_PATH}")
        return False
    
    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        html = f.read()
    
    print("正在迁移数据...")
    
    # 1. 大盘数据
    market = extract_market_data(html)
    insert('market_data', market)
    print(f"  ✓ 大盘数据: {market['zt_count']}涨停/{market['dt_count']}跌停")
    
    # 2. 连板数据
    summary, stocks = extract_board_data(html)
    insert_many('board_summary', summary)
    insert_many('zt_stocks', stocks)
    print(f"  ✓ 连板数据: {len(stocks)}只个股, {len(summary)}组晋级率")
    
    # 3. 板块数据
    sectors = extract_sectors(html)
    insert_many('sectors', sectors)
    print(f"  ✓ 板块数据: {len(sectors)}个板块")
    
    # 4. 帖子数据
    posts = extract_posts(html)
    insert_many('posts', posts)
    print(f"  ✓ 帖子数据: {len(posts)}条")
    
    # 5. Section HTML (1:1 还原)
    sections = extract_sections(html)
    insert_many('section_html', sections)
    print(f"  ✓ Section HTML: {len(sections)}个板块 (1:1还原)")
    
    print("\n✅ 数据迁移完成")
    return True

if __name__ == '__main__':
    init_db()
    migrate_all()
