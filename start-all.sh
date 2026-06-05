#!/bin/bash
# ======================================================
# 复盘工具 — 一键启动 (Flask + FreeLLMAPI)
# ======================================================
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

echo "╔════════════════════════════════════════════════════╗"
echo "║     📊 双社区全面复盘 + 🧠 FreeLLMAPI             ║"
echo "╚════════════════════════════════════════════════════╝"

# ── 1. 检查/安装 Node.js ──
if ! command -v node &>/dev/null; then
    echo ""
    echo "📥 Node.js 未安装，正在下载 Node.js 22 LTS..."
    echo "   下载链接: https://nodejs.org/dist/v22.14.0/node-v22.14.0.pkg"
    echo "   或手动安装后重新运行本脚本"
    curl -L -o /tmp/node.pkg https://nodejs.org/dist/v22.14.0/node-v22.14.0.pkg
    echo "   下载完成，请双击安装 /tmp/node.pkg，然后重新运行本脚本"
    open /tmp/node.pkg
    exit 1
fi
echo "✅ Node.js $(node --version)"

# ── 2. 安装/更新 FreeLLMAPI ──
if [ ! -d "$ROOT_DIR/freellmapi" ]; then
    echo ""
    echo "📥 正在克隆 FreeLLMAPI..."
    git clone https://github.com/tashfeenahmed/freellmapi.git "$ROOT_DIR/freellmapi"
    cd "$ROOT_DIR/freellmapi"
    npm install
    echo "✅ FreeLLMAPI 安装完成"
else
    echo "✅ FreeLLMAPI 已安装"
fi

# ── 3. 配置 FreeLLMAPI ──
cd "$ROOT_DIR/freellmapi"
if [ ! -f .env ]; then
    ENCRYPTION_KEY="$(openssl rand -hex 32)"
    echo "ENCRYPTION_KEY=$ENCRYPTION_KEY" > .env
    echo "PORT=3001" >> .env
    echo "✅ FreeLLMAPI .env 已生成"
fi

# ── 4. 启动 FreeLLMAPI ──
echo ""
echo "🚀 启动 FreeLLMAPI (端口 3001)..."
if lsof -ti :3001 &>/dev/null; then
    echo "   ✅ FreeLLMAPI 已在运行"
else
    cd "$ROOT_DIR/freellmapi"
    npm run dev > /tmp/freellmapi.log 2>&1 &
    FREELM_PID=$!
    sleep 3
    if lsof -ti :3001 &>/dev/null; then
        echo "   ✅ FreeLLMAPI 启动成功 (PID $FREELM_PID)"
    else
        echo "   ⚠️ FreeLLMAPI 启动可能失败，查看日志: cat /tmp/freellmapi.log"
    fi
fi

# ── 5. 启动 Flask (端口 5500) ──
echo ""
echo "🚀 启动 Flask (端口 5500)..."
cd "$ROOT_DIR"
python3 run.py

echo ""
echo "🌐 访问地址:"
echo "   http://localhost:5500  — 复盘工具 (Flask)"
echo "   http://localhost:3001  — FreeLLMAPI 管理面板"
echo ""
echo "📋 FreeLLMAPI 使用步骤:"
echo "   1. 打开 http://localhost:3001"
echo "   2. 添加至少一个 LLM Provider 的 API Key"
echo "   3. 在 Keys 页面获取 Unified API Key"
echo "   4. 将 Key 填入 .env 的 FREELM_API_KEY"
echo "   5. 重启本脚本即可使用 AI 功能"
