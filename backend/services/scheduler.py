
"""
收盘自动调度器 (v1)
===================
A股收盘 15:01 自动触发全量数据采集 → 分析 → Git 推送
"""
import os, sys, time, threading, json
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.models import query, execute
from backend.services.mcp_engine import mcp_call, is_trading_day, TODAY

# ── 配置 ──
CHECK_INTERVAL = 30  # 每30秒检查一次
CLOSE_TIME = "15:01"
GIT_REPO = "/Users/a8888/Desktop/复盘工具"
REMOTE = "origin"
BRANCH = "main"
GITHUB_TAGS_URL = "https://github.com/li765464024-pixel/765464024/tags"

def get_latest_tag():
    """获取最新版本号"""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "tag", "-l", "--sort=-version:refname"],
            capture_output=True, text=True, cwd=GIT_REPO, timeout=10
        )
        tags = [t.strip() for t in result.stdout.split('\n') if t.strip()]
        return tags[0] if tags else "v6.0"
    except:
        return "v6.0"

def bump_version(tag):
    """版本号+0.1（支持多位数版本 v6.10->v6.11）"""
    try:
        parts = tag.replace('v', '').split('.')
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        minor += 1
        return f"v{major}.{minor}"
    except:
        return "v7.1"

def sync_frontend_version(new_version):
    """同步前端版本号"""
    html_path = os.path.join(GIT_REPO, "frontend", "index.html")
    try:
        with open(html_path, 'r') as f:
            content = f.read()
        import re
        content = re.sub(r'<span id="ver-status">v[\d.]+</span>',
                        f'<span id="ver-status">{new_version}</span>',
                        content)
        with open(html_path, 'w') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"  ⚠️ 版本同步失败: {e}")
        return False

def git_commit_push(new_version, today):
    """Git 提交 & 推送"""
    import subprocess
    cmds = [
        ["git", "add", "-A"],
        ["git", "commit", "-m", f"{new_version}: 自动更新 {today}"],
        ["git", "tag", new_version],
        ["git", "push", REMOTE, BRANCH],
        ["git", "push", REMOTE, new_version],
    ]
    results = []
    for cmd in cmds:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=GIT_REPO, timeout=30)
            results.append((cmd[0], r.returncode, r.stdout[:100]))
        except Exception as e:
            results.append((cmd[0], -1, str(e)))
    return results

def run_full_update():
    """
    收盘后全量更新流程
    涨停池 → 大盘数 → 财联社 → 韭研公社 → 淘股吧 → v2分析 → 日报 → 重建页面 → Git推送
    """
    today = date.today().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M:%S")
    
    print(f"\n{'='*50}")
    print(f"📊 收盘自动更新 [{today} {now}]")
    print(f"{'='*50}")
    
    # 1. 检查是否为交易日
    if not is_trading_day(today):
        print(f"  ⏭️ {today} 非交易日，跳过")
        return False
    
    # 2. 导入并执行完整更新（自动Git推送）
    try:
        from backend.services.crawler import refresh_all
        results = refresh_all(git_push=True)
        
        # 3. 版本管理
        latest_tag = get_latest_tag()
        new_version = bump_version(latest_tag)
        print(f"  📌 版本: {latest_tag} → {new_version}")
        
        sync_frontend_version(new_version)
        print(f"  ✅ 前端版本已同步: {new_version}")
        
        git_results = git_commit_push(new_version, today)
        for action, code, msg in git_results:
            status = "✅" if code == 0 else "❌"
            print(f"  {status} {action}: {msg[:80]}")
        
        print(f"\n  🌐 GitHub Tags: {GITHUB_TAGS_URL}")
        print(f"{'='*50}\n")
        return True
    except Exception as e:
        print(f"  ❌ 更新失败: {e}")
        return False


def scheduler_loop():
    """守护线程：每秒检查时间"""
    print(f"  ⏰ 收盘调度器已启动 (每天 {CLOSE_TIME} 触发)")
    print(f"  🔍 检查间隔: {CHECK_INTERVAL}秒")
    print(f"  🌐 GitHub: {GITHUB_TAGS_URL}")
    
    last_run_date = ""
    
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            
            # 15:01-15:05 之间触发，每天只跑一次
            if (now.hour == 15 and now.minute == 1 and today_str != last_run_date):
                last_run_date = today_str
                run_full_update()
            
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print(f"  ⚠️ 调度器异常: {e}")
            time.sleep(60)


def start_scheduler():
    """启动调度器线程"""
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    return t


if __name__ == '__main__':
    print("📊 收盘自动更新工具")
    print("  1. 立即运行全量更新")
    print("  2. 启动调度器 (15:01自动触发)")
    choice = input("请选择 (1/2): ").strip()
    if choice == '2':
        print("  ⏰ 调度器运行中...")
        scheduler_loop()
    else:
        run_full_update()
