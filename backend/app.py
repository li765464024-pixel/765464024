"""
Flask 主应用 — API 路由
"""
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

# ── 启动 ──
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
