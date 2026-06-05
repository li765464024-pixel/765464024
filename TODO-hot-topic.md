
# A股热门题材与主线题材监控 — 实施完成 ✅

## Phase 1: ✅ 后端 — 多平台热度采集增强
   - ✅ models.py 新增 `platform_heat` 表（10 个维度/平台）
   - ✅ collector.py 新增 `collect_platform_heat()` 四平台聚合（韭研公社/雪球/东方财富/同花顺）
   - ✅ cleaner.py 已有题材别名归一化（已覆盖低空经济/AI/芯片/机器人/新能源等 25+ 族）

## Phase 2: ✅ 后端 — 新评分引擎 + 排行计算
   - ✅ 新建 `hot_topic_scorer.py`（三种评分算法：热度分/主线强度分/综合分）

## Phase 3: ✅ 后端 — 新 API 端点
   - ✅ app.py 新增 `GET /api/v2/hot-topics/rankings`

## Phase 4: ✅ 前端 — 替换 s3 Tab HTML
   - ✅ index.html 中 s3 section 替换为三栏排行榜布局（热度/主线/综合）
   - ✅ 日期筛选 + 刷新按钮

## Phase 5: ✅ 前端 — JS 渲染逻辑
   - ✅ app.js 新增三个排行榜渲染函数（renderHotRankings/renderMainlineRankings/renderCombinedRankings）
   - ✅ 替换旧的 s3loadTopics/s3triggerAnalysis/s3changePage

## Phase 6: ✅ 集成测试
   - ✅ API 返回 200，三个排行榜正常
   - ✅ 新旧 API 兼容
   - ✅ 前端文件结构验证通过
