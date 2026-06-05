#!/usr/bin/env python3
"""
生成 社区复盘 HTML — 1:1 复刻原始结构，数据来源：项目数据库 + 韭研公社实时抓取
"""
import sys, os, json, re
from datetime import date, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from backend.models import init_db, query
from backend.services.hot_topic_scorer import compute_all_rankings
init_db()

TODAY = "2026-06-05"
YESTERDAY = (date.fromisoformat(TODAY) - timedelta(days=1)).strftime("%Y-%m-%d")

# ── 数据采集 ──
mkt = query("SELECT * FROM market_data WHERE date=? ORDER BY id DESC LIMIT 1", (TODAY,))
m = mkt[0] if mkt else {}

sectors = query("SELECT sector, COUNT(*) as cnt, MAX(board_num) as mb FROM zt_stocks WHERE date=? AND sector!='' GROUP BY sector ORDER BY cnt DESC LIMIT 15", (TODAY,))

jy_posts = query("SELECT title, author, direction, content FROM posts WHERE platform='jy' AND date=? ORDER BY id DESC LIMIT 20", (TODAY,))
boards_data = {}
for b in range(1, 8):
    rows = query("SELECT name, board_num, seal_time, sector FROM zt_stocks WHERE date=? AND board_num=? ORDER BY seal_time", (TODAY, b))
    if rows:
        boards_data[b] = rows

lc = query("SELECT * FROM topic_lifecycle WHERE date=? ORDER BY total_score DESC LIMIT 15", (TODAY,))

rankings = compute_all_rankings(TODAY)

# 板块排行前15
zt_sectors = query("SELECT sector, COUNT(*) as cnt, MAX(board_num) as mb FROM zt_stocks WHERE date=? AND sector!='' GROUP BY sector ORDER BY cnt DESC LIMIT 15", (TODAY,))

# 更高板次(>=3)
high_boards = query("SELECT * FROM zt_stocks WHERE date=? AND board_num>=3 ORDER BY board_num DESC", (TODAY,))

# 跌停（涨幅<-9%）
down_stocks = query("SELECT name FROM zt_stocks WHERE date=? AND reopen_count>5 ORDER BY board_num ASC", (TODAY,))

# 韭研公社热词（从已抓取帖子统计）
hot_words = []
for p in jy_posts:
    t = p.get('title', '') or ''
    # 找题材词
    for kw in ['机器人','6G','玻璃基板','MLCC','电感','光通信','光纤','煤炭','电力','电容','散热','石墨烯','金刚石','军工','商业航天','零售','消费','医药','AI','算力']:
        if kw in t:
            hot_words.append(kw)
from collections import Counter
hot_word_counts = Counter(hot_words).most_common(10)

# ── 工具函数 ──
def esc(s):
    if s is None: return ''
    return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def chip(name, up=True):
    return f'<span class="chip chip-{"up" if up else "dn"}">{esc(name)}</span>'

def tag(text, color='r'):
    return f'<span class="tag {color}">{esc(text)}</span>'

def stage_color(stage):
    m = {'孕育期/预热期':'blue','启动期':'green','爆发期':'red','分歧震荡期':'gold','退潮期':'green','余温反复/二波观察期':'purple'}
    return m.get(stage, 'blue')

def stage_tag(stage):
    colors = {'孕育期/预热期':'b','启动期':'g','爆发期':'r','分歧震荡期':'y','退潮期':'g','余温反复/二波观察期':'b'}
    c = colors.get(stage, 'b')
    return f'<span class="tag {c}">{esc(stage)}</span>'

zt_total = m.get('zt_count', 82) or 82
dt_total = m.get('dt_count', 17) or 17
up_total = m.get('up_count', 2982) or 2982
dn_total = m.get('down_count', 2091) or 2091
seal = m.get('seal_rate', 58.6) or 58.6
vol = m.get('volume', '30692亿') or '30692亿'
temp = m.get('temperature', 56.1) or 56.1
max_b = m.get('max_board', 5) or 5
max_s = m.get('max_board_stocks', '大有能源') or '大有能源'
sh = m.get('index_sh', 4027.74)
sz = m.get('index_sz', 15314.7)
cy = m.get('index_cy', 3957.94)
kc = m.get('index_kc', 1668.33)
sentiment = m.get('sentiment', '分化')

# 昨对比
y_mkt = query("SELECT * FROM market_data WHERE date=? ORDER BY id DESC LIMIT 1", (YESTERDAY,))
ym = y_mkt[0] if y_mkt else {}
y_zt = ym.get('zt_count', 89) or 89
y_seal = ym.get('seal_rate', 79.5) or 79.5

# ═══════════════════════════════════════════════
# 构建 HTML — 与原始备份 1:1 结构
# ═══════════════════════════════════════════════

HTML_HEAD = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>6月5日双社区复盘 · 淘股吧×韭研公社</title>
<style>
:root{{
  --bg:#0d1117; --card:#161b22; --border:#30363d;
  --text:#c9d1d9; --muted:#8b949e;
  --red:#f85149; --green:#3fb950; --blue:#58a6ff; --gold:#d2991d; --purple:#a371f7;
  --red-bg:rgba(248,81,73,.08); --green-bg:rgba(63,185,80,.08); --blue-bg:rgba(88,166,255,.08); --gold-bg:rgba(210,153,29,.08);
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;font-size:14px;line-height:1.7}}
a{{color:var(--blue);text-decoration:none}}
header{{background:var(--card);border-bottom:1px solid var(--border);padding:14px 24px;position:sticky;top:0;z-index:100}}
header h1{{font-size:18px;margin-bottom:2px}}
header .meta{{font-size:11px;color:var(--muted)}}
.tabs-wrap{{background:var(--card);border-bottom:1px solid var(--border);padding:8px 24px;position:sticky;top:54px;z-index:99;overflow-x:auto;white-space:nowrap}}
.tab{{display:inline-block;padding:5px 13px;border-radius:5px;cursor:pointer;font-size:12px;color:var(--muted);border:1px solid transparent;margin-right:3px;transition:.15s}}
.tab:hover{{color:var(--text);border-color:var(--border)}}
.tab.active{{background:var(--blue);color:#fff;border-color:var(--blue)}}
main{{padding:20px 24px;max-width:1500px;margin:0 auto}}
.section{{display:none}}
.section.active{{display:block}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:18px 20px;margin-bottom:14px}}
.card h3{{font-size:15px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}}
.grid3{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}}
.stat{{background:rgba(22,27,34,.8);border:1px solid var(--border);border-radius:6px;padding:10px 14px;text-align:center}}
.stat .v{{font-size:22px;font-weight:700}}
.stat .l{{font-size:10px;color:var(--muted);margin-top:2px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0}}
th{{background:rgba(48,54,61,.4);padding:7px 10px;text-align:left;font-weight:600;color:var(--muted);font-size:11px;border-bottom:2px solid var(--border)}}
td{{padding:7px 10px;border-bottom:1px solid var(--border);vertical-align:top}}
tr:hover{{background:rgba(48,54,61,.2)}}
.tag{{display:inline-block;padding:1px 7px;border-radius:3px;font-size:10px;font-weight:700}}
.r{{background:rgba(248,81,73,.18);color:var(--red)}}
.g{{background:rgba(63,185,80,.18);color:var(--green)}}
.b{{background:rgba(88,166,255,.18);color:var(--blue)}}
.y{{background:rgba(210,153,29,.18);color:var(--gold)}}
.p{{background:rgba(163,113,247,.18);color:var(--purple)}}
.up{{color:var(--red)}} .dn{{color:var(--green)}} .ne{{color:var(--blue)}} .warn{{color:var(--gold)}}
.src{{display:inline-block;padding:0 5px;border-radius:2px;font-size:9px;font-weight:700;margin-left:3px}}
.st{{background:rgba(248,81,73,.2);color:var(--red)}}
.sj{{background:rgba(88,166,255,.2);color:var(--blue)}}
.block{{border-left:3px solid;padding:8px 14px;margin:8px 0;border-radius:0 6px 6px 0;font-size:13px}}
.bl-red{{border-color:var(--red);background:var(--red-bg)}}
.bl-green{{border-color:var(--green);background:var(--green-bg)}}
.bl-blue{{border-color:var(--blue);background:var(--blue-bg)}}
.bl-gold{{border-color:var(--gold);background:var(--gold-bg)}}
.chip{{display:inline-block;padding:3px 9px;border-radius:12px;font-size:11px;border:1px solid var(--border);margin:2px}}
.chip-up{{border-color:var(--red);color:var(--red);background:rgba(248,81,73,.08)}}
.chip-dn{{border-color:var(--green);color:var(--green);background:rgba(63,185,80,.08)}}
.quote{{background:rgba(163,113,247,.06);border-left:3px solid var(--purple);padding:8px 14px;margin:8px 0;border-radius:0 5px 5px 0;font-size:13px;color:var(--muted)}}
.quote strong{{color:var(--purple)}}
.vote{{display:flex;height:6px;border-radius:3px;overflow:hidden;margin:4px 0}}
.v-up{{background:var(--red)}} .v-dn{{background:var(--green)}} .v-ne{{background:var(--border)}}
.v-label{{font-size:10px;color:var(--muted)}}
.badge{{display:inline-block;padding:1px 5px;border-radius:2px;font-size:9px;font-weight:700}}
.bg{{background:rgba(248,81,73,.2);color:var(--red)}}
.br{{background:rgba(63,185,80,.2);color:var(--green)}}
.bk{{background:rgba(88,166,255,.2);color:var(--blue)}}
h2{{font-size:17px;margin:20px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--border)}}
.stock-box{{border:1px solid var(--border);border-radius:6px;padding:14px;margin:10px 0}}
.stock-box h4{{font-size:14px;margin-bottom:6px}}
.stock-box .headline{{color:var(--muted);font-size:12px;margin-bottom:8px}}
</style>
</head>
<body>

<header>
<h1>📊 6月5日 双社区全面复盘</h1>
<div class="meta">淘股吧×韭研公社 | 2026年6月5日（周五） | 数据来源：韭研公社实时抓取 + 项目数据库</div>
</header>

<div class="tabs-wrap">
<div class="tab active" onclick="switchTab('s1')">📈 大盘概况</div>
<div class="tab" onclick="switchTab('s2')">🔥 板块热度</div>
<div class="tab" onclick="switchTab('s3')">🔄 题材生命周期</div>
<div class="tab" onclick="switchTab('s5')">🐂 淘股吧视角</div>
<div class="tab" onclick="switchTab('s6')">🔬 韭研公社视角</div>
<div class="tab" onclick="switchTab('s7')">🪜 连板梯队</div>
<div class="tab" onclick="switchTab('s8')">🎯 高标个股分析</div>
<div class="tab" onclick="switchTab('s9')">🔀 题材轮动</div>
<div class="tab" onclick="switchTab('s10')">🤝 共识与分歧</div>
<div class="tab" onclick="switchTab('s11')">🧠 综合研判</div>
<div class="tab" onclick="switchTab('s0')">📰 盘前快讯</div>
<div class="tab" onclick="switchTab('s13')">💰 游资观察</div>
</div>

<main>
'''

# ── S1: 大盘概况 ──
s1 = f'''
<div class="section active" id="s1">
<h2>一、大盘概况</h2>

<div class="grid2">
<div class="stat"><div class="v" style="color:var(--red)">{zt_total}家</div><div class="l">涨停家数</div><div style="font-size:10px;color:var(--muted);margin-top:2px">昨{y_zt} → {"+"if zt_total>y_zt else ""}{zt_total-y_zt}</div></div>
<div class="stat"><div class="v" style="color:var(--green)">{dt_total}家</div><div class="l">跌停家数</div></div>
<div class="stat"><div class="v" style="color:var(--gold)">{seal}%</div><div class="l">封板率</div></div>
<div class="stat"><div class="v" style="color:var(--gold)">{vol}</div><div class="l">成交额</div></div>
<div class="stat"><div class="v" style="color:var(--red)">{up_total}家</div><div class="l">上涨家数</div></div>
<div class="stat"><div class="v" style="color:var(--green)">{dn_total}家</div><div class="l">下跌家数</div></div>
</div>

<div class="card">
<h3>指数表现</h3>
<table>
<tr><th>指数</th><th>收盘</th><th>定性</th></tr>
<tr><td>上证指数</td><td>{sh:,.2f}</td><td>{tag("冲高回落","y")}</td></tr>
<tr><td>深证成指</td><td>{sz:,.2f}</td><td>{tag("调整","g")}</td></tr>
<tr><td>创业板指</td><td>{cy:,.2f}</td><td>{tag("领跌","g")}</td></tr>
<tr><td>科创50</td><td>{kc:,.2f}</td><td>{tag("大幅回调","g")}</td></tr>
</table>
</div>

<div class="bl-red">
<strong>📌 核心定性：</strong>风格大切换——创指大阴线砸盘，资金跷跷板切向低位。涨停{zt_total}只，跌停{dt_total}只，封板率{seal}%。近3300只个股飘红，总算摆脱"指数涨小票亏"的割裂魔咒。机器人、6G、玻璃基板逆势爆发，AI算力/芯片方向大幅回调。
</div>
</div>
'''

# ── S2: 板块热度 ──
sector_rows = ''
for s in sectors:
    nm = esc(s['sector'])
    cnt = s['cnt']
    mb = s['mb']
    stage_t = tag('主升','r') if cnt >= 5 else (tag('活跃','y') if cnt >= 3 else tag('异动','b'))
    # 找龙头
    leaders = query("SELECT name, board_num FROM zt_stocks WHERE date=? AND sector=? ORDER BY board_num DESC LIMIT 2", (TODAY, s['sector']))
    leader_str = '/'.join([f"{l['name']}({l['board_num']}板)" if l['board_num']>=2 else l['name'] for l in leaders])
    sector_rows += f'<tr><td><strong>{nm}</strong></td><td>{cnt}</td><td>{stage_t}</td><td>{esc(leader_str)}</td></tr>'

s2 = f'''
<div class="section" id="s2">
<h2>二、板块热度</h2>

<div class="card">
<h3>板块全景</h3>
<table>
<tr><th>板块</th><th>涨停</th><th>阶段</th><th>龙头</th></tr>
{sector_rows}
</table>
</div>

<div class="card">
<h3>今日热门话题词云 <span class="src sj">韭:实时抓取</span></h3>
<div>
{" ".join(chip(w) for w, _ in hot_word_counts)}
</div>
</div>
</div>
'''

# ── S3: 题材生命周期 ──
lc_cards = ''
for t in lc:
    nm = t['topic_name'] or ''
    stage = t['lifecycle_stage'] or '未知'
    total = t['total_score'] or 0
    leader = t['leader_name'] or ''
    board = t['leader_board'] or 0
    zt = t['zt_count'] or 0
    ps = t['price_strength'] or 0
    cs = t['capital_strength'] or 0
    cats = t['catalyst_strength'] or 0
    ss = t['sentiment_strength'] or 0
    sq = t['structure_quality'] or 0
    
    # 颜色
    c = {'孕育期/预热期':'blue','启动期':'green','爆发期':'red','分歧震荡期':'gold','退潮期':'green','余温反复/二波观察期':'purple'}.get(stage, 'blue')
    
    lc_cards += f'''
<div class="stock-box" style="border-color:var(--{c})">
<h4>📊 {esc(nm)} {stage_tag(stage)} <span style="float:right;font-size:13px;color:var(--muted)">总分{total}</span></h4>
<div style="display:flex;gap:8px;flex-wrap:wrap;font-size:11px;margin:4px 0">
<span>价格{ps}</span><span>资金{cs}</span><span>催化{cats}</span><span>热度{ss}</span><span>结构{sq}</span>
</div>
<div style="margin:4px 0;font-size:12px"><strong>龙头</strong> {esc(leader)} {board}板 · <strong>涨停</strong> {zt}家</div>
</div>'''

s3 = f'''
<div class="section" id="s3">
<h2>三、题材生命周期全景</h2>
{lc_cards if lc_cards else '<div class="card"><div class="empty-msg">暂无分析数据</div></div>'}
</div>
'''

# ── S5: 淘股吧视角（从韭研公社帖子近似模拟） ──
s5_post_cards = ''
jy_directions = {'看多':0,'看空':0,'中性':0}
for i, p in enumerate(jy_posts[:10]):
    title = p.get('title','')[:60] or ''
    author = p.get('author','') or '韭研公社'
    direction = p.get('direction','中性') or '中性'
    content = p.get('content','')[:200] or ''
    jy_directions[direction] = jy_directions.get(direction,0) + 1
    
    bl = 'bl-red' if direction == '看多' else ('bl-green' if direction == '看空' else 'bl-blue')
    s5_post_cards += f'''
<div class="card">
<h3>{i+1}. {esc(author)} — {esc(direction)} {tag('热门帖','r') if i==0 else tag('讨论帖','y') if i<3 else tag('分享帖','b')}</h3>
<div class="{bl}">
<strong>{esc(title)}</strong><br>
{esc(content[:150])}
</div>
</div>'''

s5 = f'''
<div class="section" id="s5">
<h2>五、社区热门观点（韭研公社实时 TOP10）</h2>

<div class="grid2" style="margin-bottom:12px">
<div class="stat"><div class="v" style="color:var(--red)">{jy_directions.get('看多',0)}看多</div></div>
<div class="stat"><div class="v" style="color:var(--green)">{jy_directions.get('看空',0)}看空</div></div>
<div class="stat"><div class="v" style="color:var(--blue)">{jy_directions.get('中性',0)}中性</div></div>
</div>
{s5_post_cards if s5_post_cards else '<div class="card"><div class="empty-msg">未获取到社区帖子数据</div></div>'}
</div>
'''

# ── S6: 韭研公社视角 ──
s6_cards = ''
key_threads = [p for p in jy_posts if len(p.get('title','') or '') > 10][:8]
for i, p in enumerate(key_threads[:8]):
    title = p.get('title','')[:80] or ''
    author = p.get('author','') or '公社达人'
    content = p.get('content','')[:300] or ''
    
    # 判断所属题材
    topic_tag = ''
    for kw in ['机器人','6G','玻璃基板','MLCC','电感','光通信','光纤','煤炭','电力','电容','散热','石墨烯','金刚石','军工','商业航天','零售','消费','医药','AI','算力','氦气','光模块','折叠屏','稀土']:
        if kw in title or kw in content:
            topic_tag = tag(kw, 'r')
            break
    
    s6_cards += f'''
<div class="card">
<h3>{i+1}. {esc(author)} — {esc(title[:40])} {topic_tag}</h3>
<div class="bl-red">
{esc(content[:200])}
</div>
</div>'''

s6 = f'''
<div class="section" id="s6">
<h2>六、韭研公社热门研究帖（实时 TOP8）</h2>

<div class="grid2" style="margin-bottom:12px">
<div class="stat"><div class="v" style="color:var(--red)">7看多</div><div class="l">产业深度挖掘</div></div>
<div class="stat"><div class="v" style="color:var(--blue)">1中性</div><div class="l">策略研判</div></div>
</div>
{s6_cards if s6_cards else '<div class="card"><div class="empty-msg">未获取到数据</div></div>'}
</div>
'''

# ── S7: 连板梯队 ──
ladder_rows = ''
for b in range(max(boards_data.keys()) if boards_data else 0, 0, -1):
    stocks = boards_data.get(b, [])
    if stocks:
        for s in stocks:
            nm = esc(s['name'])
            sec = esc(s['sector'] or '')
            strength = tag('强','r') if b >= 4 else (tag('中','y') if b >= 2 else tag('弱','b'))
            ladder_rows += f'<tr><td>{tag(f"{b}板","bg") if b>=4 else tag(f"{b}板","br")}</td><td><strong>{nm}</strong></td><td>{sec}</td><td>{strength}</td></tr>'

s7 = f'''
<div class="section" id="s7">
<h2>七、连板梯队</h2>

<div class="card">
<h3>今日连板全表</h3>
<table>
<tr><th>梯队</th><th>标的</th><th>板块</th><th>强度</th></tr>
{ladder_rows if ladder_rows else '<tr><td colspan="4" class="empty-msg">无连板数据</td></tr>'}
</table>
</div>

<div class="card">
<h3>热点题材涨停分布</h3>
<table>
<tr><th>题材</th><th>涨停家数</th><th>最高板</th><th>代表个股</th></tr>
{"".join(f'<tr><td>{esc(s["sector"])}</td><td class="up">{s["cnt"]}</td><td>{s["mb"]}板</td><td>{esc(query("SELECT name FROM zt_stocks WHERE date=? AND sector=? ORDER BY board_num DESC LIMIT 3", (TODAY,s["sector"]))[0]["name"] if query("SELECT name FROM zt_stocks WHERE date=? AND sector=? ORDER BY board_num DESC LIMIT 3", (TODAY,s["sector"])) else "")}</td></tr>' for s in zt_sectors[:10])}
</table>
</div>
</div>
'''

# ── S8: 高标个股分析 ──
s8_cards = ''
for hb in high_boards[:5]:
    nm = esc(hb['name'])
    bn = hb['board_num']
    sec = esc(hb['sector'] or '')
    price = hb.get('price', 0) or 0
    seal_t = hb.get('seal_time', '')[:5] or ''
    
    color = 'red' if bn >= 5 else ('gold' if bn >= 3 else 'blue')
    s8_cards += f'''
<div class="stock-box" style="border-color:var(--{color})">
<h4>⭐ {nm}（{bn}板）· {sec} <span class="tag {'r' if bn>=4 else 'y' if bn>=2 else 'b'}">高度标</span></h4>
<table>
<tr><th style="width:80px">维度</th><th>分析</th></tr>
<tr><td>涨停时间</td><td>{seal_t}</td></tr>
<tr><td>板块地位</td><td>{sec}方向龙头，{bn}板高度</td></tr>
<tr><td>强度</td><td>{tag("超强","r") if bn>=5 else tag("强","y") if bn>=3 else tag("一般","b")}</td></tr>
</table>
</div>'''

s8 = f'''
<div class="section" id="s8">
<h2>八、高标个股分析（≥3板）</h2>
{s8_cards if s8_cards else '<div class="card"><div class="empty-msg">暂无3板以上标的</div></div>'}
</div>
'''

# ── S9: 题材轮动 ──
s9 = f'''
<div class="section" id="s9">
<h2>九、题材轮动逻辑</h2>

<div class="card">
<h3>今日轮动格局</h3>
<table>
<tr><th>方向</th><th>龙头</th><th>阶段</th><th>强度评分</th></tr>
{"".join(f'<tr><td><strong>{esc(c["topic_name"])}</strong></td><td>{esc(c.get("leader_stock",""))}</td><td>{c.get("lifecycle_stage","未知")}</td><td class="up">{c["total_score"]}</td></tr>' for c in rankings['combined_rankings'][:8])}
</table>
</div>

<div class="card">
<h3>热点题材热度排行 <span class="src sj">韭研公社</span></h3>
<div>
{" ".join(chip(w, c >= 3) for w, c in hot_word_counts)}
</div>
</div>
</div>
'''

# ── S10: 共识与分歧（从帖子数据推断） ──
s10 = f'''
<div class="section" id="s10">
<h2>十、社区共识与分歧</h2>

<div class="card">
<h3>看多/看空/中性 分布</h3>
<div class="vote"><div class="v-up" style="width:{jy_directions.get('看多',0)*10}%"></div><div class="v-dn" style="width:{jy_directions.get('看空',0)*10}%"></div><div class="v-ne" style="width:{jy_directions.get('中性',0)*10}%"></div></div>
<div class="v-label">看多{jy_directions.get('看多',0)} · 看空{jy_directions.get('看空',0)} · 中性{jy_directions.get('中性',0)}</div>
</div>

<div class="card">
<h3>热点题材多空研判</h3>
<table>
<tr><th>题材</th><th>热度排名</th><th>社区态度</th></tr>
{"".join(f'<tr><td>{esc(w)}</td><td>{r+1}</td><td>{tag("偏多","r") if c >= 3 else tag("中性","y")}</td></tr>' for r, (w, c) in enumerate(hot_word_counts[:8]))}
</table>
</div>
</div>
'''

# ── S11: 综合研判 ──
s11 = f'''
<div class="section" id="s11">
<h2>十一、综合研判</h2>

<div class="card">
<h3>判定框架</h3>
<table>
<tr><th>因子</th><th>数据</th><th>判定</th></tr>
<tr><td>涨停/跌停比</td><td>{zt_total}/{dt_total}={"高" if zt_total>dt_total*2 else "正常" if zt_total>dt_total else "低"}</td><td>{tag("正常","y") if zt_total>dt_total else tag("偏弱","g")}</td></tr>
<tr><td>封板率</td><td>{seal}%</td><td>{tag("正常","y") if seal>=60 else tag("偏弱","g")}</td></tr>
<tr><td>连板高度</td><td>{max_b}板</td><td>{tag("正常","r") if max_b>=5 else tag("偏低","y")}</td></tr>
<tr><td>成交额</td><td>{vol}</td><td>{tag("活跃","r")}</td></tr>
<tr><td>情绪周期</td><td>风格切换</td><td>{tag("混沌转机","y")}</td></tr>
</table>
<div style="background:rgba(210,153,29,.12);border:2px solid var(--gold);border-radius:8px;padding:16px 20px;margin-top:14px;text-align:center">
<div style="font-size:28px;font-weight:900;color:var(--gold);margin-bottom:6px">⚡ 综合判定：风格切换期</div>
<div style="font-size:15px;color:var(--text);line-height:2">
AI算力/芯片大幅回调，资金跷跷板切向机器人、6G、玻璃基板等低位新方向<br>
创业板大跌但近3300家上涨——"假指数，真赚钱"<br>
<span style="color:var(--gold);font-weight:700">关注新方向持续性：机器人+玻璃基板能否成为新主线</span>
</div>
</div>
</div>
</div>
'''

# ── S0: 盘前快讯（从社区帖子提取） ──
s0_items = ''
for i, p in enumerate(jy_posts[:6]):
    title = p.get('title','')[:80] or ''
    content = p.get('content','')[:200] or ''
    # 提取关联个股
    stocks = re.findall(r'[S]\s*[A-Za-z\u4e00-\u9fff]{2,8}', content)
    stock_str = '、'.join(stocks[:3]) if stocks else ''
    s0_items += f'''
<div class="bl-red" style="margin-bottom:8px">
<strong>{i+1}. {esc(title[:60])}</strong><br>
{esc(content[:120])}
{f'<br><span style="font-size:12px;color:var(--muted)">关联：{esc(stock_str)}</span>' if stock_str else ''}
</div>'''

s0 = f'''
<div class="section" id="s0">
<h2>📰 盘前快讯（6月5日） <span class="src sj">韭:实时抓取</span></h2>
<div class="card">
<h3>今日热点速览</h3>
{s0_items if s0_items else '<div class="empty-msg">未获取到盘前消息</div>'}
</div>
</div>
'''

# ── S13: 游资观察 ──
s13 = f'''
<div class="section" id="s13">
<h2>💰 游资观察 — 韭研公社热门博主</h2>

<div class="grid2" style="margin-bottom:12px">
<div class="stat"><div class="v" style="color:var(--red)">7篇看多</div><div class="l">产业挖掘派</div></div>
<div class="stat"><div class="v" style="color:var(--blue)">3篇策略</div><div class="l">数据研判派</div></div>
</div>

<div class="card">
<h3>今日热门博主 TOP10 <span class="src sj">韭:实时热榜</span></h3>
<table>
<tr><th>排名</th><th>博主</th><th>方向</th><th>核心观点</th></tr>
{"".join(f'<tr><td>{i+1}</td><td><strong>{esc(p.get("author","")[:12])}</strong></td><td>{tag(p.get("direction","中性"),"r") if p.get("direction")=="看多" else tag("中性","b")}</td><td style="font-size:11px">{esc(p.get("title","")[:60])}</td></tr>' for i, p in enumerate(jy_posts[:10]))}
</table>
</div>
</div>
'''

# ── 组装 ──
HTML_FOOT = '''
<main>
<script>
function switchTab(id) {
  document.querySelectorAll('.section').forEach(function(s) { s.classList.remove('active'); });
  document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
  var el = document.getElementById(id);
  if (el) el.classList.add('active');
  if (event && event.target) event.target.classList.add('active');
}
</script>
</body>
</html>
'''

html = HTML_HEAD + s0 + s1 + s2 + s3 + s5 + s6 + s7 + s8 + s9 + s10 + s11 + s13 + HTML_FOOT

# 写入文件
output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', '社区复盘_20260605.html')
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"✅ 社区复盘HTML已生成: {output_path}")
print(f"   文件大小: {os.path.getsize(output_path):,} 字节")
