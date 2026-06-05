#!/usr/bin/env python3
"""
⚠️ 警告：此脚本的正则 s3_pattern（第 193 行）有已知 bug！
使用 `.*?</div>\s*</div>` 匹配 section 边界会导致：
- 在 stock-box 内部 vote 区域（`</div></div>` 连续结构）提前截断
- 导致大部分内容变成游离 HTML，跨 tab 显示
详见记忆 section-container-rule

如要使用，必须先修复正则逻辑（改用 HTML 解析器或精确定位标记）。

Generate s3 (题材生命周期) section with:
- 涨停家数统计 for each topic
- 容量趋势票 (红底白字标签)
- 1:1 structure as backup file
"""
import sys, os, re, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from backend.models import init_db, query
init_db()

today = "2026-06-05"

# ── Data ──
sectors = query("SELECT sector, COUNT(*) as cnt, MAX(board_num) as mb FROM zt_stocks WHERE date=? AND sector!='' GROUP BY sector ORDER BY cnt DESC LIMIT 20", (today,))
all_stocks = query("SELECT name, sector, board_num, trade_amt, float_mcap, net_inflow, price, seal_time FROM zt_stocks WHERE date=? ORDER BY board_num DESC", (today,))
high_boards = [s for s in all_stocks if s['board_num'] >= 2]
mkt = query("SELECT * FROM market_data WHERE date=? ORDER BY id DESC LIMIT 1", (today,))
m = mkt[0] if mkt else {}
zt_total = m.get('zt_count', 82) or 82
jy_posts = query("SELECT title, author, direction FROM posts WHERE platform='jy' AND date=? ORDER BY id DESC LIMIT 30", (today,))

# ── Topic definitions with sector keywords and trend stocks ──
topics = [
    {
        'emoji': '🤖', 'name': '机器人/物理AI', 'stage': '爆发期', 'tag_cls': 'r', 'border': 'red',
        'headline': '黄仁勋全力押注物理AI，机器人产业链全线爆发',
        'desc': '黄仁勋在Computex公开表示"未来半导体制造将越来越依赖机器人和人工智能"，英伟达与韩国制造企业深度合作推进Physical AI落地。A股机器人板块全面爆发：绿的谐波(谐波减速器龙头批量配套斗山机器人)、艾迪精密(工业机器人发往韩国)、阿尔特(英伟达A股独家全链路绑定)。',
        'tao': '木炭一箩筐', 'jiu': '戈壁淘金',
        'up': 75, 'dn': 10, 'ne': 15,
        'label': '看多75% | 看空10% | 中性15%（木炭"英伟达钦点物理AI" | 戈壁"机器人进入产业加速期"）',
        'sector_kw': ['通用设备', '专用设备', '电机', '自动化'],
        'trend_stocks': ['绿的谐波', '中大力德', '双环传动', '汇川技术', '埃斯顿'],
    },
    {
        'emoji': '🔬', 'name': '玻璃基板/先进封装', 'stage': '主升期', 'tag_cls': 'r', 'border': 'red',
        'headline': '台积电官宣CoPoS玻璃基板试产线投产，产业化加速推进',
        'desc': '台积电正式官宣CoPoS玻璃基板技术试产线建成投产，标志着玻璃基板作为下一代先进封装核心材料的产业化步入实质推进阶段。德龙激光(TGV设备龙头)强势涨停，帝尔激光、大族激光跟涨。沃格光电、京东方A产业链受益。玻璃基板适配大尺寸高密度AI芯片封装，0到1产业机遇明确。',
        'tao': 'Vin7的大', 'jiu': '异动特工小队',
        'up': 70, 'dn': 5, 'ne': 25,
        'label': '看多70% | 看空5% | 中性25%（Vin7大"台积电官宣试产线" | 无名小韭763"TGV设备+耗材双爆发"）',
        'sector_kw': ['光学光电', '玻璃玻纤', '电子'],
        'trend_stocks': ['京东方A', '沃格光电', '德龙激光', '帝尔激光', '大族激光', '彩虹股份'],
    },
    {
        'emoji': '📡', 'name': '6G通信', 'stage': '启动期', 'tag_cls': 'r', 'border': 'gold',
        'headline': '6G核心AI产业链梳理，武汉凡谷/东方通信/中兴通讯集体走强',
        'desc': '6G概念全线爆发。中兴通讯作为全球通信设备巨头及6G标准核心制定者，已全面展开6G端到端系统预研。信科移动深度参与IMT-2030(6G)推进组。武汉凡谷、东方通信涨停。6G与AI深度融合，通感算一体化、太赫兹通信、星地融合组网三大方向备受关注。',
        'tao': '炒谷养娃2007', 'jiu': '题材图谱小集',
        'up': 65, 'dn': 5, 'ne': 30,
        'label': '看多65% | 看空5% | 中性30%（6G核心AI产业链有望成为新主线，但需持续催化验证）',
        'sector_kw': ['通信设备', '通信', '电信'],
        'trend_stocks': ['中兴通讯', '信科移动', '中国移动', '盛路通信', '创远信科'],
    },
    {
        'emoji': '🔌', 'name': 'MLCC/电容/电感', 'stage': '主升期', 'tag_cls': 'r', 'border': 'red',
        'headline': '被动元件提价再加速！村田/太阳诱电7月电感涨价，MLCC供不应求',
        'desc': '被动元件供需持续紧张。村田、太阳诱电有望在7月1日起再次对电感进行提价。三环集团计划自7月1日起对晶振基座调价10-30%。MLCC目前供需极为紧张，村田、三星均表示MLCC景气度极高、持续供不应求。氧化镝作为MLCC核心材料，卖方给出10倍涨价空间。顺络电子、麦捷科技强势涨停。',
        'tao': '小陆研选', 'jiu': '戈壁淘金',
        'up': 80, 'dn': 5, 'ne': 15,
        'label': '看多80% | 看空5% | 中性15%（戈壁"被动元件涨价大行情" | 无名小韭5718"氧化镝=下一个中船特气"）',
        'sector_kw': ['元件', '电子', '半导体', '元器件', '光学光电'],
        'trend_stocks': ['顺络电子', '麦捷科技', '风华高科', '三环集团', '江海股份', '铂科新材', '国瓷材料'],
    },
    {
        'emoji': '⛏️', 'name': '煤炭', 'stage': '高位分歧', 'tag_cls': 'y', 'border': 'gold',
        'headline': '大有能源5板领涨！煤炭板块逆势走强',
        'desc': '大有能源超预期晋级5板，成为全市场最高标。焦煤期货大涨，安泰集团、平煤股份涨停助攻。煤炭板块作为防御避险品种逆势活跃。大有能源5板高度打开空间，但煤炭板块跟风力度偏弱，分歧较大。',
        'tao': '庄哥说股', 'jiu': '',
        'up': 50, 'dn': 25, 'ne': 25,
        'label': '看多50% | 看空25% | 中性25%（庄哥"煤炭逆势但跟风弱" | 大有能源5板空间龙）',
        'sector_kw': ['煤炭', '煤炭开采'],
        'trend_stocks': ['大有能源', '安泰集团', '平煤股份', '陕西煤业', '中国神华', '中煤能源'],
    },
    {
        'emoji': '💡', 'name': '光纤/光通信', 'stage': '活跃', 'tag_cls': 'y', 'border': 'gold',
        'headline': '光纤预制棒价格暴涨550%，宏柏新材9N高纯四氯化硅卡位',
        'desc': '央视实锤光纤全行业爆单，头部光缆厂订单排至2027年。AI算力拉动高端A2光纤预制棒年内暴涨550%、一棒难求。光棒扩产周期18-24月，上游9N高纯四氯化硅成为核心卡脖子原料。宏柏新材布局2万吨光纤级高纯四氯化硅，对标三孚股份。亨通光电、长飞光纤主力流入。',
        'tao': '独自等待', 'jiu': '题材图谱小集',
        'up': 60, 'dn': 10, 'ne': 30,
        'label': '看多60% | 看空10% | 中性30%（宏柏新材对标三孚硅烷，光棒紧缺2027年前无解）',
        'sector_kw': ['通信设备', '光纤'],
        'trend_stocks': ['亨通光电', '长飞光纤', '宏柏新材', '三孚股份', '中天科技', '烽火通信'],
    },
    {
        'emoji': '💎', 'name': '石墨烯/金刚石散热', 'stage': '试错', 'tag_cls': 'b', 'border': 'blue',
        'headline': '美股Solidion暴涨350%引爆石墨烯太空电池，英伟达钦点散热材料',
        'desc': '美股Solidion因石墨烯太空电池暴涨350%。英伟达最新Rubin服务器采用石墨烯+金刚石双散热方案。方大炭素3天2板、东方碳素冲30cm涨停（石墨烯版惠丰钻石）。德尔未来、黄河旋风跟涨。AI高端GPU散热迎来产业级机遇，但从0到1阶段初期，板块联动尚弱。',
        'tao': '土拨鼠', 'jiu': '',
        'up': 40, 'dn': 15, 'ne': 45,
        'label': '看多40% | 看空15% | 中性45%（土拨鼠"石墨烯散热新概念" | 产业逻辑待验证）',
        'sector_kw': ['冶钢原料', '家居用品', '金属'],
        'trend_stocks': ['方大炭素', '德尔未来', '黄河旋风', '东方碳素', '惠丰钻石', '中兵红箭'],
    },
]

def esc(s):
    if s is None: return ''
    return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def make_chip(name, board=0, is_trend=False):
    """红底白字标签 for 涨停个股; 橙底 for 趋势票"""
    if is_trend:
        return f'<span style="display:inline-block;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700;color:#fff;background:#d2991d;margin:2px">{esc(name)}</span>'
    else:
        tag = f'{esc(name)}' + (f' <span style="font-size:10px;opacity:0.8">{board}板</span>' if board > 1 else '')
        return f'<span style="display:inline-block;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700;color:#fff;background:#f85149;margin:2px">{tag}</span>'

def make_stock_tag(name, board=0, extra=''):
    """红底白字标签 — 显眼"""
    label = esc(name)
    if board >= 2:
        label += f' <span style="font-size:10px;opacity:0.85">({board}b)</span>'
    if extra:
        label += extra
    return f'<span style="display:inline-block;padding:3px 12px;border-radius:5px;font-size:13px;font-weight:700;color:#fff;background:#f85149;margin:3px;box-shadow:0 1px 4px rgba(248,81,73,.3)">{label}</span>'

def make_trend_tag(name, desc=''):
    """橙底白字标签 for 容量趋势票"""
    label = esc(name)
    if desc:
        label += f' <span style="font-size:10px;opacity:0.85">{desc}</span>'
    return f'<span style="display:inline-block;padding:3px 12px;border-radius:5px;font-size:13px;font-weight:700;color:#fff;background:#d2991d;margin:3px;box-shadow:0 1px 4px rgba(210,153,29,.3)">{label}</span>'

# ── Build cards ──
cards_html = ''
for tp in topics:
    # 1. Count 涨停 stocks matching this topic
    zt_matched = []
    for s in all_stocks:
        sec = s['sector'] or ''
        nm = s['name'] or ''
        bn = s['board_num'] or 0
        if any(kw in sec for kw in tp['sector_kw']):
            zt_matched.append(s)
    
    zt_count = len(zt_matched)
    
    # 2. Build 涨停 stocks tags (红底白字)
    zt_tags = ''.join(make_stock_tag(s['name'], s['board_num']) for s in zt_matched[:8])
    
    # 3. Build 容量趋势票 tags (橙底白字)
    trend_tags = ''
    for s_name in tp['trend_stocks']:
        # Check if already in zt list
        if any(s['name'] == s_name for s in zt_matched):
            continue
        trend_tags += make_trend_tag(s_name)
    
    # 4. Stock box title with zt count
    zt_badge = '<span style="display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:700;color:#fff;background:#f85149;margin-left:6px">涨停' + str(zt_count) + '家</span>'
    
    # Build the source tags outside f-string
    src_html = ''
    if tp['tao']:
        src_html += ' <span class="src st">淘:' + esc(tp['tao']) + '</span>'
    if tp['jiu']:
        src_html += ' <span class="src sj">韭:' + esc(tp['jiu']) + '</span>'
    
    trend_html = ''
    if trend_tags:
        trend_html = '<div style="margin:4px 0"><span style="font-size:11px;color:var(--muted);margin-right:6px">📊 容量趋势票</span> ' + trend_tags + '</div>'
    
    card = '''
<div class="stock-box" style="border-color:var(--''' + tp['border'] + ''');background:rgba(248,81,73,.04)">
<h4>''' + tp['emoji'] + ' ' + esc(tp['name']) + ' <span class="tag ' + tp['tag_cls'] + '">' + esc(tp['stage']) + '''</span>''' + zt_badge + '''</h4>
<div class="headline">''' + esc(tp['headline']) + '''</div>
<p>''' + esc(tp['desc']) + src_html + '''</p>

<!-- 涨停标的 -->
<div style="margin:8px 0"><span style="font-size:11px;color:var(--muted);margin-right:6px">📈 涨停标的</span> ''' + (zt_tags if zt_tags else '<span style="font-size:11px;color:var(--muted)">无</span>') + '''</div>
''' + trend_html + '''

<div class="vote"><div class="v-up" style="width:''' + str(tp['up']) + '''%"></div><div class="v-dn" style="width:''' + str(tp['dn']) + '''%"></div><div class="v-ne" style="width:''' + str(tp['ne']) + '''%"></div></div>
<div class="v-label">''' + esc(tp['label']) + '''</div>
</div>'''
    cards_html += card

# ── Assemble ──
s3_html = f'''<div class="section" id="s3">
<h2>三、题材生命周期全景 <span style="font-size:12px;color:var(--muted);font-weight:normal">今日涨停{zt_total}家 · 数据来源：韭研公社实时抓取 + 数据库</span></h2>
{cards_html}
</div>'''

# ── Write to index.html ──
idx_path = 'frontend/index.html'
with open(idx_path, 'r', encoding='utf-8') as f:
    content = f.read()

s3_pattern = r'<div class="section" id="s3">.*?</div>\s*</div>'
match = re.search(s3_pattern, content, re.DOTALL)
if match:
    old_s3 = match.group(0)
    new_content = content.replace(old_s3, s3_html)
    with open(idx_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f'✅ s3 section updated ({len(s3_html)} chars)')
    print(f'   7 topic cards with 涨停计数 + 红底白字标签')
    # Print summary
    for tp in topics:
        cnt = 0
        for s in all_stocks:
            sec = s['sector'] or ''
            if any(kw in sec for kw in tp['sector_kw']):
                cnt += 1
        zt_names = [s['name'] for s in all_stocks if any(kw in (s['sector'] or '') for kw in tp['sector_kw'])]
        trend_names = [n for n in tp['trend_stocks'] if n not in zt_names]
        print(f'  {tp["name"]:12s}: 涨停{cnt:2d}家 {", ".join(zt_names[:5])}  | 趋势: {", ".join(trend_names[:4])}')
else:
    # Fallback: find by line
    print('❌ Regex failed, trying line-based...')
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'id="s3"' in line:
            # Find end of s3 section
            for j in range(i, min(i+200, len(lines))):
                if j < len(lines) and lines[j].strip() == '</div>' and j > i+10:
                    # Check if it's the s3 closing tag
                    new_lines = lines[:i] + [s3_html] + lines[j+1:]
                    new_content = '\n'.join(new_lines)
                    with open(idx_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f'✅ s3 section replaced (line-based)')
                    break
            break
