#!/usr/bin/env python3
"""
复盘工具 — 一键启动脚本
本地访问: http://localhost:5000
"""
import os
import sys
import webbrowser
import threading
import time

# 确保项目根目录在 PATH 中
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from backend.models import init_db, query
from backend.seed_data import migrate_all

def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://localhost:5000')

if __name__ == '__main__':
    print("╔══════════════════════════════════════════╗")
    print("║     📊 双社区全面复盘工具               ║")
    print("║     淘股吧 × 韭研公社                    ║")
    print("╚══════════════════════════════════════════╝")
    
    # 初始化数据库
    print("\n📦 初始化数据库...")
    init_db()
    
    # 检查是否有数据
    existing = query("SELECT COUNT(*) as c FROM market_data")
    if existing[0]['c'] == 0:
        print("\n📥 首次启动，从现有 HTML 迁移数据...")
        migrate_all()
    else:
        print(f"\n✅ 数据库已有 {existing[0]['c']} 条大盘记录")
    
    print("\n🚀 启动 Web 服务...")
    print(f"\n🌐 访问地址: http://localhost:5000")
    print("⌨️  按 Ctrl+C 停止服务\n")
    
    # 自动打开浏览器
    threading.Thread(target=open_browser, daemon=True).start()
    
    # 启动 Flask
    from backend.app import app
    app.run(host='0.0.0.0', port=5000, debug=False)
