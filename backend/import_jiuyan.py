"""
韭研公社数据导入器
从爬取的HTML中提取帖子 → 按日期组织 → 写入SQLite
支持增量更新：已有日期的数据不会重复写入
"""
import os, sys, re, json
from datetime import date, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bs4 import BeautifulSoup
from backend.models import init_db, insert, insert_many, query, execute

# 配置
RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'raw')
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'fupan.db')

# 33位博主ID
USER_IDS = [
    "4df747be1bf143a998171ef03559b517","06ba6cc884784961b7112545e98c8e0b",
    "23606d36df0f47bd86b5642461202768","f7875a62f88540f6a7cc7965c2b97e14",
    "13da545295e349fc9eb89811b1265b31","fd13e01ed8954304a9bdd1a1d231f49a",
    "1","d43f96f71f5a4ef986911c5f726b4169",
    "23119b3faa73442dbcce4b3165d12266","90ae329471984b0e8cbdecb60e879c95",
    "d13c9931e2ce4a6d96e4e988e57881a9","840c96e9d4a845ab9574a29e57598fb5",
    "fd8e0b0499cb458b996084aa9e74c12f","49d90faaf91c47c9a62ed992feb34175",
    "b13e20149a2f45c9acca10529eacb6b7","faa40b17378b4562ac3f8093e7682975",
    "1b901ff42def4190abb8abfc5ab8187d","d91ce35bfd22433e841f4fdd85886589",
    "967b824fef4b4c4b9a20fbf2a54dbcc8","d031637a724549aaa966e982edf830c7",
    "82b6174c5a4b4d348ff1500596a9aa4a","eabb800874e94c628641df60a7ac619d",
    "5b74c3ab7393469a9ad6d244169a1047","c77ff37e45e3405dbab92d097d409e35",
    "179a91857c5f471eacb7cee384efc990","574ac5f084d94082a573067f833c85c5",
    "79c2149b5eb743809af2c2a339a3e30b","ac49e58190ad4d849f924d0d866c4d74",
    "276f83dafc624053b4e6a136d3a108f4","4fed604ba9d04aababe69bdedbb6c977",
    "21b6c92b728c4b6fa3ba20ee7aa385a8","27ec30b4a75b4560a91dc2bfe8b2918d",
    "41096dbc36844029a9d8cebd219e1615",
]

# 股票→题材映射
STOCK_THEME = {
    "绿的谐波":"机器人","中大力德":"机器人","双环传动":"机器人","埃斯顿":"机器人",
    "汇川技术":"机器人","拓普集团":"机器人","三花智控":"机器人","江苏雷利":"机器人",
    "五洲新春":"机器人","中大力德":"机器人","奥比中光":"机器人","艾迪精密":"机器人",
    "祥明智能":"机器人","模塑科技":"机器人",
    "索辰科技":"物理AI","能科科技":"物理AI","阿尔特":"物理AI","德赛西威":"物理AI",
    "中科创达":"物理AI","软通动力":"物理AI","达实智能":"物理AI","天娱数科":"物理AI",
    "凡拓数创":"物理AI","亿嘉和":"物理AI",
    "中际旭创":"光通信","新易盛":"光通信","天孚通信":"光通信","思泰克":"光通信",
    "南风股份":"光通信",
    "鹏鼎控股":"PCB","东山精密":"PCB","胜宏科技":"PCB","中京电子":"PCB",
    "宝鼎科技":"PCB","华塑控股":"PCB","沪电股份":"PCB","深南电路":"PCB",
    "德龙激光":"玻璃基板","帝尔激光":"玻璃基板","大族激光":"玻璃基板","沃格光电":"玻璃基板",
    "京东方A":"玻璃基板","彩虹股份":"玻璃基板","旗滨集团":"玻璃基板","南京熊猫":"玻璃基板",
    "亚玛顿":"玻璃基板","金龙机电":"玻璃基板","国检集团":"玻璃基板","东威科技":"玻璃基板",
    "风华高科":"MLCC","三环集团":"MLCC","博迁新材":"MLCC","红星发展":"MLCC",
    "双星新材":"MLCC","鑫科材料":"MLCC","康达新材":"MLCC",
    "江海股份":"超级电容","法拉电子":"超级电容","海星股份":"超级电容","艾华集团":"超级电容",
    "祥和实业":"电容",
    "澜起科技":"芯片","长电科技":"芯片","兆易创新":"芯片","华天科技":"芯片",
    "新亚制程":"芯片","晶方科技":"芯片","欧晶科技":"芯片","恒林股份":"芯片",
    "新洁能":"芯片","石英股份":"芯片","三佳科技":"芯片",
    "黄河旋风":"散热","方大炭素":"散热","东方碳素":"散热","德尔未来":"散热",
    "惠丰钻石":"散热",
    "西部材料":"商业航天","铂力特":"商业航天","航天电子":"商业航天",
    "信维通信":"商业航天","电科蓝天":"商业航天","航天工程":"商业航天",
    "中天火箭":"商业航天","神剑股份":"商业航天","再升科技":"商业航天","金利华电":"商业航天",
    "亨通光电":"光纤","宏柏新材":"光纤","新能泰山":"光纤",
    "华电能源":"电力","广西能源":"电力","新中港":"电力","豫能控股":"电力",
    "江苏国信":"电力","粤电力A":"电力","京能电力":"电力","辽宁能源":"电力",
    "华能蒙电":"电力","华电辽能":"电力",
    "郑州煤电":"煤炭","大有能源":"煤炭","盘江股份":"煤炭","昊华能源":"煤炭",
    "中央商场":"消费","步步高":"消费","共创草坪":"消费","粤传媒":"消费",
    "弘信电子":"算力","大位科技":"算力","合锻智能":"算力","嘉环科技":"算力",
    "春秋电子":"AI PC","英力股份":"AI PC","雷神科技":"AI PC",
    "新亚电子":"消费电子","泓淋电力":"消费电子","顺灏股份":"消费电子",
    "歌尔股份":"消费电子","博硕科技":"消费电子",
    "威龙股份":"股权转让","利仁科技":"股权转让","统一股份":"股权转让",
    "宜安科技":"AI眼镜","维信诺":"AI眼镜","兆威机电":"AI眼镜",
    "五方光电":"AI眼镜","卓兆点胶":"AI眼镜",
    "合肥城建":"长鑫存储","合百集团":"长鑫存储","市北高新":"长鑫存储",
    "三孚股份":"长鑫存储","大众交通":"长江存储","养元饮品":"长江存储","国脉文化":"长江存储",
    "华特气体":"芯片气体","中船特气":"芯片气体","广钢气体":"芯片气体",
    "九丰能源":"芯片气体","金宏气体":"芯片气体",
    "中国平安":"金融","贵州茅台":"消费","宁德时代":"新能源",
    "信科移动":"6G","联创电子":"自动驾驶",
    "天洋新材":"化工","多氟多":"化工","中欣氟材":"化工","滨化股份":"化工","沃特股份":"化工",
    "安妮股份":"AI应用","天地在线":"AI应用","群兴玩具":"AI应用",
    "欢瑞世纪":"短剧","香江控股":"城市更新","青龙管业":"城市更新",
    "泰永长征":"数据中心","四方股份":"数据中心","云鼎科技":"煤矿安全","梅安森":"煤矿安全",
    "四环生物":"摘帽","双成药业":"摘帽","华微电子":"摘帽","久之洋":"激光",
    "长飞光纤":"光纤",
}

KW_CATS = {
    "题材驱动": ["龙头","连板","溢价","主升浪","板块效应","资金流入","高位接力","题材切换",
                "涨停","封板","打板","梯队","空间板","补涨"],
    "个股强弱": ["一字板","放量涨停","龙虎榜","机构席位","游资席位","分歧转一致",
                "弱转强","反包","炸板回封","烂板","地天板","换手板"],
    "情绪阈值": ["超预期","不及预期","退潮","冰点","情绪回暖","分歧","修复",
                "高潮","分化","亏钱效应","赚钱效应","一致性","尾盘抢筹"],
}

def parse_user_html(html, uid):
    """Parse a user's profile HTML and return posts grouped by date."""
    soup = BeautifulSoup(html, 'lxml')
    for tag in soup(["script","style","noscript"]):
        tag.decompose()
    text = soup.get_text(separator='\n')
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    # Get username
    username = uid[:12]
    for line in lines[:30]:
        if '用户主页' in line:
            n = line.split('用户主页')[0].strip()
            if n: username = n; break
        if re.match(r'\d[\d,]*\s*关注\s*\d[\d,]*\s*粉丝', line):
            m = re.search(r'(\d[\d,]*)\s*关注\s*(\d[\d,]*)\s*粉丝', line)
            if m: username = lines[lines.index(line)-1] if lines.index(line) > 0 else username
            break
    
    username = lines[5] if len(lines) > 5 else username  # fallback
    
    posts_by_date = {}
    i = 0
    while i < len(lines):
        if re.match(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$', lines[i]):
            ts = lines[i]
            date_key = ts[:10]
            title = lines[i+1] if i+1 < len(lines) else ""
            uname = lines[i-2] if i >= 2 else username
            tags = []
            j = i + 2
            while j < len(lines):
                if lines[j] == "S":
                    sn = lines[j+1] if j+1 < len(lines) else "?"
                    nums = []
                    k = j + 2
                    while k < len(lines) and len(nums) < 4:
                        if re.match(r'^-?\d+\.?\d*$', lines[k]):
                            nums.append(lines[k]); k += 1
                        else: break
                    if len(nums) == 4:
                        tags.append({"name":sn,"reads":int(nums[0]),"likes":int(nums[1]),
                                      "comments":int(nums[2]),"price_pct":float(nums[3])})
                    j = k
                elif re.match(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$', lines[j]): break
                elif any(x in lines[j] for x in ['编辑交易计划','上一页','下一页','前往页','发长文','发布']): j += 1
                else: j += 1
            if tags:
                if date_key not in posts_by_date:
                    posts_by_date[date_key] = []
                posts_by_date[date_key].append({
                    "user": uname, "ts": ts, "title": title,
                    "stock_tags": tags,
                    "stock_names": [t["name"] for t in tags],
                    "reads": max(t["reads"] for t in tags),
                    "likes": max(t["likes"] for t in tags),
                    "comments": max(t["comments"] for t in tags),
                    "price_pct": round(sum(t["price_pct"] for t in tags)/len(tags), 2),
                })
            i = j
        else: i += 1
    return posts_by_date


def save_raw_by_date(input_dir, output_dir):
    """Copy raw user HTML files into date-organized structure."""
    import shutil
    print("📦 Organizing raw data by date...")
    
    # Read the all_data.json if it exists (from earlier scrape)
    # Or re-parse from individual user files
    all_posts = {}
    
    for uid in USER_IDS:
        fp = os.path.join(input_dir, f"user_{uid}.txt")
        if not os.path.exists(fp):
            continue
        with open(fp, 'rb') as f:
            raw = f.read()
        
        # Parse to get dates
        posts_by_date = parse_user_html(raw.decode('utf-8', errors='replace'), uid)
        
        for date_key, posts in posts_by_date.items():
            if date_key not in all_posts:
                all_posts[date_key] = []
            all_posts[date_key].extend(posts)
            
            # Save raw file per user per date
            date_dir = os.path.join(output_dir, date_key)
            os.makedirs(date_dir, exist_ok=True)
            
            user_file = os.path.join(date_dir, f"user_{uid}.html")
            # Only write if not exists
            if not os.path.exists(user_file):
                with open(user_file, 'wb') as f:
                    f.write(raw)
    
    # Write a summary per date
    for date_key, posts in sorted(all_posts.items()):
        date_dir = os.path.join(output_dir, date_key)
        os.makedirs(date_dir, exist_ok=True)
        
        # Deduplicate posts for this date
        seen = set()
        uniq = []
        for p in posts:
            key = (p["user"], p["title"][:60])
            if key not in seen:
                seen.add(key)
                uniq.append(p)
        
        summary = {
            "date": date_key,
            "post_count": len(uniq),
            "user_count": len(set(p["user"] for p in uniq)),
            "stock_count": len(set(s for p in uniq for s in p["stock_names"])),
            "posts": uniq[:200],  # Limit for file size
        }
        
        with open(os.path.join(date_dir, "summary.json"), "w") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        print(f"  {date_key}: {len(uniq)} posts, {summary['user_count']} users, {summary['stock_count']} stocks")
    
    print(f"\n✅ Organized {len(all_posts)} dates into {output_dir}")
    return all_posts


def import_posts_to_db(all_posts, max_dates=30):
    """Import posts into SQLite database (most recent dates)."""
    print("\n💾 Importing posts into database...")
    
    # Only take recent dates
    sorted_dates = sorted(all_posts.keys(), reverse=True)[:max_dates]
    
    total_imported = 0
    for date_key in sorted_dates:
        posts = all_posts[date_key]
        
        # Check if posts already exist for this date
        existing = query("SELECT COUNT(*) as c FROM posts WHERE date=? AND platform='jy'", (date_key,))
        if existing and existing[0]['c'] > 0:
            print(f"  ⏭ {date_key}: {existing[0]['c']} posts already exist, skipping")
            continue
        
        # Deduplicate
        seen = set()
        uniq = []
        for p in posts:
            key = (p["user"], p["title"][:60])
            if key not in seen:
                seen.add(key)
                uniq.append(p)
        
        # Generate post direction from keywords
        db_rows = []
        for p in uniq:
            direction = "中性"
            title_lower = (p["title"] + " ").lower()
            if any(kw in title_lower for kw in ["超预期","看好","看多","利好","突破","主升浪","龙头"]):
                direction = "看多"
            elif any(kw in title_lower for kw in ["不及预期","退潮","警惕","风险","见顶","出货","看空","冰点"]):
                direction = "看空"
            
            tags_str = ",".join(p["stock_names"][:10])
            
            db_rows.append({
                "date": date_key,
                "platform": "jy",
                "author": p["user"],
                "title": p["title"][:200],
                "content": f"涨幅:{p['price_pct']}% 个股:{tags_str}",
                "direction": direction,
                "views": p["reads"],
                "comments": p["comments"],
                "tags": tags_str,
            })
        
        if db_rows:
            insert_many("posts", db_rows)
            total_imported += len(db_rows)
            print(f"  ✅ {date_key}: {len(db_rows)} posts imported")
    
    print(f"\n✅ Total: {total_imported} posts imported across {len(sorted_dates)} dates")
    return sorted_dates


def generate_section_html(all_posts, date_key, is_today=False):
    """Generate section HTML for a specific date showing 韭研公社 analysis."""
    posts = all_posts.get(date_key, [])
    if not posts:
        return None
    
    # Deduplicate
    seen = set()
    uniq = []
    for p in posts:
        key = (p["user"], p["title"][:60])
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    
    # Sort by engagement
    uniq.sort(key=lambda x: x["reads"]*0.3+x["likes"]*0.3+x["comments"]*0.4, reverse=True)
    
    # --- s6: 韭研公社今日热帖 ---
    top = uniq[:10]
    cards = ""
    for i, p in enumerate(top):
        tags_html = " ".join([f'<a class="stock-tag" href="/s/{s}" target="_blank">{s}</a>' for s in p["stock_names"][:5]])
        direction_color = {"看多": "var(--red)", "看空": "var(--green)", "中性": "var(--muted)"}
        dir_color = direction_color.get("看多" if any(k in (p["title"]+" ") for k in ["超预期","龙头","主升浪"]) else "中性", "var(--muted)")
        
        cards += f'''
<div class="card" style="margin-bottom:8px">
  <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
    <span><strong>{p["user"]}</strong></span>
    <span style="font-size:11px;color:var(--muted)">{p["ts"][11:19]}</span>
  </div>
  <h3 style="margin:4px 0;font-size:14px">{p["title"][:100]}</h3>
  <div style="margin:4px 0">{tags_html}</div>
  <div style="display:flex;gap:12px;font-size:12px;color:var(--muted)">
    <span>👁 {p["reads"]}</span>
    <span>👍 {p["likes"]}</span>
    <span>💬 {p["comments"]}</span>
    <span style="color:{'var(--red)' if p['price_pct']>0 else 'var(--green)'}">📈 {p["price_pct"]}%</span>
  </div>
</div>'''
    
    s6_html = f'''<div class="section-content">
<h2>📢 韭研公社热议 <span class="tag r">实时</span></h2>
<p style="color:var(--muted);font-size:12px">来源: jiuyangongshe.com · {date_key}</p>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
{cards}
</div>
</div>'''
    
    # --- s5: 题材热度排行榜 ---
    from collections import Counter
    theme_mentions = Counter()
    theme_stocks = {}
    theme_prices = {}
    
    for p in uniq:
        for t in p["stock_tags"]:
            name = t["name"]
            theme = STOCK_THEME.get(name, "其他")
            theme_mentions[theme] += 1
            if theme not in theme_stocks:
                theme_stocks[theme] = Counter()
            theme_stocks[theme][name] += 1
            if theme not in theme_prices:
                theme_prices[theme] = []
            theme_prices[theme].append(t["price_pct"])
    
    theme_rows = ""
    for theme, count in theme_mentions.most_common(15):
        if theme == "其他": continue
        avg_price = sum(theme_prices[theme])/len(theme_prices[theme]) if theme_prices[theme] else 0
        top3 = ", ".join([s[0] for s in theme_stocks[theme].most_common(3)])
        heat = min(count * 2, 99)
        price_color = "var(--red)" if avg_price > 10 else "var(--gold)" if avg_price > 5 else "var(--muted)"
        
        # Heat bar
        heat_bar = f'<div style="width:{heat}%;height:6px;background:var(--red);border-radius:3px"></div>'
        
        theme_rows += f'''<tr>
  <td><strong>{theme}</strong></td>
  <td><div style="display:flex;align-items:center;gap:6px"><span>{count}</span><div style="flex:1;height:6px;background:var(--border);border-radius:3px">{heat_bar}</div></div></td>
  <td style="color:{price_color}">{avg_price:+.1f}%</td>
  <td style="font-size:12px">{top3}</td>
</tr>'''
    
    s5_html = f'''<div class="section-content">
<h2>🔥 题材热度排行榜 <span class="tag r">热度+涨幅验证</span></h2>
<p style="color:var(--muted);font-size:12px">基于韭研公社{len(uniq)}篇帖子分析</p>
<table class="data-table">
<thead><tr><th>题材</th><th>提及数</th><th>涨幅%</th><th>核心个股</th></tr></thead>
<tbody>{theme_rows}</tbody>
</table>
</div>'''
    
    return {"s5": s5_html, "s6": s6_html}


def save_sections_to_db(all_posts, dates):
    """Save generated section HTML to DB."""
    print("\n📝 Saving section HTML to database...")
    count = 0
    for date_key in dates:
        sections = generate_section_html(all_posts, date_key)
        if not sections:
            continue
        
        existing = query("SELECT COUNT(*) as c FROM section_html WHERE date=? AND (section_id='s5' OR section_id='s6')", (date_key,))
        if existing and existing[0]['c'] >= 2:
            print(f"  ⏭ {date_key}: sections already exist")
            continue
        
        for sid, html_content in sections.items():
            title_map = {"s5": "题材热度排行榜", "s6": "韭研公社热议"}
            insert("section_html", {
                "date": date_key,
                "section_id": sid,
                "title": title_map.get(sid, sid),
                "html": html_content,
            })
            count += 1
        print(f"  ✅ {date_key}: {len(sections)} sections")
    
    print(f"✅ Total: {count} sections saved")
    return count


def generate_heat_data(all_posts, dates):
    """Generate platform_heat data from posts."""
    print("\n📊 Generating platform heat data...")
    from collections import Counter
    count = 0
    
    # Delete old platform_heat for these dates
    for date_key in dates:
        execute("DELETE FROM platform_heat WHERE platform='jygs' AND stat_date=?", (date_key,))
    
    for date_key in dates:
        posts = all_posts.get(date_key, [])
        if not posts:
            continue
        
        # Count mentions per topic
        theme_counts = Counter()
        for p in posts:
            for t in p["stock_tags"]:
                theme = STOCK_THEME.get(t["name"], "其他")
                theme_counts[theme] += 1
        
        for theme, cnt in theme_counts.most_common(20):
            if theme == "其他":
                continue
            try:
                insert("platform_heat", {
                    "topic_id": 0,
                    "topic_name": theme,
                    "platform": "jygs",
                    "stat_date": date_key,
                    "mention_count": cnt,
                    "article_count": cnt,
                    "comment_count": 0,
                    "like_count": 0,
                    "favorite_count": 0,
                    "share_count": 0,
                    "hot_rank": 0,
                    "heat_change_1d": 0,
                    "heat_change_3d": 0,
                    "heat_change_7d": 0,
                })
                count += 1
            except:
                pass
    
    print(f"✅ {count} platform_heat records saved")
    return count


def main():
    """Main entry point."""
    print("=" * 60)
    print("  韭研公社 数据导入器 v1.0")
    print("  从爬取数据 → 按日期组织 → SQLite")
    print("=" * 60)
    
    # Step 1: Initialize DB
    print("\n📁 Initializing database...")
    init_db()
    
    # Step 2: Source directory (scraped data)
    import shutil
    scrape_dir = "/tmp/jiuyan_data"
    
    if not os.path.exists(scrape_dir):
        print(f"✗ Scrape directory not found: {scrape_dir}")
        return
    
    # Step 3: Organize raw data by date
    all_posts = save_raw_by_date(scrape_dir, RAW_DIR)
    
    if not all_posts:
        print("✗ No posts found!")
        return
    
    # Step 4: Import to DB (recent 30 dates)
    recent_dates = import_posts_to_db(all_posts, max_dates=30)
    
    # Step 5: Generate section HTML
    save_sections_to_db(all_posts, recent_dates)
    
    # Step 6: Generate heat data
    generate_heat_data(all_posts, recent_dates)
    
    print("\n" + "=" * 60)
    print("✅ 数据导入完成!")
    print(f"  数据库: {DB_PATH}")
    print(f"  原始数据: {RAW_DIR}")
    print(f"  覆盖日期: {recent_dates[0]} ~ {recent_dates[-1]}")
    print("=" * 60)


if __name__ == "__main__":
    main()
