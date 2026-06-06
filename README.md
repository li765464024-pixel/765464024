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

## 已安装技能（Skills）

项目内置 `skills/` 目录下的 AI 技能模块，每个技能包含独立的 `SKILL.md` 定义调用规范。

### 原有技能
| 技能 | 目录 | 描述 |
|------|------|------|
| 陈小群视角分析 | `skills/chen-xiao-qun/` | 模仿 A 股新生代游资"陈小群"的龙头信仰交易视角 |

### 新增数据技能
| # | 技能 | 目录 | 描述 |
|---|------|------|------|
| 1 | 网页搜索 | `skills/网页搜索/` | 多平台搜索（淘股吧/韭研公社/同花顺/东财/财联社/百度） |
| 2 | 网页正文提取 | `skills/网页正文提取/` | 从 HTML 提取干净正文，去标签/去广告 |
| 3 | 浏览器操作 | `skills/浏览器操作/` | 浏览器自动化（登录/截图/动态页面渲染） |
| 4 | 表格/列表解析 | `skills/表格列表解析/` | HTML 表格→dict、涨停梯队、板块排行解析 |
| 5 | 数据清洗去重 | `skills/数据清洗去重/` | 新闻/公告去重、IQR 异常值标记 |
| 6 | 题材归一化 | `skills/题材归一化/` | 同义题材名统一、催化事件分类分级 |
| 7 | 行情数据读取 | `skills/行情数据读取/` | 从 SQLite 读取大盘/涨停/板块/资金数据 |
| 8 | 评分分类器 | `skills/评分分类器/` | 五维评分 + 六阶段生命周期分类 + 风险检测 |

各技能详细调用规范见对应目录下的 `SKILL.md`。

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

---

## v1.3 — 韭研公社数据导入器 & 按日期组织

### 新增功能
- **韭研公社数据导入**: `backend/import_jiuyan.py` — 从爬取的HTML提取帖子，按日期组织
- **日期结构化数据**: `data/raw/YYYY-MM-DD/summary.json` — 每日帖子摘要
- **自动生成Section**: 每个日期自动生成 s5(题材热度排行榜) 和 s6(韭研公社热议) 内容
- **前端日期切换**: 支持查看历史日期的韭研公社数据

### 数据导入
```bash
# 爬取最新数据 → 组织到 data/raw/ → 导入 database
python3 backend/import_jiuyan.py
```

### 历史数据查看
前端日期选择器支持任意历史日期切换，数据按 `YYYY-MM-DD` 格式组织。
