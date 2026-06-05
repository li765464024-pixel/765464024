"""
Flask 主应用 — API 路由
"""
import json
import os
import sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.models import query, init_db
from backend.services.crawler import refresh_all

app = Flask(__name__, static_folder=None)
CORS(app)

# ── 静态文件服务 (前端) ──
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend')

@app.route('/')
def index():
    return send_from_directory(FRONTEND_DIR, 'index.html')

@app.route('/css/<path:path>')
def serve_css(path):
    return send_from_directory(os.path.join(FRONTEND_DIR, 'css'), path)

@app.route('/js/<path:path>')
def serve_js(path):
    return send_from_directory(os.path.join(FRONTEND_DIR, 'js'), path)

@app.route('/<path:filename>')
def serve_frontend_files(filename):
    """通用静态文件fallback（确保 HTML/CSS/JS 新文件可访问）"""
    return send_from_directory(FRONTEND_DIR, filename)

# ════════════════════════════════════════════
# API 接口
# ════════════════════════════════════════════

@app.route('/api/market/today')
def api_market_today():
    """今日大盘数据"""
    rows = query("SELECT * FROM market_data WHERE date = (SELECT MAX(date) FROM market_data)")
    if rows:
        return jsonify({'ok': True, 'data': rows[0]})
    return jsonify({'ok': False, 'error': '暂无数据'})

@app.route('/api/board/list')
def api_board_list():
    """指定板次涨停个股"""
    board = request.args.get('board', 1, type=int)
    rows = query("SELECT * FROM zt_stocks WHERE board_num = ? AND date = (SELECT MAX(date) FROM market_data) ORDER BY seal_time", (board,))
    return jsonify({'ok': True, 'data': rows})

@app.route('/api/board/summary')
def api_board_summary():
    """连板晋级率汇总"""
    rows = query("SELECT * FROM board_summary WHERE date = (SELECT MAX(date) FROM market_data) ORDER BY board_num")
    return jsonify({'ok': True, 'data': rows})

@app.route('/api/sectors/hot')
def api_sectors_hot():
    """板块热度排行"""
    rows = query("SELECT * FROM sectors WHERE date = (SELECT MAX(date) FROM market_data) ORDER BY zt_count DESC")
    return jsonify({'ok': True, 'data': rows})

@app.route('/api/posts')
def api_posts():
    """社区帖子（按平台筛选）"""
    platform = request.args.get('platform', '')
    date = request.args.get('date', '')
    sql = "SELECT * FROM posts WHERE 1=1"
    params = []
    if platform:
        sql += " AND platform = ?"
        params.append(platform)
    if date:
        sql += " AND date = ?"
        params.append(date)
    sql += " ORDER BY views DESC, id DESC LIMIT 50"
    rows = query(sql, params)
    return jsonify({'ok': True, 'data': rows})

@app.route('/api/board/higher')
def api_board_higher():
    """高板个股（3板及以上）"""
    rows = query("SELECT * FROM zt_stocks WHERE board_num >= 3 AND date = (SELECT MAX(date) FROM market_data) ORDER BY board_num DESC, seal_time")
    return jsonify({'ok': True, 'data': rows})

@app.route('/api/market/refresh', methods=['POST'])
def api_market_refresh():
    """触发数据刷新 — 实时爬取"""
    try:
        results = refresh_all()
        return jsonify({'ok': True, 'message': f'更新完成: 涨停{results.get("zt_pool",0)}只 · 韭研公社{results.get("jy_posts",0)}条', 'data': results})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/data/versions')
def api_data_versions():
    """数据版本列表（有数据的日期）"""
    source = request.args.get('source', 'market_data')
    rows = query(f"SELECT DISTINCT date FROM {source} ORDER BY date DESC")
    return jsonify({'ok': True, 'data': [r['date'] for r in rows]})

@app.route('/api/section/<sid>')
def api_section(sid):
    """单个 section 的 HTML 内容（可选 date 参数）"""
    req_date = request.args.get('date', '')
    if req_date:
        rows = query("SELECT * FROM section_html WHERE section_id=? AND date=?", (sid, req_date))
    else:
        rows = query("SELECT * FROM section_html WHERE section_id=? AND date=(SELECT MAX(date) FROM section_html)", (sid,))
    if rows:
        return jsonify({'ok': True, 'data': rows[0]})
    return jsonify({'ok': False, 'error': f'Section {sid} not found'})

@app.route('/api/sections/all')
def api_sections_all():
    """当天所有 section 的 HTML（可选 date 参数）"""
    req_date = request.args.get('date', '')
    if req_date:
        rows = query("SELECT * FROM section_html WHERE date=? ORDER BY id", (req_date,))
    else:
        rows = query("SELECT * FROM section_html WHERE date=(SELECT MAX(date) FROM section_html) ORDER BY id")
    data = {r['section_id']: r for r in rows}
    return jsonify({'ok': True, 'data': data, 'list': rows})

@app.route('/api/sections/dates')
def api_sections_dates():
    """有 section 数据的日期列表"""
    rows = query("SELECT DISTINCT date FROM section_html ORDER BY date DESC")
    return jsonify({'ok': True, 'data': [r['date'] for r in rows]})

@app.route('/api/today/overview')
def api_today_overview():
    """今日数据全景（可选 date 参数）"""
    req_date = request.args.get('date', '')
    if not req_date:
        req_date = date.today().strftime("%Y-%m-%d")
    
    market = query("SELECT * FROM market_data WHERE date=? ORDER BY id DESC LIMIT 1", (req_date,))
    zt_by_board = {b: query("SELECT COUNT(*) as c FROM zt_stocks WHERE board_num=? AND date=?", (b, req_date))[0]['c'] for b in range(1,6)}
    jy_posts = query("SELECT * FROM posts WHERE platform='jy' AND date=? ORDER BY id DESC LIMIT 10", (req_date,))
    versions = query("SELECT DISTINCT date FROM market_data ORDER BY date DESC")
    
    return jsonify({
        'ok': True,
        'data': {
            'today': req_date,
            'market': market[0] if market else None,
            'zt_by_board': zt_by_board,
            'zt_total': sum(zt_by_board.values()),
            'jy_posts_count': len(jy_posts),
            'versions': [r['date'] for r in versions],
        }
    })


# ════════════════════════════════════════════
# 题材生命周期 API
# ════════════════════════════════════════════

from backend.services.lifecycle import analyze_topic, analyze_all_active_topics, discover_active_topics

@app.route('/api/lifecycle/analyze', methods=['POST'])
def api_lifecycle_analyze():
    """触发指定题材分析（或全量分析）"""
    body = request.get_json(silent=True) or {}
    topic_name = body.get('topic', '')
    analysis_date = body.get('date', date.today().strftime("%Y-%m-%d"))
    
    try:
        if topic_name:
            result = analyze_topic(topic_name, analysis_date)
            return jsonify({'ok': True, 'data': result})
        else:
            results = analyze_all_active_topics(analysis_date)
            return jsonify({'ok': True, 'data': results, 'count': len(results)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/lifecycle/result')
def api_lifecycle_result():
    """获取某题材某日的分析结果"""
    topic = request.args.get('topic', '')
    analysis_date = request.args.get('date', date.today().strftime("%Y-%m-%d"))
    if not topic:
        return jsonify({'ok': False, 'error': '缺少 topic 参数'})
    
    rows = query(
        "SELECT * FROM topic_lifecycle WHERE topic_name=? AND date=? ORDER BY id DESC LIMIT 1",
        (topic, analysis_date)
    )
    if rows:
        result = rows[0]
        # 解析 summary_json 如果有
        if result.get('summary_json'):
            try:
                full = json.loads(result['summary_json'])
                return jsonify({'ok': True, 'data': full})
            except:
                pass
        return jsonify({'ok': True, 'data': dict(result)})
    return jsonify({'ok': False, 'error': f'无 {topic} {analysis_date} 的分析记录'})

@app.route('/api/lifecycle/topics')
def api_lifecycle_topics():
    """获取某日所有活跃题材的生命周期快照"""
    analysis_date = request.args.get('date', date.today().strftime("%Y-%m-%d"))
    rows = query(
        "SELECT topic_name, lifecycle_stage, total_score, price_strength, capital_strength, catalyst_strength, sentiment_strength, structure_quality, leader_name, leader_board, zt_count FROM topic_lifecycle WHERE date=? ORDER BY total_score DESC",
        (analysis_date,)
    )
    
    # 如果没有分析记录，先自动发现活跃题材
    if not rows:
        topics = discover_active_topics(analysis_date)
        return jsonify({'ok': True, 'data': [], 'discovered': [t['name'] for t in topics[:10]], 'message': '尚未分析，可使用 POST /api/lifecycle/analyze 触发分析'})
    
    return jsonify({'ok': True, 'data': rows})

@app.route('/api/lifecycle/history')
def api_lifecycle_history():
    """获取某题材最近N天的生命周期演变"""
    topic = request.args.get('topic', '')
    days = request.args.get('days', 30, type=int)
    if not topic:
        return jsonify({'ok': False, 'error': '缺少 topic 参数'})
    
    rows = query(
        "SELECT date, lifecycle_stage, total_score, price_strength, capital_strength, leader_name, leader_board, zt_count FROM topic_lifecycle WHERE topic_name=? ORDER BY date DESC LIMIT ?",
        (topic, days)
    )
    return jsonify({'ok': True, 'data': rows})

@app.route('/api/lifecycle/report')
def api_lifecycle_report():
    """获取题材生命周期 HTML 报告（供 s3 直接渲染）"""
    topic = request.args.get('topic', '')
    analysis_date = request.args.get('date', date.today().strftime("%Y-%m-%d"))
    
    if not topic:
        return jsonify({'ok': False, 'error': '缺少 topic 参数'})
    
    rows = query(
        "SELECT * FROM topic_lifecycle WHERE topic_name=? AND date=? ORDER BY id DESC LIMIT 1",
        (topic, analysis_date)
    )
    if not rows:
        return jsonify({'ok': False, 'error': f'无 {topic} 分析记录'})
    
    row = rows[0]
    full = row
    if row.get('summary_json'):
        try:
            full = json.loads(row['summary_json'])
        except:
            pass
    
    # 构造 HTML 卡片（与现有 stock-box 风格一致）
    stage = row['lifecycle_stage'] or ''
    total = row['total_score'] or 0
    leader = row['leader_name'] or ''
    board = row['leader_board'] or 0
    zt = row['zt_count'] or 0
    
    # 颜色
    color_map = {
        '孕育期/预热期': 'blue',
        '启动期': 'gold',
        '爆发期': 'red',
        '分歧震荡期': 'gold',
        '退潮期': 'green',
        '余温反复/二波观察期': 'blue',
    }
    color = color_map.get(stage, 'blue')
    
    risks = full.get('risk_warnings', []) if isinstance(full, dict) else []
    risk_badges = ''
    for r in risks:
        rtype = r.get('risk_type', '')
        sev = r.get('severity', 'warning')
        risk_badges += f'<span class="chip chip-{"dn" if sev=="critical" else "ne"}">{rtype}</span> '
    
    reasons = full.get('stage_judgement_reasons', []) if isinstance(full, dict) else []
    reasons_html = ' '.join([f'<span style="font-size:11px;color:var(--muted)">• {r}</span>' for r in reasons])
    
    scores = full.get('scores', {}) if isinstance(full, dict) else {}
    score_bars = ''
    for dim, label in [('price_strength','价格'), ('capital_strength','资金'), ('catalyst_strength','催化'), ('sentiment_strength','热度'), ('structure_quality','结构')]:
        val = scores.get(dim, 0) if isinstance(scores, dict) else 0
        bar_color = 'var(--red)' if val >= 60 else ('var(--gold)' if val >= 40 else 'var(--green)')
        score_bars += f'<div style="display:flex;align-items:center;gap:4px;font-size:11px;margin:1px 0"><span style="width:28px">{label}</span><div style="flex:1;height:8px;background:var(--border);border-radius:4px"><div style="width:{val}%;height:8px;background:{bar_color};border-radius:4px"></div></div><span style="width:24px;text-align:right">{val}</span></div>'
    
    html = f'''<div class="stock-box" style="border-color:var(--{color});background:rgba(248,81,73,.04)">
<h4>📊 {topic} <span class="tag {color[0]}">{stage}</span> <span style="float:right;font-size:13px;color:var(--muted)">总分{total}</span></h4>
<div style="margin:4px 0">{risk_badges}</div>
{score_bars}
<div style="margin:4px 0;font-size:12px"><strong>龙头</strong> {leader} {board}板 · <strong>涨停</strong> {zt}家</div>
<div style="margin:2px 0">{reasons_html}</div>
</div>'''
    
    return jsonify({'ok': True, 'data': {'topic': topic, 'date': analysis_date, 'html': html, 'stage': stage, 'total_score': total}})


# ════════════════════════════════════════════
# v2 API — 题材生命周期系统
# ════════════════════════════════════════════

from backend.services.pipeline import run_full_analysis, ensure_topic_id, analyze_single_topic
from backend.services.cleaner import normalize_topic_name

@app.route('/api/v2/topics')
def api_v2_topics():
    """题材总览列表 — 支持筛选、分页"""
    date_filter = request.args.get('date', date.today().strftime("%Y-%m-%d"))
    stage_filter = request.args.get('stage', '')
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    time_range = request.args.get('time_range', '')  # 10d / 30d
    
    where = "WHERE 1=1"
    params = []
    
    if stage_filter:
        stages = stage_filter.split(',')
        placeholders = ','.join(['?' for _ in stages])
        where += f" AND t.current_stage IN ({placeholders})"
        params.extend(stages)
    
    if search:
        where += " AND (t.topic_name LIKE ? OR t.topic_aliases LIKE ?)"
        params.extend([f'%{search}%', f'%{search}%'])
    
    # 先查topics表，再join scoring表获取最新评分
    sql = f"""
        SELECT t.id, t.topic_name, t.topic_aliases, t.core_logic,
               t.current_stage, t.total_score, t.last_analysis_date,
               s.price_strength, s.capital_strength, s.catalyst_strength,
               s.sentiment_strength, s.structure_quality,
               s.analysis_date as score_date, s.confidence,
               COALESCE((SELECT leader_name FROM topic_lifecycle WHERE topic_name=t.topic_name AND date=? ORDER BY id DESC LIMIT 1), '') as leader_name,
               COALESCE((SELECT center_name FROM topic_lifecycle WHERE topic_name=t.topic_name AND date=? ORDER BY id DESC LIMIT 1), '') as center_name,
               COALESCE((SELECT limit_up_count FROM topic_daily_quotes WHERE topic_id=t.id ORDER BY trade_date DESC LIMIT 1), 0) as limit_up_count
        FROM topics t
        LEFT JOIN scoring s ON s.topic_id = t.id AND s.analysis_date = (
            SELECT MAX(s2.analysis_date) FROM scoring s2 WHERE s2.topic_id = t.id
        )
        {where}
        ORDER BY t.total_score DESC, t.last_analysis_date DESC
        LIMIT ? OFFSET ?
    """
    limit_params = [date_filter, date_filter] + params + [page_size, (page - 1) * page_size]
    rows = query(sql, limit_params)
    
    # 总条数
    count_sql = f"SELECT COUNT(*) as c FROM topics t {where}"
    count_params = params if params else []
    total = query(count_sql, count_params)[0]['c']
    
    # 风险等级判断
    for r in rows:
        risks = query(
            "SELECT severity FROM topic_risk_events WHERE topic_name=? AND date=? ORDER BY id DESC LIMIT 3",
            (r['topic_name'], date_filter)
        )
        if any(rk['severity'] == 'critical' for rk in risks):
            r['risk_level'] = 'critical'
        elif risks:
            r['risk_level'] = 'warning'
        else:
            r['risk_level'] = 'none'
    
    return jsonify({
        'ok': True,
        'data': rows,
        'total': total,
        'page': page,
        'page_size': page_size,
        'filter': {'date': date_filter, 'stage': stage_filter, 'search': search},
        'stage_colors': {
            '孕育期/预热期': '#6b7280',
            '启动期': '#22c55e',
            '爆发期': '#059669',
            '分歧震荡期': '#f59e0b',
            '退潮期': '#ef4444',
            '余温反复/二波观察期': '#8b5cf6',
        }
    })


@app.route('/api/v2/topics/<int:topic_id>/detail')
def api_v2_topic_detail(topic_id):
    """题材详情 — 完整数据包"""
    analysis_date = request.args.get('date', date.today().strftime("%Y-%m-%d"))
    
    topic = query("SELECT * FROM topics WHERE id=?", (topic_id,))
    if not topic:
        return jsonify({'ok': False, 'error': '题材不存在'})
    topic = topic[0]
    
    # 评分
    scoring = query(
        "SELECT * FROM scoring WHERE topic_id=? ORDER BY analysis_date DESC LIMIT 1",
        (topic_id,)
    )
    scoring = scoring[0] if scoring else {}
    
    # 成分股
    components = query(
        "SELECT * FROM topic_components_v2 WHERE topic_id=? ORDER BY component_type",
        (topic_id,)
    )
    
    # 每日行情（近10个交易日）
    quotes = query(
        "SELECT * FROM topic_daily_quotes WHERE topic_id=? ORDER BY trade_date DESC LIMIT 10",
        (topic_id,)
    )
    
    # 催化事件
    catalysts = query(
        "SELECT * FROM catalysts WHERE topic_id=? ORDER BY event_date DESC LIMIT 20",
        (topic_id,)
    )
    
    # 热度
    heat = query(
        "SELECT * FROM heat_data WHERE topic_id=? ORDER BY stat_date DESC LIMIT 10",
        (topic_id,)
    )
    
    # 资金
    capital = query(
        "SELECT * FROM capital_flow WHERE topic_id=? ORDER BY trade_date DESC LIMIT 10",
        (topic_id,)
    )
    
    # 报告
    report = query(
        "SELECT * FROM reports WHERE topic_id=? AND analysis_date=? ORDER BY id DESC LIMIT 1",
        (topic_id, analysis_date)
    )
    report = report[0] if report else {}
    
    # 风险
    risks = query(
        "SELECT * FROM topic_risk_events WHERE topic_name=? AND date=? ORDER BY id DESC",
        (topic['topic_name'], analysis_date)
    )
    
    # 组件按角色分组
    grouped_components = {'leader_candidate': [], 'center_candidate': [], 'follow_up_candidate': [], 'core': [], 'extended': []}
    for c in components:
        ct = c.get('component_type', 'extended')
        if ct not in grouped_components:
            grouped_components[ct] = []
        grouped_components[ct].append(c)
    
    return jsonify({
        'ok': True,
        'data': {
            'topic': dict(topic),
            'scoring': scoring,
            'components': grouped_components,
            'component_list': components,
            'quotes': quotes,
            'catalysts': catalysts,
            'heat': heat,
            'capital': capital,
            'report': report,
            'risks': risks,
            'stage_colors': {
                '孕育期/预热期': '#6b7280', '启动期': '#22c55e', '爆发期': '#059669',
                '分歧震荡期': '#f59e0b', '退潮期': '#ef4444', '余温反复/二波观察期': '#8b5cf6',
            }
        }
    })


@app.route('/api/v2/topics/<int:topic_id>/quotes')
def api_v2_topic_quotes(topic_id):
    """题材行情序列"""
    days = request.args.get('days', 30, type=int)
    quotes = query(
        "SELECT * FROM topic_daily_quotes WHERE topic_id=? ORDER BY trade_date DESC LIMIT ?",
        (topic_id, days)
    )
    return jsonify({'ok': True, 'data': quotes})


@app.route('/api/v2/topics/<int:topic_id>/catalysts')
def api_v2_topic_catalysts(topic_id):
    """催化事件时间线"""
    days = request.args.get('days', 30, type=int)
    from datetime import timedelta
    start_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    catalysts = query(
        "SELECT * FROM catalysts WHERE topic_id=? AND event_date>=? ORDER BY event_date DESC",
        (topic_id, start_date)
    )
    return jsonify({'ok': True, 'data': catalysts})


@app.route('/api/v2/topics/<int:topic_id>/heat')
def api_v2_topic_heat(topic_id):
    """热度趋势"""
    days = request.args.get('days', 30, type=int)
    heat = query(
        "SELECT * FROM heat_data WHERE topic_id=? ORDER BY stat_date DESC LIMIT ?",
        (topic_id, days)
    )
    return jsonify({'ok': True, 'data': heat})


@app.route('/api/v2/topics/<int:topic_id>/capital')
def api_v2_topic_capital(topic_id):
    """资金流向"""
    days = request.args.get('days', 30, type=int)
    capital = query(
        "SELECT * FROM capital_flow WHERE topic_id=? ORDER BY trade_date DESC LIMIT ?",
        (topic_id, days)
    )
    return jsonify({'ok': True, 'data': capital})


@app.route('/api/v2/analyze', methods=['POST'])
def api_v2_analyze():
    """触发全量分析"""
    try:
        body = request.get_json(silent=True) or {}
        analysis_date = body.get('date', date.today().strftime("%Y-%m-%d"))
        topic_name = body.get('topic', '')
        
        if topic_name:
            topic_id = ensure_topic_id(topic_name)
            result = analyze_single_topic(topic_id, topic_name, analysis_date)
            return jsonify({'ok': True, 'data': result})
        else:
            results = run_full_analysis(analysis_date)
            return jsonify({'ok': True, 'data': results, 'count': len(results)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/v2/reports/<int:topic_id>')
def api_v2_report(topic_id):
    """获取题材日报Markdown"""
    analysis_date = request.args.get('date', date.today().strftime("%Y-%m-%d"))
    report = query(
        "SELECT * FROM reports WHERE topic_id=? AND analysis_date=? ORDER BY id DESC LIMIT 1",
        (topic_id, analysis_date)
    )
    if report and report[0].get('report_markdown'):
        return jsonify({'ok': True, 'data': {'markdown': report[0]['report_markdown']}})
    
    # 无报告，临时生成
    topic = query("SELECT * FROM topics WHERE id=?", (topic_id,))
    if not topic:
        return jsonify({'ok': False, 'error': '题材不存在'})
    
    scoring = query("SELECT * FROM scoring WHERE topic_id=? ORDER BY analysis_date DESC LIMIT 1", (topic_id,))
    scoring = scoring[0] if scoring else {}
    
    md = f"""# 题材日报：{topic[0]['topic_name']}

**分析日期**：{analysis_date}  
**生命周期阶段**：{scoring.get('lifecycle_stage', '未知')}  
**总分**：{scoring.get('total_score', 'N/A')}

## 五维评分
- 价格强度：{scoring.get('price_strength', 'N/A')}/100
- 资金强度：{scoring.get('capital_strength', 'N/A')}/100
- 催化强度：{scoring.get('catalyst_strength', 'N/A')}/100
- 热度强度：{scoring.get('sentiment_strength', 'N/A')}/100
- 结构质量：{scoring.get('structure_quality', 'N/A')}/100

## 风险提示
暂无风险数据。

---
*由 A股题材生命周期分析系统自动生成*
"""
    return jsonify({'ok': True, 'data': {'markdown': md}})


# ════════════════════════════════════════════
# 热门题材与主线题材监控 API
# ════════════════════════════════════════════

@app.route('/api/v2/hot-topics/rankings')
def api_hot_topic_rankings():
    """获取热门题材/主线题材/又热又强 三个排行榜"""
    analysis_date = request.args.get('date', date.today().strftime("%Y-%m-%d"))
    
    try:
        from backend.services.hot_topic_scorer import compute_all_rankings
        results = compute_all_rankings(analysis_date)
        return jsonify({'ok': True, 'data': results})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# ════════════════════════════════════════════
if __name__ == '__main__':
    init_db()
    # 首次启动 → 迁移静态数据 + 实时爬取
    existing = query("SELECT COUNT(*) as c FROM market_data")
    if existing[0]['c'] == 0:
        print("📥 首次启动，迁移初始数据...")
        from backend.seed_data import migrate_all
        migrate_all()
        print("📡 实时爬取今日数据...")
        refresh_all()
    else:
        # 非首次：检查今日是否有数据，没有则爬取
        today_count = query("SELECT COUNT(*) as c FROM market_data WHERE date=?", (date.today().strftime("%Y-%m-%d"),))
        if today_count[0]['c'] == 0:
            print("📡 今日数据尚未抓取，自动爬取...")
            refresh_all()
        else:
            print(f"✅ 今日数据已存在")
    print(f"\n🌐 访问地址: http://localhost:5500")
    app.run(host='0.0.0.0', port=5500, debug=True)
