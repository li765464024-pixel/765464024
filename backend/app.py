"""
Flask 主应用 — API 路由
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.models import query, init_db
from backend.seed_data import migrate_all

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
    """触发数据刷新"""
    try:
        ok = migrate_all()
        return jsonify({'ok': ok, 'message': '数据刷新完成' if ok else '刷新失败'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/data/versions')
def api_data_versions():
    """数据版本列表（有数据的日期）"""
    rows = query("SELECT DISTINCT date FROM market_data ORDER BY date DESC")
    return jsonify({'ok': True, 'data': [r['date'] for r in rows]})

# ── 启动 ──
if __name__ == '__main__':
    init_db()
    # 有数据才不重新迁移
    existing = query("SELECT COUNT(*) as c FROM market_data")
    if existing[0]['c'] == 0:
        print("首次启动，迁移初始数据...")
        migrate_all()
    print(f"\n🌐 访问地址: http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
