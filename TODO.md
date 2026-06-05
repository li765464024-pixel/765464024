# A股题材生命周期分析系统 — 实施任务列表 (v2)

## Phase 1: 数据模型全面升级 — 9 表设计
   - [x] models.py 新增 9 张 v2 表（保持旧表兼容）
   - [x] 执行建表并验证

## Phase 2: 采集 & 清洗管道
   - [x] 创建 backend/services/collector.py（采集）
   - [x] 创建 backend/services/cleaner.py（清洗+归一化）
   - [x] 重构 scorer.py / classifier.py（从 lifecycle.py 拆出）
   - [x] 创建 backend/services/pipeline.py（全流程编排）

## Phase 3: REST API v2 端点
   - [x] 新增 GET /api/v2/topics（总览列表带筛选分页）
   - [x] 新增 GET /api/v2/topics/<id>/detail（详情完整数据）
   - [x] 新增 GET /api/v2/topics/<id>/quotes（行情序列）
   - [x] 新增 GET /api/v2/topics/<id>/catalysts（催化时间线）
   - [x] 新增 GET /api/v2/topics/<id>/heat（热度趋势）
   - [x] 新增 GET /api/v2/topics/<id>/capital（资金流向）
   - [x] 新增 POST /api/v2/analyze（触发全量分析）
   - [x] 新增 GET /api/v2/reports/<id>（日报Markdown）

## Phase 4: 前端 — 题材总览页
   - [x] frontend/topics.html 总览页面（表格+筛选+搜索）
   - [x] 生命周期颜色编码 CSS
   - [x] 集成到 index.html 新 tab

## Phase 5: 前端 — 题材详情页
   - [x] frontend/detail.html 详情页面（9区块）
   - [x] JS 渲染逻辑（评分条/时间线/热力图）

## Phase 6: 日报生成 & 系统集成
   - [x] 创建 backend/services/reporter.py
   - [x] 集成到 refresh_all() 流程
