# 📊 双社区全面复盘工具

淘股吧 × 韭研公社 — A股每日复盘系统

## 架构

```
复盘工具/
├── backend/                  # Flask 后端
│   ├── app.py                # API 路由 (RESTful)
│   ├── models.py             # SQLite 数据库模型
│   └── seed_data.py          # 数据迁移 (HTML→DB)
├── frontend/                 # 前端 (纯静态)
│   ├── index.html            # 主页面
│   ├── css/style.css         # 暗色主题样式
│   └── js/app.js             # 交互逻辑 + API调用
├── data/fupan.db             # SQLite 数据库 (自动生成)
├── run.py                    # 一键启动脚本
├── requirements.txt          # Python 依赖
└── start.sh                  # 快速启动 (bash)
```

## 一键启动

```bash
# 首次 (安装依赖)
pip3 install flask flask-cors requests

# 启动
python3 run.py
# 或
bash start.sh
```

浏览器访问: **http://localhost:5500**

## API 接口

| 端点 | 用途 |
|------|------|
| `GET /api/market/today` | 今日大盘数据 |
| `GET /api/board/list?board=1` | 指定板次涨停个股 |
| `GET /api/board/summary` | 连板晋级率汇总 |
| `GET /api/sectors/hot` | 板块热度排行 |
| `GET /api/posts?platform=taoguba` | 淘股吧帖子 |
| `GET /api/posts?platform=jy` | 韭研公社帖子 |
| `POST /api/market/refresh` | 触发数据刷新 |
| `GET /api/data/versions` | 数据版本列表 |

## 版本管理

```bash
# 查看版本
git tag

# 发布新版本
git tag v1.2        # 打标签
git push origin v1.2  # 推送 (如有远程仓库)

# 回退到指定版本
git checkout v1.0
```

## 改版流程

1. 修改前端文件 (`frontend/`)
2. `git add -A && git commit -m "v1.X: 改动说明"`
3. `git tag v1.X`
4. 刷新浏览器 (自动加载最新)

数据独立存储于 `data/fupan.db`，改版不影响历史数据。

## 端口说明

默认端口 **5500** (macOS 上 5000 被 AirPlay Receiver 占用)。如需修改端口，改 `backend/app.py` 和 `frontend/js/app.js` 中的端口号。
