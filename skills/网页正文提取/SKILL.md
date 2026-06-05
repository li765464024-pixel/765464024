---
name: 网页正文提取
description: 从 HTML 页面提取干净的正文内容 — 支持多平台适配、正文清洗、标题提取。基于 crawler.py 中的 BeautifulSoup 解析模式。
---

# 网页正文提取（Web Scraper/Reader）

## 用途

从淘股吧、韭研公社、同花顺、东方财富等 A 股平台的 HTML 页面中提取**干净的正文内容**（去标签、去脚本、去广告），用于后续的主题分析、情绪分析、催化事件提取。

## 调用方法

### 方式 A：使用项目内置爬虫

```python
from backend.services.crawler import extract_text_from_html

# 直接从 HTML 字符串提取正文
raw_html = "<html>...广告...<div class='content'>正文内容</div>...</html>"
text, title = extract_text_from_html(raw_html)
# text: "正文内容"
# title: 页面标题或 None
```

### 方式 B：基于 BeautifulSoup 的通用提取

```python
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/604.1",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

def extract_page(url: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    # 移除无用标签
    for tag in soup(["script", "style", "nav", "footer", "aside", "iframe"]):
        tag.decompose()
    
    # 提取标题
    title = soup.title.string.strip() if soup.title else ""
    
    # 提取正文（优先匹配文章类容器）
    article = soup.find("article") or soup.find(class_=re.compile(r"content|article|post|main"))
    text = article.get_text(separator="\n", strip=True) if article else soup.get_text(separator="\n", strip=True)
    
    return {"title": title, "text": text[:10000], "url": url}
```

### 方式 C：从存储的 HTML 文件读取

```python
from pathlib import Path
from bs4 import BeautifulSoup

html_path = Path("社区复盘_20260604.html")
soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
```

## 输出格式

```python
{
    "title": "页面标题",
    "text": "干净正文（最长 10000 字符）",
    "url": "来源 URL",
    "extracted_at": "2025-06-04T10:30:00",
    "platform": "jiuyangongshe",   # 自动识别的平台
}
```

## 数据缺失时

- ✅ 可以告知"页面无法访问或解析失败"，给出 HTTP 状态码
- ✅ 可以尝试切换请求头 / 添加延迟重试
- ❌ 不能编造页面内容

## 参考文件

- `backend/services/crawler.py` — 项目已有的爬虫实现（`BeautifulSoup` + `requests` 模式）
- `社区复盘_*.html` — 本地存储的社区页面样本，可用于测试解析逻辑
