---
name: 浏览器操作
description: 通过 browser-automation / Selenium 自动化操作浏览器 — 登录认证、动态页面抓取、截图、表单交互。适用于需要 JavaScript 渲染的 A 股数据页面（如同花顺 Level-2、东方财富动态研报）。
---

# 浏览器操作（Browser Automation）

## 用途

处理**纯 HTTP 请求无法获取**的动态页面数据：
1. 需要登录态才能访问的社区/研报页面（如淘股吧需登录查看全文）
2. JavaScript 渲染的行情图表/资金流向（如同花顺、东方财富动态页面）
3. 需交互操作才能触发的数据加载（翻页、筛选、展开更多）
4. 页面截图用于可视化验证或存档

## 前提条件

```bash
# 使用 agent-browser MCP (已在系统中可用)
# 或安装 Selenium:
pip install selenium webdriver-manager
```

## 调用方法

### 方式 A：通过 agent-browser MCP（推荐）

agent-browser 支持页面导航、点击、表单填充、截图和数据提取。调用方式：

```
run_skill({ name: "agent-browser", arguments: "<具体任务描述>" })
```

典型场景：
- "导航到同花顺板块页面，截图板块涨幅榜"
- "打开东方财富个股研报页面，提取 PDF 研报标题列表"
- "登录淘股吧，进入我的关注页面，提取关注列表"

### 方式 B：项目内 Selenium 模式

```python
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

def capture_dynamic_page(url: str, wait_selector: str = None) -> str:
    """返回渲染后的页面 HTML"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(options=options)
    driver.get(url)
    
    if wait_selector:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
        )
    
    html = driver.page_source
    driver.quit()
    return html
```

### 方式 C：截图存证

```python
driver.get("http://localhost:5500/topics.html")
driver.save_screenshot("/tmp/topics_page.png")
```

## 输出格式

```python
{
    "action": "navigate | click | fill | screenshot | extract",
    "url": "操作的页面 URL",
    "status": "success | error",
    "result": "...",           # 提取的数据 / 截图路径 / 页面 HTML
    "screenshot_path": "...",  # 如为截图操作则返回路径
}
```

## 约束

- **频率限制**：两次操作之间至少间隔 1 秒，避免被目标网站封禁
- **数据量**：单次提取正文不超过 50000 字符
- **登录态密文管理**：不要在代码中硬编码密码，使用 `.env` 环境变量
- **不可用于 DDoS/爬取攻击**：仅用于获取复盘工具所需的公开数据

## 参考文件

- agent-browser MCP 内置 skill（`/agent-browser`）
- `backend/services/crawler.py` — 项目现有爬虫（静态页面方案）
- `.env` — API 密钥配置
