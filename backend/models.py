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

    CREATE INDEX IF NOT EXISTS idx_market_date ON market_data(date);
    CREATE INDEX IF NOT EXISTS idx_zt_date ON zt_stocks(date);
    CREATE INDEX IF NOT EXISTS idx_zt_board ON zt_stocks(board_num);
    CREATE INDEX IF NOT EXISTS idx_sectors_date ON sectors(date);
    CREATE INDEX IF NOT EXISTS idx_posts_date ON posts(date);
    CREATE INDEX IF NOT EXISTS idx_posts_platform ON posts(platform);
    CREATE INDEX IF NOT EXISTS idx_youzi_date ON youzi_analysis(date);
    CREATE INDEX IF NOT EXISTS idx_section_date ON section_html(date);
    CREATE INDEX IF NOT EXISTS idx_section_id ON section_html(section_id);
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
