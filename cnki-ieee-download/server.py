#!/usr/bin/env python3
"""
学术论文搜索下载 MCP Server — IEEE / CNKI 统一入口。

所有数据库通过 CDP 连接用户真实 Chrome，自动启动 Chrome（如未运行）。
用户手动登录一次，cookie 自动保存恢复，无需自动化表单填写。

MCP tools:
  login         - 连接 Chrome 并检测数据库登录状态
  search        - 搜索论文 (IEEE)
  detail        - 获取论文详情
  download      - 下载 PDF (IEEE: JS fetch)
  status        - CDP 连接状态 + 数据库列表
  logout        - 断开 CDP（不关闭 Chrome）
  cnki_search   - 搜索 CNKI
  cnki_login    - CNKI 登录检测 (no-op，使用 Chrome 已有登录态)
  cnki_detail   - CNKI 论文详情
  cnki_download - CNKI PDF/CAJ 下载

添加新数据库: 编辑 registry.py + 在 databases/ 下创建适配器
"""

import json
import asyncio
import os
import sys
from pathlib import Path

# Ensure project root is in Python path (MCP server may run from any CWD)
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from carsi_search.engine import CarsiAuth, log
from carsi_search.registry import list_dbs, get_db, get_adapter

# ── MCP Server 实例 ──────────────────────────────────────────────────
app = Server("cnki-ieee-download")

# ── 全局状态 ─────────────────────────────────────────────────────────
_auth = None        # CarsiAuth 实例，管理 CDP 连接
_pages = {}         # 按数据库名存储各自的 Page: {"ieee": page, "sciencedirect": page, "cnki": page}

# 从 registry 获取所有已注册数据库的名称列表，用于 tool 描述
DB_LIST = ", ".join(list_dbs())


# ══════════════════════════════════════════════════════════════════════
# Tool 定义
# ══════════════════════════════════════════════════════════════════════

@app.list_tools()
async def list_tools() -> list[Tool]:
    """注册所有 MCP 工具。每个 Tool 定义了名称、描述和参数 schema。"""
    return [
        # ── IEEE 工具 ──────────────────────────────────────────
        Tool(
            name="ieee_login",
            description="Connect Chrome via CDP and check IEEE Xplore login status. Auto-launches Chrome if needed.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="ieee_search",
            description="Search IEEE Xplore for papers. Requires prior login via ieee_login.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords"},
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="ieee_detail",
            description="Get full paper metadata from an IEEE Xplore paper page.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "IEEE paper detail page URL"},
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="ieee_download",
            description="Download a paper PDF from IEEE Xplore. Uses browser JS fetch with CARSI cookies. Saves to downloads/.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "IEEE paper detail URL (or direct PDF URL)"},
                    "title": {"type": "string", "description": "Paper title (used as filename)."},
                },
                "required": ["url"]
            }
        ),

        # ── ScienceDirect 工具 ──────────────────────────────────
        Tool(
            name="sciencedirect_login",
            description="Connect Chrome and check ScienceDirect login status. Cloudflare may require manual verification.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="sciencedirect_search",
            description="Search ScienceDirect for papers. Requires prior login via sciencedirect_login.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords"},
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="sciencedirect_detail",
            description="Get full paper metadata from a ScienceDirect article page.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "ScienceDirect article URL"},
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="sciencedirect_download",
            description="Download a paper PDF from ScienceDirect. Cloudflare may require manual verification. Saves to downloads/.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "ScienceDirect article URL or pdfft URL"},
                    "title": {"type": "string", "description": "Paper title (used as filename)."},
                },
                "required": ["url"]
            }
        ),

        # ── CNKI 工具 ───────────────────────────────────────────
        Tool(
            name="cnki_search",
            description="Search CNKI (中国知网) for papers. Supports advanced filters. Auto-connects Chrome if needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords (Chinese or English)"},
                    "author": {"type": "string", "description": "Filter by author name"},
                    "journal": {"type": "string", "description": "Filter by journal/source name"},
                    "year_start": {"type": "string", "description": "Start year (e.g. '2020')"},
                    "year_end": {"type": "string", "description": "End year (e.g. '2025')"},
                    "page": {"type": "integer", "description": "Page number (default 1)", "default": 1},
                    "sort": {"type": "string", "description": "Sort: relevance, date, citations, downloads"},
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="cnki_login",
            description="Check CNKI login status. User logs in manually in Chrome; this tool only checks and reports.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="cnki_detail",
            description="Get full paper metadata from a CNKI paper detail page.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "CNKI paper detail URL (contains kcms2/article/abstract)"},
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="cnki_download",
            description="Download a paper PDF/CAJ from CNKI. Requires user to be logged in to CNKI in Chrome.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "CNKI paper detail URL"},
                },
                "required": ["url"]
            }
        ),

        # ── 通用工具 ───────────────────────────────────────────
        Tool(
            name="status",
            description="Check CDP connection status and list available databases.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="logout",
            description="Disconnect CDP connection. Does NOT close Chrome browser.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
    ]


# ══════════════════════════════════════════════════════════════════════
# Tool 调用分发
# ══════════════════════════════════════════════════════════════════════

@app.call_tool()
async def call_tool(name: str, args: dict) -> list[TextContent]:
    """
    MCP tool 调用入口。根据 tool name 分发到对应的 handler 函数。
    每次调用自动计时，结果末尾附带耗时信息。
    """
    global _auth, _pages
    import time
    t0 = time.time()
    try:
        # IEEE 工具
        if name == "ieee_login":     result = await handle_login({"database": "ieee"})
        elif name == "ieee_search":  args["database"] = "ieee"; result = await handle_search(args)
        elif name == "ieee_detail":  args["database"] = "ieee"; result = await handle_detail(args)
        elif name == "ieee_download": args["database"] = "ieee"; result = await handle_download(args)
        # ScienceDirect 工具
        elif name == "sciencedirect_login":     result = await handle_login({"database": "sciencedirect"})
        elif name == "sciencedirect_search":  args["database"] = "sciencedirect"; result = await handle_search(args)
        elif name == "sciencedirect_detail":  args["database"] = "sciencedirect"; result = await handle_detail(args)
        elif name == "sciencedirect_download": args["database"] = "sciencedirect"; result = await handle_download(args)
        # CNKI 工具
        elif name == "cnki_search":  result = await handle_cnki_search(args)
        elif name == "cnki_login":   result = await handle_cnki_login(args)
        elif name == "cnki_detail":  result = await handle_cnki_detail(args)
        elif name == "cnki_download": result = await handle_cnki_download(args)
        # 通用工具
        elif name == "status":   result = await handle_status(args)
        elif name == "logout":   result = await handle_logout(args)
        else: return [TextContent(type="text", text=f"Unknown tool: {name}")]
        elapsed = time.time() - t0
        result[0].text += f"\n\n⏱ {elapsed:.1f}s"
        return result
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# ══════════════════════════════════════════════════════════════════════
# IEEE handler 函数
# ══════════════════════════════════════════════════════════════════════


async def handle_login(args: dict) -> list[TextContent]:
    """
    连接 Chrome 并检测数据库登录状态。
    不再自动填写表单 — 用户需在 Chrome 中手动登录，cookie 会自动保存供后续使用。

    流程：
    1. 通过 CDP 连接用户真实 Chrome（如果尚未连接）
    2. 如果有已保存的 cookie，自动注入
    3. 导航到目标数据库，检测是否已登录
    4. 已登录 → 保存 cookie，设置全局状态
    5. 未登录 → 提示用户在 Chrome 中手动登录，然后重试
    """
    global _auth, _pages

    database = args["database"]
    if database not in list_dbs():
        return [TextContent(type="text", text=f"Unknown database: {database}. Available: {DB_LIST}")]

    # 连接 Chrome CDP
    if not _auth or not _auth.context:
        _auth = CarsiAuth()
        try:
            await _auth.start()
        except RuntimeError as e:
            return [TextContent(type="text", text=str(e))]

    ctx = _auth.context
    db_config = get_db(database)
    db_label = db_config["label"]
    home_url = db_config["home_url"]
    target_domain = home_url.split("/")[2]

    # 查找已有的目标数据库标签页，或创建新页
    page = None
    for p in ctx.pages:
        if target_domain in p.url and "login" not in p.url.lower():
            page = p
            break
    if not page:
        # 创建新标签页，不复用其他数据库的页面
        page = await ctx.new_page()
        await page.goto(home_url, wait_until="domcontentloaded", timeout=30000)

    # 检测登录状态
    current_url = page.url
    is_on_login_page = any(kw in current_url.lower() for kw in ["login", "wayf", "cas", "authserver"])

    is_logged_in = False
    if not is_on_login_page and target_domain in current_url:
        try:
            page_text = await page.evaluate("() => document.body.innerText.slice(0, 5000)")
            # 检测 Cloudflare / bot 验证
            if "Are you a robot" in page_text or "Just a moment" in page_text:
                return [TextContent(type="text",
                    text=f"NEED_ACTION: {db_label} 显示了 Cloudflare 验证页面。请告诉用户在 Chrome 浏览器中手动完成验证，完成后告知你，然后重试。")]
            if database == "sciencedirect":
                # ScienceDirect: 有 "institutional Access via" = 已登录
                # 没有 "Sign in" 按钮也可能是已登录（页面结构变化时的兜底）
                has_inst = "institutional Access via" in page_text or "institutional access via" in page_text
                has_sign_in = "Sign in" in page_text and "Sign in via" not in page_text
                is_logged_in = has_inst or not has_sign_in
            elif database == "cnki":
                not_logged = "机构登录" in page_text or "校外访问" in page_text
                is_logged_in = not not_logged
            else:
                not_logged = "Institutional Sign In" in page_text
                is_logged_in = not not_logged
        except Exception:
            is_logged_in = True

    if is_logged_in:
        _pages[database] = page
        await _auth.save_state()
        return [TextContent(type="text",
            text=f"✅ 已连接 {db_label}。\n"
                 f"URL: {current_url[:120]}\n"
                 f"Cookie 已保存，下次启动自动恢复。")]
    else:
        return [TextContent(type="text",
            text=f"NEED_LOGIN: 尚未登录 {db_label}。请告诉用户在 Chrome 浏览器中手动登录 {db_label}，登录完成后告知你，然后重试。")]

async def _try_cookie_session(db: str) -> bool:
    """
    尝试通过 CDP 连接 + 已保存的 cookie 恢复会话。

    流程：
    1. 创建 CarsiAuth 实例并通过 CDP 连接用户 Chrome
    2. 自动注入已保存的 cookie（如果存在）
    3. 导航到目标数据库，检查是否已登录
    4. 成功则设置全局变量并返回 True
    """
    global _auth, _pages
    from carsi_search.engine import CarsiAuth
    auth = CarsiAuth()
    try:
        await auth.start()
    except RuntimeError:
        return False

    ctx = auth.context
    from carsi_search.registry import get_db as _get_db
    db_config = _get_db(db)
    if not db_config:
        await auth.stop()
        return False

    target_domain = db_config["home_url"].split("/")[2]
    # 查找已有标签页
    page = None
    for p in ctx.pages:
        if target_domain in p.url and "login" not in p.url.lower():
            page = p
            break
    if not page:
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(db_config["home_url"], wait_until="domcontentloaded", timeout=30000)

    # 检查是否已登录
    url = page.url
    if (target_domain in url
            and "login" not in url.lower()
            and "wayf" not in url.lower()
            and "cas" not in url.lower()):
        try:
            page_text = await page.evaluate("() => document.body.innerText.slice(0, 5000)")
            # 检测 Cloudflare
            if "Are you a robot" in page_text or "Just a moment" in page_text:
                await auth.stop()
                return False
            if db == "sciencedirect":
                has_inst = "institutional Access via" in page_text or "institutional access via" in page_text
                has_sign_in = "Sign in" in page_text and "Sign in via" not in page_text
                if not has_inst and has_sign_in:
                    await auth.stop()
                    return False
            elif db == "cnki":
                if "机构登录" in page_text or "校外访问" in page_text:
                    await auth.stop()
                    return False
            else:
                if "Institutional Sign In" in page_text:
                    await auth.stop()
                    return False
        except Exception:
            pass
        _auth = auth
        _pages[db] = page
        return True

    await auth.stop()
    return False


async def handle_search(args: dict) -> list[TextContent]:
    """
    CARSI 数据库搜索。如果没有活跃会话，先尝试从 Cookie 恢复。
    返回格式化的论文列表（标题、作者、年份、来源、摘要、URL）。
    """
    global _auth, _pages

    db = args.get("database")
    if not db:
        return [TextContent(type="text", text="No database. Use ieee_search or sciencedirect_search.")]

    # 如果没有活跃的浏览器会话，尝试从 Cookie 恢复
    if not _auth or not _pages.get(db):
        if not await _try_cookie_session(db):
            return [TextContent(type="text",
                text=f"NEED_LOGIN: {db} 未登录。请告诉用户在 Chrome 浏览器中手动登录 {db}，登录完成后告知你，然后重试此操作。")]
        log.info("[CDP] Session restored from cookies")

    adapter = await get_adapter(db, _pages[db])
    result = await adapter.search(args["query"], page=args.get("page", 1))

    if not result.get("success"):
        err = result.get("error", "")
        if err == "captcha":
            return [TextContent(type="text",
                text='NEED_ACTION: ScienceDirect 显示了 Cloudflare 验证。请告诉用户在 Chrome 浏览器中手动完成验证，完成后告知你，然后重试搜索。')]
        return [TextContent(type="text", text=f"Search failed: {err}")]

    papers = result.get("papers", [])
    if not papers:
        return [TextContent(type="text", text="No papers found. May need login or DB unavailable.")]

    total = result.get("total", "")
    total_str = f" (total: {total})" if total else ""
    page = args.get("page", 1)
    text = f"Page {page}, {len(papers)} papers{total_str}:\n\n"
    for i, p in enumerate(papers, 1):
        text += f"{i}. **{p.get('title', 'No title')}**\n"
        if p.get('authors'): text += f"   Authors: {p['authors']}\n"
        if p.get('year'): text += f"   Year: {p['year']}\n"
        if p.get('source'): text += f"   Source: {p['source']}\n"
        if p.get('abstract'): text += f"   Abstract: {p['abstract'][:200]}...\n"
        if p.get('url'): text += f"   URL: {p['url']}\n"
        text += "\n"
    text += "-> Use detail(url=URL) for full metadata"
    return [TextContent(type="text", text=text)]


async def handle_detail(args: dict) -> list[TextContent]:
    """
    获取 CARSI 数据库中论文的完整元数据。
    包括：摘要、作者、单位、年份、期刊、DOI、关键词、PDF 链接、引用格式。
    """
    global _auth, _pages

    db = args.get("database")
    if not _auth or not _pages.get(db or "ieee"):
        if not await _try_cookie_session(db or "ieee"):
            return [TextContent(type="text",
                text=f"NEED_LOGIN: 未登录。请告诉用户在 Chrome 浏览器中登录 {db or 'ieee'}，登录完成后告知你，然后重试。")]
        log.info("[CDP] Session restored from cookies")

    adapter = await get_adapter(db or "ieee", _pages[db or "ieee"])
    result = await adapter.detail(args["url"])

    if not result.get("success"):
        err = result.get("error", "")
        if err == "captcha":
            return [TextContent(type="text",
                text='NEED_ACTION: ScienceDirect 详情页显示了 Cloudflare 验证。请告诉用户在 Chrome 中手动完成验证，完成后告知你，然后重试。')]
        return [TextContent(type="text", text=f"Detail failed: {err}")]

    text = ""
    if result.get("abstract"): text += f"**Abstract**\n{result['abstract']}\n\n"
    if result.get("authors"):
        authors = result["authors"] if isinstance(result["authors"], list) else [result["authors"]]
        text += f"**Authors**: {', '.join(authors)}\n"
    if result.get("affiliation"): text += f"**Affiliation**: {result['affiliation']}\n"
    if result.get("year"): text += f"**Year**: {result['year']}\n"
    if result.get("venue"): text += f"**Publication**: {result['venue']}\n"
    if result.get("doi"): text += f"**DOI**: {result['doi']}\n"
    if result.get("keywords"):
        kws = result["keywords"] if isinstance(result["keywords"], list) else [result["keywords"]]
        text += f"**Keywords**: {', '.join(kws)}\n"
    if result.get("volume"): text += f"**Volume**: {result['volume']}\n"
    if result.get("pages"): text += f"**Pages**: {result['pages']}\n"
    if result.get("issn"): text += f"**ISSN**: {result['issn']}\n"
    if result.get("pubDate"): text += f"**Published**: {result['pubDate']}\n"
    if result.get("pdfUrl"):
        text += f"**PDF**: {result['pdfUrl']}\n"
        text += f"**Download**: use download(url=\"{result['pdfUrl']}\")\n"
    if result.get("citation"): text += f"\n**Citation**\n{result['citation']}\n"

    return [TextContent(type="text", text=text or "No details extracted.")]


async def handle_download(args: dict) -> list[TextContent]:
    """
    CARSI 数据库论文 PDF 下载处理。

    === 下载流程 ===
    1. 如果 URL 不是 PDF 直链，先调用 detail() 获取 PDF URL
    2. 将 IEEE 的 stamp.jsp URL 转换为 getPDF.jsp 直接下载端点
    3. 通过浏览器内 JS fetch 请求 PDF（利用浏览器的 CARSI 认证 Cookie）
    4. 将 PDF 二进制数据 base64 编码传回 Python
    5. 解码后验证 PDF 头 (%PDF)，防止下载到 HTML 错误页面
    6. 保存到 DOWNLOAD_DIR/downloads/ 目录，文件名为论文标题

    === 重要警告 ===
    CNKI 的下载有独立的处理函数 handle_cnki_download()，不走此路径。
    所有数据库共用同一个 CDP 连接（用户真实 Chrome）。
    """
    global _auth, _pages

    db = args.get("database")
    if not _auth or not _pages.get(db or "ieee"):
        if not await _try_cookie_session(db or "ieee"):
            return [TextContent(type="text",
                text=f"NEED_LOGIN: 未登录 {db or 'ieee'}。请告诉用户在 Chrome 浏览器中登录 {db or 'ieee'}，登录完成后告知你，然后重试下载。")]
        log.info("[CDP] Session restored from cookies")

    page = _pages[db or "ieee"]
    url = args["url"]
    title = args.get("title", "")

    # 第一步：如果 URL 不是 PDF 直链，先获取论文详情找到 PDF 链接
    if "stamp.jsp" not in url and "/pdf/" not in url and "getPDF.jsp" not in url and "pdfft" not in url:
        adapter = await get_adapter(db or "ieee", page)
        detail_result = await adapter.detail(url)
        if detail_result.get("error") == "captcha":
            return [TextContent(type="text",
                text='NEED_ACTION: ScienceDirect 下载需要验证。请告诉用户在 Chrome 浏览器中手动完成 Cloudflare 验证，完成后告知你，然后重试下载。')]
        if detail_result.get("pdfUrl"):
            url = detail_result["pdfUrl"]
        if not title and detail_result.get("title"):
            title = detail_result["title"]

    # IEEE 回退：如果 detail 没找到 pdfUrl，从 arnumber 构建
    if "/document/" in url and "getPDF" not in url:
        import re as _re
        m = _re.search(r'/document/(\d+)', url)
        if m:
            url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={m.group(1)}"

    # 第二步：将 IEEE stamp.jsp 转换为 getPDF.jsp 直接下载端点
    if "stamp.jsp" in url:
        arnumber = url.split("arnumber=")[-1] if "arnumber=" in url else ""
        if arnumber:
            url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}"

    # 第三步：通过浏览器下载 PDF
    # ScienceDirect: 需要先导航到 pdfft URL（重定向到 pdf.sciencedirectassets.com），再 fetch
    # IEEE: 直接 fetch 即可
    import base64, re

    is_sciencedirect = "sciencedirect" in url or "sciencedirectassets" in page.url

    if is_sciencedirect and "/pdfft" in url:
        # ScienceDirect: 导航到 PDF 页面，等重定向到 pdf.sciencedirectassets.com
        try: await page.unroute("**/*")
        except: pass
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # 等重定向完成
        for _ in range(20):
            await asyncio.sleep(1)
            if "sciencedirectassets" in page.url:
                break

        # 检测 Cloudflare 验证
        page_text = await page.evaluate("() => document.body?.innerText?.slice(0, 500) || ''")
        if "robot" in page_text.lower():
            for _ in range(40):
                await asyncio.sleep(3)
                page_text = await page.evaluate("() => document.body?.innerText?.slice(0, 500) || ''")
                if "robot" not in page_text.lower():
                    break
            else:
                return [TextContent(type="text",
                    text='NEED_ACTION: ScienceDirect PDF 域名显示了 Cloudflare 验证。请告诉用户在 Chrome 浏览器中手动完成验证，完成后告知你，然后重试下载。')]

        await asyncio.sleep(2)

        # 从当前 PDF 页面 fetch
        current_url = page.url
        pdf_b64 = await page.evaluate("""
            async () => {{
                try {{
                    const resp = await fetch(window.location.href);
                    if (!resp.ok) return 'HTTP ' + resp.status;
                    const buf = await resp.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    let binary = '';
                    for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
                    return btoa(binary);
                }} catch(e) {{
                    return 'ERROR:' + e.message;
                }}
            }}
        """)
    else:
        # IEEE: 直接 fetch
        try: await page.unroute("**/*")
        except: pass
        pdf_b64 = await page.evaluate(f"""
            async () => {{
                try {{
                    const resp = await fetch('{url}');
                    if (!resp.ok) return 'HTTP ' + resp.status;
                    const buf = await resp.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    let binary = '';
                    for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
                    return btoa(binary);
                }} catch(e) {{
                    return 'ERROR:' + e.message;
                }}
            }}
        """)

    if pdf_b64 and not pdf_b64.startswith('ERROR:') and not pdf_b64.startswith('HTTP '):
        pdf_data = base64.b64decode(pdf_b64)
        # 第四步：验证 PDF 文件头 —— fetch 可能返回 200 但内容是 HTML 错误页面
        if pdf_data[:4] != b'%PDF':
            # 返回的不是 PDF，可能是登录过期或权限不足导致的 HTML 页面
            snippet = pdf_data[:200].decode('utf-8', errors='replace')
            await page.goto(url.replace('getPDF.jsp', 'stamp.jsp'), wait_until="domcontentloaded", timeout=45000)
            return [TextContent(type="text",
                text=f"Download failed: response is not a PDF (可能是登录过期或权限不足).\n"
                     f"Opened page in browser for manual download.\nFirst bytes: {snippet[:100]}")]
        # 第五步：保存 PDF 到本地
        # 下载到调用者项目目录下的 downloads/ 文件夹
        downloads_dir = Path(os.getcwd()) / "downloads"
        downloads_dir.mkdir(exist_ok=True)
        if title:
            # 文件名安全处理：移除非法字符，限制长度
            safe_title = re.sub(r'[<>:"/\\|?*]', '', title).strip()
            safe_title = safe_title[:80]  # limit length
            filename = f"{safe_title}.pdf"
        else:
            filename = f"paper_{int(__import__('time').time())}.pdf"
        save_path = downloads_dir / filename
        save_path.write_bytes(pdf_data)
        return [TextContent(type="text",
            text=f"Downloaded PDF ({len(pdf_data)} bytes)\nSaved: {save_path}")]
    else:
        # 下载失败：回退到在浏览器中打开页面，让用户手动下载
        await page.goto(url.replace('getPDF.jsp', 'stamp.jsp'), wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(2)
        return [TextContent(type="text",
            text=f"Could not auto-download ({pdf_b64[:80]}). Opened in browser.\nURL: {page.url[:200]}")]


async def handle_status(args: dict) -> list[TextContent]:
    """显示当前会话状态：已注册的数据库列表、已登录的数据库、CDP 连接状态。"""
    global _auth, _pages

    lines = [f"**Registered databases**: {DB_LIST}"]
    for name in list_dbs():
        db = get_db(name)
        logged_in = name in _pages
        marker = " < logged in" if logged_in else ""
        lines.append(f"  - `{name}`: {db['label']}{marker}")

    if _auth and _auth.context:
        lines.append(f"\nCDP 连接: 已连接")
        if _pages:
            for db_name, pg in _pages.items():
                lines.append(f"  {db_name}: {pg.url[:80]}")
    else:
        lines.append("\nCDP 连接: 未连接。使用对应数据库的 login 工具连接。")

    return [TextContent(type="text", text="\n".join(lines))]


async def handle_logout(args: dict) -> list[TextContent]:
    """断开 CDP 连接，重置全局状态。不会关闭用户的真实 Chrome 浏览器。"""
    global _auth, _pages

    if _auth:
        await _auth.clear_state()
        try: await _auth.stop()
        except Exception: pass
    _auth = None
    _pages = {}
    return [TextContent(type="text", text="已断开 CDP 连接。Chrome 浏览器保持打开，下次使用需重新连接。")]


# ══════════════════════════════════════════════════════════════════════
# CNKI handler 函数
#
# CNKI 和 IEEE 共用同一个 CDP 连接。
# 知网有反爬机制，必须用真实 Chrome CDP。
# CNKI handler 首次调用时自动连接 Chrome。
# ══════════════════════════════════════════════════════════════════════


async def handle_cnki_login(args: dict) -> list[TextContent]:
    """
    CNKI 登录 —— no-op（空操作）。

    所有数据库（包括 CNKI）都通过 CDP 连接用户真实 Chrome，登录状态直接使用 Chrome 中已有的会话。
    用户只需在 Chrome 中手动登录 CNKI 即可使用 cnki_search/cnki_detail/cnki_download。
    """
    return [TextContent(type="text",
        text="所有数据库统一使用 CDP 连接真实 Chrome 的登录态，无需单独登录。\n"
             "请在 Chrome 中登录 CNKI 后直接使用 cnki_search/cnki_detail/cnki_download。")]


async def handle_cnki_search(args: dict) -> list[TextContent]:
    """
    CNKI 论文搜索。通过 CDP 连接用户真实 Chrome，打开知网搜索页，使用 CnkiAdapter 解析结果。
    搜索无需登录，但遇到验证码时需要用户在浏览器中手动完成。
    """
    global _auth, _pages
    if not _auth or not _auth.context:
        from carsi_search.engine import CarsiAuth
        _auth = CarsiAuth()
        try:
            await _auth.start()
        except RuntimeError as e:
            return [TextContent(type="text", text=str(e))]
    ctx = _auth.context
    # 优先使用已缓存的 CNKI 页面
    page = _pages.get("cnki")
    if page:
        try:
            _ = page.url  # 检查页面是否还有效
        except Exception:
            page = None
    # 查找已有的 CNKI 标签页
    if not page:
        for p in ctx.pages:
            if 'cnki.net' in p.url:
                page = p
                break
    # 创建新标签页（不复用其他数据库的页面）
    if not page:
        page = await ctx.new_page()
    _pages["cnki"] = page

    from carsi_search.databases.cnki import CnkiAdapter
    adapter = CnkiAdapter(page)
    result = await adapter.search(
        args["query"],
        author=args.get("author"),
        journal=args.get("journal"),
        year_start=args.get("year_start"),
        year_end=args.get("year_end"),
        page=args.get("page", 1),
        sort=args.get("sort"),
    )

    if not result.get("success"):
        err = result.get("error", "unknown")
        if err == "captcha":
            return [TextContent(type="text", text="CNKI 正在显示滑块验证码。请在浏览器中手动完成验证后重试。")]
        return [TextContent(type="text", text=f"CNKI search failed: {err}")]

    papers = result.get("papers", [])
    total = result.get("total", "?")
    page_info = result.get("page", "1/1")
    text = f"CNKI 搜索 \"{args['query']}\"：共 {total} 条结果 (第 {page_info} 页)\n\n"
    for i, p in enumerate(papers):
        text += f"[{i+1}] **{p.get('title', '?')}**\n"
        if p.get("authors"): text += f"    作者: {p['authors']}\n"
        if p.get("journal"): text += f"    期刊: {p['journal']}\n"
        if p.get("date"): text += f"    日期: {p['date']}\n"
        if p.get("citations"): text += f"    引用: {p['citations']}\n"
        if p.get("url"): text += f"    URL: {p['url']}\n"
        text += "\n"
    text += "→ 使用 cnki_detail(url=URL) 获取论文详情"
    return [TextContent(type="text", text=text)]


async def handle_cnki_detail(args: dict) -> list[TextContent]:
    """
    获取 CNKI 论文详情。通过 CDP 连接用户真实 Chrome，访问论文详情页，提取完整元数据。
    无需登录，但遇到验证码时需要用户手动处理。
    """
    global _auth
    if not _auth or not _auth.context:
        from carsi_search.engine import CarsiAuth
        _auth = CarsiAuth()
        try:
            await _auth.start()
        except RuntimeError as e:
            return [TextContent(type="text", text=str(e))]
    ctx = _auth.context
    # 查找已有的 CNKI 标签页复用
    page = None
    for p in ctx.pages:
        if 'cnki.net' in p.url:
            page = p
            break
    if not page:
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    from carsi_search.databases.cnki import CnkiAdapter
    adapter = CnkiAdapter(page)
    result = await adapter.detail(args["url"])

    if not result.get("success"):
        err = result.get("error", "unknown")
        if err == "captcha":
            return [TextContent(type="text", text="CNKI 验证码。请在浏览器中手动完成后重试。")]
        return [TextContent(type="text", text=f"CNKI detail failed: {err}")]

    text = ""
    if result.get("title"): text += f"**{result['title']}**\n\n"
    if result.get("authors"): text += f"**作者**: {', '.join(result['authors'])}\n"
    if result.get("affiliations"): text += f"**单位**: {', '.join(result['affiliations'])}\n"
    if result.get("journal"): text += f"**期刊**: {result['journal']}\n"
    if result.get("pubInfo"): text += f"**出版信息**: {result['pubInfo']}\n"
    if result.get("doi"): text += f"**DOI**: {result['doi']}\n"
    if result.get("abstract"): text += f"\n**摘要**\n{result['abstract']}\n"
    if result.get("keywords"): text += f"\n**关键词**: {', '.join(result['keywords'])}\n"
    if result.get("fund"): text += f"**基金**: {result['fund']}\n"
    if result.get("classification"): text += f"**分类号**: {result['classification']}\n"
    if result.get("isOnlineFirst"): text += "**状态**: 网络首发\n"
    return [TextContent(type="text", text=text or "未提取到详情")]


async def handle_cnki_download(args: dict) -> list[TextContent]:
    """
    CNKI 论文 PDF/CAJ 下载。

    === 下载流程 ===
    1. 通过共享的 CDP 连接访问用户真实 Chrome，查找或复用 CNKI 标签页
    2. 导航到论文详情页，等待页面加载
    3. 检查登录状态：如果用户未登录知网，提示先在 Chrome 中登录
    4. 检查验证码：如果出现滑块验证码，提示用户手动完成
    5. 查找下载按钮 (#pdfDown 或 .btn-dlpdf a)
    6. 使用 Playwright 的 expect_download 拦截浏览器原生下载事件
    7. 将下载的文件保存到 DOWNLOAD_DIR/downloads/ 目录

    注意：用户必须在 Chrome 中已登录 CNKI，否则无法下载。
    """
    global _auth, _pages
    if not _auth or not _auth.context:
        from carsi_search.engine import CarsiAuth
        _auth = CarsiAuth()
        try:
            await _auth.start()
        except RuntimeError as e:
            return [TextContent(type="text", text=str(e))]
    ctx = _auth.context
    # 优先使用已缓存的 CNKI 页面
    page = _pages.get("cnki")
    if page:
        try:
            _ = page.url  # 检查页面是否还有效
        except Exception:
            page = None
    # 查找已有的 CNKI 标签页
    if not page:
        for p in ctx.pages:
            if 'cnki.net' in p.url:
                page = p
                break
    # 创建新标签页（不复用其他数据库的页面）
    if not page:
        page = await ctx.new_page()
    _pages["cnki"] = page

    url = args["url"]
    from playwright.async_api import Error as PwError

    # 导航到论文详情页
    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
    try:
        await page.wait_for_selector('.brief h1', timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(1)

    # 检查登录状态：页面是否显示"机构登录"/"校外访问"（有则说明未登录）
    page_text = await page.evaluate("() => document.body.innerText.slice(0, 3000)")
    not_logged = "机构登录" in page_text or "校外访问" in page_text
    if not_logged:
        return [TextContent(type="text",
            text='NEED_LOGIN: CNKI 未登录。请告诉用户在 Chrome 浏览器中点击"机构登录"登录知网，登录完成后告知你，然后重试下载。')]

    # 检查是否出现滑块验证码
    captcha = await page.evaluate("""() => {
        const el = document.querySelector('#tcaptcha_transform_dy');
        return el && el.getBoundingClientRect().top >= 0;
    }""")
    if captcha:
        return [TextContent(type="text", text="CNKI 验证码。请在浏览器中手动完成后重试。")]

    # 检查是否有下载链接
    has_pdf = await page.evaluate("() => !!document.querySelector('#pdfDown, .btn-dlpdf a')")
    if not has_pdf:
        return [TextContent(type="text", text="未找到下载链接。")]

    # 点击下载按钮并拦截浏览器原生下载事件
    try:
        async with page.expect_download(timeout=60000) as dl_info:
            await page.locator('#pdfDown, .btn-dlpdf a').first.click()
        dl = await dl_info.value
        fname = dl.suggested_filename or 'paper.pdf'
        # 下载到调用者项目目录下的 downloads/ 文件夹
        save_path = Path(os.getcwd()) / "downloads" / fname
        save_path.parent.mkdir(exist_ok=True)
        await dl.save_as(str(save_path))

        # 验证下载内容是否为有效 PDF
        file_size = save_path.stat().st_size
        if file_size == 0:
            return [TextContent(type="text",
                text="NEED_LOGIN: CNKI 下载失败（文件为空）。请告诉用户在 Chrome 浏览器中重新登录 CNKI，登录完成后告知你，然后重试。")]

        with open(save_path, 'rb') as f:
            header = f.read(4)
        if header != b'%PDF':
            # 不是 PDF，可能是 HTML 错误页面
            with open(save_path, 'rb') as f:
                content_preview = f.read(200).decode('utf-8', errors='replace')
            save_path.unlink()  # 删除无效文件
            return [TextContent(type="text",
                text=f"CNKI 下载失败：返回的不是 PDF 文件。\n"
                     f"内容预览: {content_preview[:100]}\n"
                     f"请检查 CNKI 登录状态，或在 Chrome 中手动下载。")]

        return [TextContent(type="text",
            text=f"CNKI PDF 下载成功：{fname}\n"
                 f"大小: {file_size} bytes\n保存: {save_path}")]
    except PwError:
        return [TextContent(type="text", text="下载超时。PDF 可能已在浏览器中打开，请手动保存。")]


# ══════════════════════════════════════════════════════════════════════
# MCP Server 启动入口
# ══════════════════════════════════════════════════════════════════════

async def main():
    """通过 stdio 启动 MCP Server，等待客户端连接并处理 tool 调用请求。"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
