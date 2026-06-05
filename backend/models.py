"""
SQLite 数据库模型
fupan.db — 复盘工具数据持久化
"""
import sqlite3
import os
from datetime import date

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'fupan.db')

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """创建所有表（幂等）"""
    conn = get_conn()
    c = conn.cursor()
    
    # ── 大盘数据 ──
    c.executescript("""
    CREATE TABLE IF NOT EXISTS market_data (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL UNIQUE,
        sentiment   TEXT,           -- 市场情绪：分化/极致分化/修复
        zt_count    INTEGER,        -- 涨停家数
        dt_count    INTEGER,        -- 跌停家数
        up_count    INTEGER,        -- 上涨家数
        down_count  INTEGER,        -- 下跌家数
        seal_rate   REAL,           -- 封板率 %
        volume      TEXT,           -- 成交额
        main_inflow TEXT,           -- 主力净额
        max_board   INTEGER,        -- 最高板
        max_board_stocks TEXT,      -- 最高板标的
        index_sh    REAL,           -- 上证指数
        index_sz    REAL,           -- 深证成指
        index_cy    REAL,           -- 创业板指
        index_kc    REAL,           -- 科创50
        temperature REAL,           -- 市场温度
        margin_balance REAL,        -- 两融余额
        yesterday_zt_count INTEGER DEFAULT 0,
        yesterday_seal_rate REAL DEFAULT 0,
        yesterday_premium REAL DEFAULT 0,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── 涨停个股 ──
    CREATE TABLE IF NOT EXISTS zt_stocks (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        code        TEXT,
        name        TEXT,
        price       REAL,
        board_num   INTEGER,        -- 几板
        seal_time   TEXT,           -- 涨停时间
        reason      TEXT,           -- 涨停原因
        seal_amount REAL,           -- 封单金额(亿)
        max_seal    REAL,           -- 最大封单(亿)
        turnovers   REAL,           -- 换手率 %
        sector      TEXT,           -- 板块
        float_mcap  REAL,           -- 实际流通(亿)
        net_inflow  REAL,           -- 主力净额(亿)
        trade_amt   REAL,           -- 成交额(亿)
        is_dragon   INTEGER DEFAULT 0,  -- 龙虎榜
        reopen_count INTEGER DEFAULT 0, -- 炸板次数(回封标记)
        board_tag   TEXT,            -- 首板/二板等标签
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── 板块热度 ──
    CREATE TABLE IF NOT EXISTS sectors (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        name        TEXT,
        zt_count    INTEGER,
        core_logic  TEXT,
        stage       TEXT,           -- 主升期/分歧/退潮
        leader      TEXT,
        score       INTEGER,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── 连板晋级率 ──
    CREATE TABLE IF NOT EXISTS board_summary (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        date            TEXT NOT NULL,
        board_num       INTEGER,    -- 几进几
        yesterday_count INTEGER,
        today_count     INTEGER,
        promotion_rate  REAL,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── 社区帖子 ──
    CREATE TABLE IF NOT EXISTS posts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        platform    TEXT,           -- taoguba / jy
        author      TEXT,
        title       TEXT,
        content     TEXT,
        direction   TEXT,           -- 看多/看空/中性
        views       INTEGER DEFAULT 0,
        comments    INTEGER DEFAULT 0,
        tags        TEXT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── 游资分析缓存 ──
    CREATE TABLE IF NOT EXISTS youzi_analysis (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        date            TEXT NOT NULL,
        youzi_name      TEXT NOT NULL,  -- 92kobe / chenxiaoqun / etc
        analysis_type   TEXT,            -- emotion / cycle / leader
        content         TEXT,            -- HTML片段
        stocks          TEXT,            -- 关联标的
        score           INTEGER,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, youzi_name, analysis_type)
    );

    -- ── Section HTML 缓存 (1:1 原始渲染) ──
    CREATE TABLE IF NOT EXISTS section_html (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        section_id  TEXT NOT NULL,   -- s0, s1, ...
        title       TEXT,
        html        TEXT NOT NULL,   -- 完整的 section div 内部 HTML
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, section_id)
    );

    -- ── 产业链分析 ──
    CREATE TABLE IF NOT EXISTS industry_chain (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        name        TEXT,
        tier        TEXT,           -- 上游/中游/耗材/设备
        link        TEXT,
        key_data    TEXT,
        leader_stock TEXT,
        score       INTEGER,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── 题材生命周期分析结果 ──
    CREATE TABLE IF NOT EXISTS topic_lifecycle (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        date            TEXT NOT NULL,
        topic_name      TEXT NOT NULL,
        lifecycle_stage TEXT,           -- 孕育期/启动期/爆发期/分歧震荡期/退潮期/余温反复期
        total_score     REAL DEFAULT 0,
        price_strength  REAL DEFAULT 0, -- 价格强度 0-100
        capital_strength REAL DEFAULT 0,-- 资金强度 0-100
        catalyst_strength REAL DEFAULT 0,-- 催化强度 0-100
        sentiment_strength REAL DEFAULT 0,-- 热度强度 0-100
        structure_quality REAL DEFAULT 0,-- 结构质量 0-100
        zt_count        INTEGER DEFAULT 0,   -- 当日涨停家数
        leader_name     TEXT,           -- 龙头股名
        leader_board    INTEGER DEFAULT 0,   -- 龙头连板数
        center_name     TEXT,           -- 中军股名
        summary_json    TEXT,           -- 完整的分析结果JSON
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, topic_name)
    );

    -- ── 题材催化事件 ──
    CREATE TABLE IF NOT EXISTS topic_catalysts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        date            TEXT NOT NULL,
        topic_name      TEXT NOT NULL,
        event_date      TEXT,           -- 事件发生日期
        title           TEXT,
        content         TEXT,
        catalyst_type   TEXT,           -- 政策/公告/订单/合作/产品/业绩/行业会议/行业数据
        catalyst_level  TEXT,           -- 国家级/部委级/地方级/公司级/媒体级
        source_name     TEXT,           -- 来源名称
        source_url      TEXT,           -- 来源链接
        is_verified     INTEGER DEFAULT 0, -- 是否已核验
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── 题材成分股 ──
    CREATE TABLE IF NOT EXISTS topic_components (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        date            TEXT NOT NULL,
        topic_name      TEXT NOT NULL,
        stock_code      TEXT,
        stock_name      TEXT,
        role            TEXT,           -- 龙头/中军/弹性/补涨/核心/扩展
        source_platform TEXT,           -- 东方财富/同花顺/问财
        board_num       INTEGER DEFAULT 0, -- 当日板数
        market_cap      REAL DEFAULT 0, -- 流通市值(亿)
        is_active       INTEGER DEFAULT 1, -- 当日是否活跃
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, topic_name, stock_code)
    );

    -- ── 题材风险事件 ──
    CREATE TABLE IF NOT EXISTS topic_risk_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        date            TEXT NOT NULL,
        topic_name      TEXT NOT NULL,
        risk_type       TEXT,           -- 监管关注/异动公告/减持/澄清/业绩不及预期/高位巨震/断板/梯队断层/板块拥挤
        stock_code      TEXT,
        stock_name      TEXT,
        description     TEXT,
        severity        TEXT DEFAULT 'warning', -- critical/warning/info
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ════════════════════════════════════════════
    -- v2 — 新系统 9 表（旧表保留兼容）
    -- ════════════════════════════════════════════

    -- 1. 题材主表
    CREATE TABLE IF NOT EXISTS topics (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_name          TEXT NOT NULL UNIQUE,
        topic_aliases       TEXT,               -- JSON array: ["低空经济","飞行汽车","eVTOL"]
        core_logic          TEXT,               -- 核心逻辑一句话
        industry_chain      TEXT,               -- 产业链环节 JSON
        first_active_date   TEXT,               -- 首次异动日期
        current_stage       TEXT,               -- 当前生命周期阶段
        total_score         REAL DEFAULT 0,
        last_analysis_date  TEXT,               -- 最近分析日期
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 2. 题材成分股表 (v2)
    CREATE TABLE IF NOT EXISTS topic_components_v2 (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id        INTEGER NOT NULL,
        stock_code      TEXT NOT NULL,
        stock_name      TEXT,
        component_type  TEXT,           -- core / extended / leader_candidate / center_candidate / follow_up_candidate
        source_platform TEXT,           -- 东方财富/同花顺/问财
        source_date     TEXT,           -- 数据采集日期
        is_active       INTEGER DEFAULT 1,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(topic_id, stock_code, component_type)
    );

    -- 3. 题材每日行情表
    CREATE TABLE IF NOT EXISTS topic_daily_quotes (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id                INTEGER NOT NULL,
        trade_date              TEXT NOT NULL,
        board_change_pct        REAL,           -- 板块涨跌幅%
        board_turnover_amount   REAL,           -- 板块成交额(亿)
        rising_stock_count      INTEGER,        -- 上涨家数
        falling_stock_count     INTEGER,        -- 下跌家数
        limit_up_count          INTEGER,        -- 涨停家数
        limit_down_count        INTEGER,        -- 跌停家数
        consecutive_board_count INTEGER,        -- 连板家数
        front_avg_change_pct    REAL,           -- 前排股平均涨幅%
        back_avg_change_pct     REAL,           -- 后排股平均涨幅%
        created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(topic_id, trade_date)
    );

    -- 4. 个股题材行情表
    CREATE TABLE IF NOT EXISTS stock_topic_quotes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id        INTEGER NOT NULL,
        trade_date      TEXT NOT NULL,
        stock_code      TEXT NOT NULL,
        stock_name      TEXT,
        change_pct      REAL,           -- 涨跌幅%
        turnover_amount REAL,           -- 成交额(亿)
        turnover_rate   REAL DEFAULT 0, -- 换手率%
        is_limit_up     INTEGER DEFAULT 0,
        is_limit_down   INTEGER DEFAULT 0,
        board_count     INTEGER DEFAULT 0,  -- 连板数
        role_tag        TEXT,           -- leader / center / elastic / follow_up
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(topic_id, trade_date, stock_code)
    );

    -- 5. 催化事件表 (v2)
    CREATE TABLE IF NOT EXISTS catalysts (
        event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id            INTEGER NOT NULL,
        event_date          TEXT NOT NULL,
        event_title         TEXT,
        event_type          TEXT,     -- policy / announcement / order / cooperation / product / earnings / conference / industry_data / media
        event_level         TEXT,     -- national / ministry / local / company / media
        related_companies   TEXT,     -- JSON数组
        is_confirmed        INTEGER DEFAULT 0,
        sentiment_direction TEXT DEFAULT 'positive', -- positive / neutral / negative
        source_name         TEXT,
        source_url          TEXT,
        raw_text            TEXT,
        cleaned_text        TEXT,
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 6. 热度表
    CREATE TABLE IF NOT EXISTS heat_data (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id                INTEGER NOT NULL,
        stat_date               TEXT NOT NULL,
        media_report_count      INTEGER DEFAULT 0,
        guba_discussion_count   INTEGER DEFAULT 0,
        xueqiu_discussion_count INTEGER DEFAULT 0,
        baidu_index_value       INTEGER DEFAULT 0,
        heat_change_1d          REAL DEFAULT 0,
        heat_change_3d          REAL DEFAULT 0,
        heat_change_7d          REAL DEFAULT 0,
        created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(topic_id, stat_date)
    );

    -- 7. 资金表
    CREATE TABLE IF NOT EXISTS capital_flow (
        id                          INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id                    INTEGER NOT NULL,
        trade_date                  TEXT NOT NULL,
        board_main_net_inflow       REAL,     -- 板块主力净流入(亿)
        leader_main_net_inflow      REAL,     -- 龙头主力净流入(亿)
        center_main_net_inflow      REAL,     -- 中军主力净流入(亿)
        lhb_stock_count             INTEGER DEFAULT 0, -- 龙虎榜上榜个股数
        institution_participation   TEXT,     -- 机构参与描述
        hot_money_participation     TEXT,     -- 游资参与描述
        northbound_change_desc      TEXT,     -- 北向资金变化描述
        created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(topic_id, trade_date)
    );

    -- 8. 评分表
    CREATE TABLE IF NOT EXISTS scoring (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id            INTEGER NOT NULL,
        analysis_date       TEXT NOT NULL,
        price_strength      REAL DEFAULT 0,
        capital_strength    REAL DEFAULT 0,
        catalyst_strength   REAL DEFAULT 0,
        sentiment_strength  REAL DEFAULT 0,
        structure_quality   REAL DEFAULT 0,
        total_score         REAL DEFAULT 0,
        lifecycle_stage     TEXT,
        confidence          REAL DEFAULT 0.5,  -- 置信度 0-1
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(topic_id, analysis_date)
    );

    -- 9. 报告表
    CREATE TABLE IF NOT EXISTS reports (
        id                              INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id                        INTEGER NOT NULL,
        analysis_date                   TEXT NOT NULL,
        lifecycle_stage                 TEXT,
        summary_text                    TEXT,
        judgement_reasons               TEXT,     -- JSON数组
        risk_warnings                   TEXT,     -- JSON数组
        next_observation_points         TEXT,     -- JSON数组
        second_wave_trigger_conditions  TEXT,     -- JSON数组
        report_json                     TEXT,     -- 完整JSON
        report_markdown                 TEXT,     -- Markdown格式
        created_at                      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(topic_id, analysis_date)
    );

    CREATE INDEX IF NOT EXISTS idx_market_date ON market_data(date);
    CREATE INDEX IF NOT EXISTS idx_zt_date ON zt_stocks(date);
    CREATE INDEX IF NOT EXISTS idx_zt_board ON zt_stocks(board_num);
    CREATE INDEX IF NOT EXISTS idx_sectors_date ON sectors(date);
    CREATE INDEX IF NOT EXISTS idx_posts_date ON posts(date);
    CREATE INDEX IF NOT EXISTS idx_posts_platform ON posts(platform);
    CREATE INDEX IF NOT EXISTS idx_youzi_date ON youzi_analysis(date);
    CREATE INDEX IF NOT EXISTS idx_section_date ON section_html(date);
    CREATE INDEX IF NOT EXISTS idx_section_id ON section_html(section_id);
    CREATE INDEX IF NOT EXISTS idx_topic_date ON topic_lifecycle(date);
    CREATE INDEX IF NOT EXISTS idx_topic_name ON topic_lifecycle(topic_name);
    CREATE INDEX IF NOT EXISTS idx_catalyst_topic ON topic_catalysts(topic_name);
    CREATE INDEX IF NOT EXISTS idx_comp_topic ON topic_components(topic_name);
    CREATE INDEX IF NOT EXISTS idx_risk_topic ON topic_risk_events(topic_name);
    CREATE INDEX IF NOT EXISTS idx_topics_name ON topics(topic_name);
    CREATE INDEX IF NOT EXISTS idx_topics_stage ON topics(current_stage);
    CREATE INDEX IF NOT EXISTS idx_comp_v2_topic ON topic_components_v2(topic_id);
    CREATE INDEX IF NOT EXISTS idx_daily_quotes_topic ON topic_daily_quotes(topic_id);
    CREATE INDEX IF NOT EXISTS idx_daily_quotes_date ON topic_daily_quotes(trade_date);
    CREATE INDEX IF NOT EXISTS idx_stock_quotes_topic ON stock_topic_quotes(topic_id);
    CREATE INDEX IF NOT EXISTS idx_catalysts_topic ON catalysts(topic_id);
    CREATE INDEX IF NOT EXISTS idx_catalysts_date ON catalysts(event_date);
    CREATE INDEX IF NOT EXISTS idx_heat_topic ON heat_data(topic_id);
    CREATE INDEX IF NOT EXISTS idx_capital_topic ON capital_flow(topic_id);
    CREATE INDEX IF NOT EXISTS idx_scoring_topic ON scoring(topic_id);
    CREATE INDEX IF NOT EXISTS idx_scoring_date ON scoring(analysis_date);
    CREATE INDEX IF NOT EXISTS idx_reports_topic ON reports(topic_id);

    -- 10. 平台热度表 — 按平台存储独立热度指标
    CREATE TABLE IF NOT EXISTS platform_heat (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id        INTEGER NOT NULL,
        topic_name      TEXT NOT NULL,
        platform        TEXT NOT NULL,   -- jygs / xueqiu / eastmoney / ths
        stat_date       TEXT NOT NULL,
        mention_count   INTEGER DEFAULT 0,
        article_count   INTEGER DEFAULT 0,
        comment_count   INTEGER DEFAULT 0,
        like_count      INTEGER DEFAULT 0,
        favorite_count  INTEGER DEFAULT 0,
        share_count     INTEGER DEFAULT 0,
        hot_rank        INTEGER DEFAULT 0,
        heat_change_1d  REAL DEFAULT 0,
        heat_change_3d  REAL DEFAULT 0,
        heat_change_7d  REAL DEFAULT 0,
        extra_data      TEXT,           -- JSON 扩展字段
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(topic_id, platform, stat_date)
    );
    CREATE INDEX IF NOT EXISTS idx_plat_heat_topic ON platform_heat(topic_id);
    CREATE INDEX IF NOT EXISTS idx_plat_heat_date ON platform_heat(stat_date);
    CREATE INDEX IF NOT EXISTS idx_plat_heat_plat ON platform_heat(platform);
    """)
    conn.commit()
    conn.close()
    print("✓ 数据库表初始化完成")

def query(sql, params=None):
    conn = get_conn()
    c = conn.cursor()
    if params:
        c.execute(sql, params)
    else:
        c.execute(sql)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def execute(sql, params=None):
    conn = get_conn()
    c = conn.cursor()
    if params:
        c.execute(sql, params)
    else:
        c.execute(sql)
    conn.commit()
    conn.close()

def insert(table, data):
    """插入一行数据"""
    cols = ', '.join(data.keys())
    phs = ', '.join(['?' for _ in data])
    sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({phs})"
    execute(sql, list(data.values()))

def insert_many(table, rows):
    """批量插入"""
    if not rows:
        return
    cols = ', '.join(rows[0].keys())
    phs = ', '.join(['?' for _ in rows[0]])
    sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({phs})"
    conn = get_conn()
    c = conn.cursor()
    c.executemany(sql, [list(r.values()) for r in rows])
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("数据库路径:", DB_PATH)
