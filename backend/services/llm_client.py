"""
LLM 智能分析客户端
==================
调用 FreeLLMAPI (或其他 OpenAI-compatible 端点) 提供 AI 分析能力。

FreeLLMAPI 聚合了 16 家免费 LLM 提供商，统一为 /v1/chat/completions 端点。
默认地址: http://localhost:3001/v1
支持: 文本生成、流式、Tool calling、图片理解
"""
import os
import json
import requests
from typing import Optional, List, Dict, Any

# ── 配置 ──
FREELM_BASE_URL = os.environ.get('FREELM_BASE_URL', 'http://localhost:3001/v1')
FREELM_API_KEY = os.environ.get('FREELM_API_KEY', '')
DEFAULT_MODEL = os.environ.get('FREELM_DEFAULT_MODEL', 'auto')
REQUEST_TIMEOUT = int(os.environ.get('FREELM_TIMEOUT', '60'))


def _get_headers() -> dict:
    """获取请求头"""
    headers = {"Content-Type": "application/json"}
    if FREELM_API_KEY:
        headers["Authorization"] = f"Bearer {FREELM_API_KEY}"
    return headers


def chat_completion(
    messages: List[Dict[str, Any]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
) -> Dict[str, Any]:
    """
    调用 LLM 获取对话补全

    参数:
        messages: OpenAI 格式的对话历史
        model: 模型名 (默认 "auto" 让 FreeLLMAPI 自动路由)
        temperature: 温度 0-2
        max_tokens: 最大输出 token 数
        tools: tool calling 定义
        tool_choice: "auto" / "required" / "none"
        stream: 是否流式
    返回:
        OpenAI 格式的响应 dict
    """
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice

    try:
        resp = requests.post(
            f"{FREELM_BASE_URL}/chat/completions",
            headers=_get_headers(),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        print("  ⚠️ LLM 连接失败: FreeLLMAPI 未运行在", FREELM_BASE_URL)
        return _fallback_response("LLM 服务未启动，请先启动 FreeLLMAPI")
    except Exception as e:
        print(f"  ⚠️ LLM 调用异常: {e}")
        return _fallback_response(f"LLM 分析暂时不可用: {str(e)}")


def _fallback_response(msg: str) -> dict:
    """当 LLM 不可用时的降级响应"""
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": msg,
            }
        }],
        "model": "fallback",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def extract_content(response: dict) -> str:
    """从 OpenAI 格式响应中提取文本内容"""
    try:
        return response['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        return ""


# ═══════════════════════════════════════════════
# AI 分析场景函数
# ═══════════════════════════════════════════════

def analyze_topic_sentiment(topic_name: str, posts: List[Dict]) -> Dict[str, Any]:
    """
    分析题材的社区情绪: 看多/看空/中性比例 + 核心逻辑摘要

    参数:
        topic_name: 题材名称
        posts: 相关帖子列表 [{"title":..., "author":..., "content":...}]
    返回:
        {"bull_pct": int, "bear_pct": int, "neutral_pct": int,
         "summary": str, "key_points": [str]}
    """
    if not posts:
        return {
            "bull_pct": 40, "bear_pct": 20, "neutral_pct": 40,
            "summary": "暂无社区讨论数据",
            "key_points": ["数据不足，等待更多采集"],
        }

    # 构造 prompt
    posts_text = "\n\n".join([
        f"【{p.get('author','未知')}】{p.get('title','')}"
        for p in posts[:10]
    ])

    prompt = f"""你是一位专业的 A 股短线情绪分析师。请分析以下关于题材「{topic_name}」的社区帖子，输出 JSON：

{{
  "bull_pct": 看多百分比(0-100),
  "bear_pct": 看空百分比(0-100),
  "neutral_pct": 中性百分比(0-100),
  "summary": "核心逻辑摘要(50字内)",
  "key_points": ["关键观点1", "关键观点2", "关键观点3"]
}}

帖子内容：
{posts_text}

只输出 JSON，不要其他文字。"""

    try:
        resp = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )
        content = extract_content(resp)
        # 尝试解析 JSON
        # 找到第一个 { 和最后一个 }
        start = content.find('{')
        end = content.rfind('}')
        if start >= 0 and end > start:
            return json.loads(content[start:end+1])
    except:
        pass

    # 降级
    return {
        "bull_pct": 50, "bear_pct": 20, "neutral_pct": 30,
        "summary": f"社区对{topic_name}讨论活跃",
        "key_points": [f"来自{len(posts)}篇帖子的讨论"],
    }


def generate_daily_strategy(
    market_data: Dict,
    hot_topics: List[Dict],
    sector_data: List[Dict],
) -> str:
    """
    基于市场数据生成次日的操作策略建议

    参数:
        market_data: 大盘数据
        hot_topics: 热门题材榜单
        sector_data: 板块数据
    返回:
        Markdown 格式的策略建议文本
    """
    zt = market_data.get('zt_count', 'N/A')
    dt = market_data.get('dt_count', 'N/A')
    sh = market_data.get('index_sh', 'N/A')
    vol = market_data.get('volume', 'N/A')

    topics_text = "\n".join([
        f"- {t.get('topic_name','')}: 强度{t.get('mainline_strength_score','?')}分 "
        f"龙头{t.get('leader_stock','?')} 阶段{t.get('lifecycle_stage','?')}"
        for t in hot_topics[:5]
    ])

    prompt = f"""你是一位 A 股短线交易策略师。基于今日数据，给出明日的操作建议。

今日市场：
- 涨停{zt}家 / 跌停{dt}家
- 上证指数{sh}
- 成交额{vol}

热点题材：
{topics_text}

请输出 Markdown 格式的策略，包含：
1. **大盘判断**（一句话定性）
2. **核心主线**（哪个题材最值得关注及理由）
3. **风险提示**（需要注意什么）
4. **仓位建议**（几成仓）
5. **操作方向**（具体做什么）

控制在 300 字以内。"""

    resp = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=800,
    )
    return extract_content(resp) or "LLM 分析暂不可用"


if __name__ == '__main__':
    # 测试连接
    resp = chat_completion(
        messages=[{"role": "user", "content": "你好，请用一句话说明今天 A 股的市场情绪"}],
        max_tokens=100,
    )
    print("LLM 响应:", extract_content(resp)[:200])
