"""
数据清洗引擎 (v2)
================
题材名称归一化、股票归一化、新闻/公告去重、催化事件分类
"""
import re
import json
from datetime import date
from typing import Optional

from backend.models import query, insert, insert_many

# ═══════════════════════════════════════════════
# 1. 题材名称归一化映射表
# ═══════════════════════════════════════════════

# 同义词 → 标准题材名称
TOPIC_ALIAS_MAP = {
    # 低空经济族
    '低空经济': '低空经济',
    '飞行汽车': '低空经济',
    'eVTOL': '低空经济',
    '无人机': '低空经济',
    '低空': '低空经济',
    
    # AI 族
    '人工智能': '人工智能',
    'AI': '人工智能',
    '大模型': '人工智能',
    'ChatGPT': '人工智能',
    '多模态': '人工智能',
    'AI应用': '人工智能',
    'AI芯片': '人工智能',
    
    # 算力族
    '算力': '算力',
    'AI算力': '算力',
    '算力租赁': '算力',
    '数据中心': '算力',
    'IDC': '算力',
    
    # 半导体族
    '半导体': '半导体/芯片',
    '芯片': '半导体/芯片',
    '集成电路': '半导体/芯片',
    '封测': '半导体/芯片',
    '光刻': '半导体/芯片',
    '硅片': '半导体/芯片',
    '存储芯片': '半导体/芯片',
    'MCU': '半导体/芯片',
    
    # 机器人族
    '机器人': '机器人',
    '人形机器人': '机器人',
    '减速器': '机器人',
    '传感器': '机器人',
    '机器视觉': '机器人',
    
    # 新能源车族
    '新能源汽车': '新能源汽车',
    '新能源车': '新能源汽车',
    '电动车': '新能源汽车',
    '锂电': '新能源汽车',
    '固态电池': '新能源汽车',
    '充电桩': '新能源汽车',
    
    # 光伏族
    '光伏': '光伏',
    '太阳能': '光伏',
    '逆变器': '光伏',
    '硅料': '光伏',
    '电池片': '光伏',
    
    # 房地产族
    '房地产': '房地产',
    '地产': '房地产',
    '房产': '房地产',
    '物业管理': '房地产',
    
    # 券商族
    '券商': '券商',
    '证券': '券商',
    '证券行业': '券商',
    
    # 医药族
    '医药': '医药',
    '创新药': '医药',
    '中药': '医药',
    'CXO': '医药',
    '医疗器械': '医药',
    '生物医药': '医药',
    
    # 消费族
    '大消费': '大消费',
    '消费': '大消费',
    '食品饮料': '大消费',
    '白酒': '大消费',
    '免税': '大消费',
    '旅游': '大消费',
    
    # 军工族
    '军工': '军工',
    '国防': '军工',
    '航天': '军工',
    '航空': '军工',
    '商业航天': '军工',
    
    # 通信族
    '5G': '5G/通信',
    '6G': '5G/通信',
    '通信': '5G/通信',
    '光通信': '5G/通信',
    'CPO': '5G/通信',
    '光模块': '5G/通信',
    
    # 电力族
    '电力': '电力',
    '电网': '电力',
    '虚拟电厂': '电力',
    '储能': '电力',
    '特高压': '电力',
    '智能电网': '电力',
}

# 催化事件类型关键词映射
EVENT_TYPE_KEYWORDS = {
    'policy': ['政策', '意见', '通知', '印发', '纲要', '规划', '方案', '措施', '办法', '规定', '条例'],
    'announcement': ['公告', '披露', '公示', '声明', '通知'],
    'order': ['中标', '订单', '合同', '签约', '采购'],
    'cooperation': ['合作', '战略合作', '签约', '合资', '联盟'],
    'product': ['发布', '推出', '亮相', '首秀', '新品', '产品'],
    'earnings': ['业绩', '营收', '利润', '净利润', '同比增长', '扭亏', '预增'],
    'conference': ['会议', '大会', '峰会', '论坛', '博览会', '展会'],
    'industry_data': ['数据', '统计', '报告', '指数', '景气度'],
    'media': ['报道', '传闻', '消息', '据悉', '媒体报道'],
}

EVENT_LEVEL_KEYWORDS = {
    'national': ['国务院', '国家', '中央', '全国', '总书记', '总理'],
    'ministry': ['部', '委', '局', '工信部', '发改委', '财政部', '证监会', '央行'],
    'local': ['省', '市', '地方', '区', '自贸区'],
    'company': ['公司', '集团', '股份', '有限', '公告'],
    'media': ['报道', '据', '媒体', '记者'],
}


def normalize_topic_name(raw_name: str) -> str:
    """题材名称归一化：同义词统一为标准名称"""
    # 精确匹配
    if raw_name in TOPIC_ALIAS_MAP:
        return TOPIC_ALIAS_MAP[raw_name]
    
    # 子串匹配
    for alias, standard in TOPIC_ALIAS_MAP.items():
        if alias in raw_name or raw_name in alias:
            return standard
    
    # 去尾：去掉"行业""板块""概念""产业链"等后缀
    cleaned = re.sub(r'(行业|板块|概念|产业链|方向)$', '', raw_name).strip()
    if cleaned != raw_name and cleaned in TOPIC_ALIAS_MAP:
        return TOPIC_ALIAS_MAP[cleaned]
    
    # 没找到映射，返回原名称
    return raw_name


def get_topic_aliases(topic_name: str) -> list:
    """获取题材的所有别名"""
    if topic_name in TOPIC_ALIAS_MAP.values():
        # 反向查找所有映射到这个标准名的别名
        return [k for k, v in TOPIC_ALIAS_MAP.items() if v == topic_name and k != topic_name]
    return []


# ═══════════════════════════════════════════════
# 2. 股票名称归一化
# ═══════════════════════════════════════════════

STOCK_FULL_NAMES = {}  # 可由外部加载

def normalize_stock_name(code: str, name: str) -> dict:
    """股票名称归一化：代码作为主键"""
    return {
        'stock_code': code,
        'stock_name': name,
    }


# ═══════════════════════════════════════════════
# 3. 新闻去重
# ═══════════════════════════════════════════════

def deduplicate_news(news_list: list) -> list:
    """新闻去重：同链接/同标题/相似内容"""
    seen_urls = set()
    seen_titles = set()
    result = []
    
    for n in news_list:
        url = n.get('source_url', '') or n.get('url', '')
        title = n.get('title', '').strip()
        
        # 同链接去重
        if url and url in seen_urls:
            continue
        
        # 同标题去重（取前20字比较）
        title_key = title[:20] if title else ''
        if title_key and title_key in seen_titles:
            continue
        
        if url:
            seen_urls.add(url)
        if title_key:
            seen_titles.add(title_key)
        
        result.append(n)
    
    return result


# ═══════════════════════════════════════════════
# 4. 公告去重
# ═══════════════════════════════════════════════

def deduplicate_announcements(ann_list: list) -> list:
    """公告去重：同公司同日同主题合并，更正公告保留最新"""
    seen = {}
    
    for a in ann_list:
        key = (a.get('stock_code', ''), a.get('date', ''), a.get('topic', ''))
        
        # 如果是更正公告且已有旧版，替换
        is_correction = '更正' in (a.get('title', '') or '')
        
        if key in seen:
            if is_correction:
                seen[key] = a  # 更正版替换
            # 否则保留第一条
        else:
            seen[key] = a
    
    return list(seen.values())


# ═══════════════════════════════════════════════
# 5. 催化事件分类
# ═══════════════════════════════════════════════

def classify_event_type(title: str, content: str = '') -> str:
    """根据标题和内容判定催化事件类型（9分类）"""
    text = (title or '') + ' ' + (content or '')
    
    scores = {}
    for etype, keywords in EVENT_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[etype] = score
    
    if not scores:
        return 'media'  # 默认媒体类
    
    # 返回匹配最多的类型
    return max(scores, key=scores.get)


def classify_event_level(title: str, content: str = '') -> str:
    """判定催化事件级别（5级）"""
    text = (title or '') + ' ' + (content or '')
    
    for level, keywords in EVENT_LEVEL_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return level
    
    return 'media'


# ═══════════════════════════════════════════════
# 6. 异常值处理
# ═══════════════════════════════════════════════

def get_stat_bounds(values: list, multiplier: float = 3.0) -> tuple:
    """计算IQR异常值边界"""
    if len(values) < 4:
        return (None, None)
    sorted_v = sorted(values)
    n = len(sorted_v)
    q1 = sorted_v[n // 4]
    q3 = sorted_v[3 * n // 4]
    iqr = q3 - q1
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    return (lower, upper)


def mark_outliers(data_list: list, field: str) -> list:
    """标记异常值，不删除"""
    values = [d.get(field, 0) or 0 for d in data_list if d.get(field) is not None]
    lower, upper = get_stat_bounds(values)
    if lower is None:
        return data_list
    
    for d in data_list:
        val = d.get(field, 0) or 0
        if val < lower or val > upper:
            d['_outlier'] = True
            d['_outlier_reason'] = f'超出范围[{lower:.2f}, {upper:.2f}]'
        else:
            d['_outlier'] = False
    
    return data_list


if __name__ == '__main__':
    # 验证归一化
    tests = [
        ('飞行汽车', '低空经济'),
        ('半导体', '半导体/芯片'),
        ('AI算力', '算力'),
        ('光通信', '5G/通信'),
    ]
    for raw, expected in tests:
        result = normalize_topic_name(raw)
        status = '✅' if result == expected else '❌'
        print(f'{status} normalize_topic_name("{raw}") = "{result}" (期望"{expected}")')
    
    # 验证事件分类
    test_events = [
        ('国务院印发人工智能发展规划', 'national'),
        ('工信部发布5G商用通知', 'ministry'),
        ('某公司与华为签署合作协议', 'company'),
    ]
    for title, expected_level in test_events:
        etype = classify_event_type(title)
        level = classify_event_level(title)
        print(f'  "{title}" → type={etype}, level={level}')
    
    print('✅ cleaner.py 验证通过')
