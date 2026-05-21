#!/usr/bin/env python3
"""
CARSI Academic Database Search MCP Server

=== 架构概览 ===

本文件是学术论文搜索 MCP Server 的主入口，提供两大类工具：

1. CARSI 模式 (IEEE / 万方智搜):
   - 使用 Playwright 启动无头浏览器，通过西安电子科技大学 CARSI 认证登录数据库
   - 登录成功后保持 session，后续搜索/下载复用同一浏览器实例
   - Cookie 状态持久化到磁盘，下次启动可自动恢复会话
   - 下载方式：浏览器内 fetch + base64 解码 → 写入本地文件

2. CNKI 模式 (中国知网):
   - 通过 CDP (Chrome DevTools Protocol) 连接用户已打开的真实 Chrome 浏览器
   - 不使用 Playwright 自带浏览器，因为知网有反爬机制会拦截 Playwright
   - 用户需先用 --remote-debugging-port=9222 启动 Chrome，并在 Chrome 中登录知网
   - 搜索无需登录，下载需要用户已登录 CNKI
   - 下载方式：Playwright expect_download 拦截浏览器原生下载

3. S2 模式 (Semantic Scholar):
   - 不在本文件中实现，由 Skill 层通过 curl 调用 Semantic Scholar API
   - 详见 skills/scholar/SKILL.md

MCP tools:
  login         - 通过 CARSI 认证登录学术数据库 (IEEE/万方)
  search        - 在当前数据库中搜索论文
  detail        - 获取论文详情 + PDF 链接
  download      - 下载论文 PDF 到本地
  status        - 检查会话状态、列出可用数据库
  logout        - 清除保存的会话
  cnki_search   - 搜索中国知网论文 (无需登录)
  cnki_login    - CNKI 登录 (现已为 no-op，使用 Chrome 已有登录态)
  cnki_detail   - 获取 CNKI 论文详情
  cnki_download - 从 CNKI 下载 PDF/CAJ (需已在 Chrome 中登录知网)

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

from carsi_search.engine import CarsiAuth
from carsi_search.registry import list_dbs, get_db

# ── MCP Server 实例 ──────────────────────────────────────────────────
app = Server("carsi-search-mcp")

# ── 全局状态 ─────────────────────────────────────────────────────────
_auth = None        # CarsiAuth 实例，管理 Playwright 浏览器和 CARSI 登录
_page = None        # 当前活跃的 Playwright Page 对象 (CARSI 模式)
_current_db = None  # 当前激活的数据库名称 ("ieee" / "zhizhen")

# 从 registry 获取所有已注册数据库的名称列表，用于 tool 描述
DB_LIST = ", ".join(list_dbs())


# ══════════════════════════════════════════════════════════════════════
# Tool 定义
# ══════════════════════════════════════════════════════════════════════

@app.list_tools()
async def list_tools() -> list[Tool]:
    """注册所有 MCP 工具。每个 Tool 定义了名称、描述和参数 schema。"""
    return [
        # ── CARSI 模式工具 ──────────────────────────────────────────
        # login: 通过 CARSI (中国教育网联邦认证) 登录到学术数据库
        # 适用场景：首次使用 IEEE 或万方智搜时需要先登录
        # 登录后 session 会持久化到磁盘，下次启动可自动恢复
        Tool(
            name="login",
            description=f"Login to an academic database via CARSI (Xidian University). Available: {DB_LIST}. Username/password are optional if XIDIAN_USERNAME/XIDIAN_PASSWORD env vars are set.",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": f"Database key: {DB_LIST}"},
                    "username": {"type": "string", "description": "Xidian student/staff ID"},
                    "password": {"type": "string", "description": "Xidian unified auth password"},
                    "headless": {"type": "boolean", "description": "Headless mode", "default": False},
                    "force": {"type": "boolean", "description": "Force re-login", "default": False},
                },
                "required": ["database"]
            }
        ),
        # search: 在已登录的 CARSI 数据库中搜索论文
        # 返回标题、作者、摘要、URL 等信息，支持分页
        Tool(
            name="search",
            description="Search papers in the current database. Returns title, authors, abstract, URL for each paper.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords"},
                    "database": {"type": "string", "description": f"Database override. {DB_LIST}"},
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                },
                "required": ["query"]
            }
        ),
        # detail: 获取论文的完整元数据，包括摘要、作者、DOI、PDF 链接等
        # 通常在 search 之后调用，传入论文的 URL 获取详情
        Tool(
            name="detail",
            description="Get full paper metadata: abstract, authors, affiliation, keywords, DOI, PDF link, citation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Paper detail page URL"},
                    "database": {"type": "string", "description": f"Database key. {DB_LIST}"},
                },
                "required": ["url"]
            }
        ),
        # download: 下载论文 PDF 到项目目录
        # 对于 CARSI 数据库：通过浏览器 JS fetch + base64 解码保存
        # 注意：CNKI 有独立的下载处理函数，不走此路径
        Tool(
            name="download",
            description="Download a paper PDF to the project's downloads/ directory with the paper title as filename.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Paper detail URL (or direct PDF URL)"},
                    "title": {"type": "string", "description": "Paper title (used as filename). If omitted, extracted from the page."},
                    "database": {"type": "string", "description": f"Database key. {DB_LIST}"},
                },
                "required": ["url"]
            }
        ),
        # status: 查看当前会话状态，列出所有可用数据库及当前激活的数据库
        Tool(
            name="status",
            description="Check session status and list available databases.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        # logout: 清除保存的 Cookie 会话，下次操作需要重新登录
        Tool(
            name="logout",
            description="Clear saved session cookies.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),

        # ── CNKI 模式工具 ───────────────────────────────────────────
        # cnki_search: 搜索中国知网论文
        # 无需登录即可使用，支持作者/期刊/年份/排序等高级筛选
        # 通过 CDP 连接用户真实 Chrome，使用 CnkiAdapter 执行搜索
        Tool(
            name="cnki_search",
            description="Search CNKI (中国知网) for papers. No login required. Supports advanced filters.",
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
        # cnki_login: CNKI 登录工具
        # 目前已变为 no-op：CNKI 使用用户 Chrome 浏览器中已有的登录态
        # 保留此 tool 是为了向后兼容，调用时会提示用户在 Chrome 中登录
        Tool(
            name="cnki_login",
            description="Login to CNKI via CARSI (Xidian University off-campus access). Opens browser. Required for PDF/CAJ download.",
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Xidian student/staff ID (optional if env var set)"},
                    "password": {"type": "string", "description": "Xidian password (optional if env var set)"},
                },
                "required": []
            }
        ),
        # cnki_detail: 获取 CNKI 论文的完整元数据
        # 无需登录，通过 CDP Chrome 访问知网论文详情页
        Tool(
            name="cnki_detail",
            description="Get full paper metadata from a CNKI paper detail page. No login required.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "CNKI paper detail URL (contains kcms2/article/abstract)"},
                },
                "required": ["url"]
            }
        ),
        # cnki_download: 从 CNKI 下载论文 PDF/CAJ
        # 要求用户已在 Chrome 中登录知网账号
        # 使用 Playwright expect_download 拦截原生下载，保存到项目 downloads/ 目录
        # 注意：此工具与 download 工具是完全独立的下载通道
        Tool(
            name="cnki_download",
            description="Download a paper PDF/CAJ from CNKI. Requires user to be logged in to CNKI. Opens browser window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "CNKI paper detail URL"},
                },
                "required": ["url"]
            }
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
    global _auth, _page, _current_db
    import time
    t0 = time.time()
    try:
        # CARSI 模式工具
        if name == "login":    result = await handle_login(args)
        elif name == "search":   result = await handle_search(args)
        elif name == "detail":   result = await handle_detail(args)
        elif name == "download": result = await handle_download(args)
        elif name == "status":   result = await handle_status(args)
        elif name == "logout":   result = await handle_logout(args)
        # CNKI 模式工具
        elif name == "cnki_search":  result = await handle_cnki_search(args)
        elif name == "cnki_login":   result = await handle_cnki_login(args)
        elif name == "cnki_detail":  result = await handle_cnki_detail(args)
        elif name == "cnki_download": result = await handle_cnki_download(args)
        else: return [TextContent(type="text", text=f"Unknown tool: {name}")]
        elapsed = time.time() - t0
        result[0].text += f"\n\n⏱ {elapsed:.1f}s"
        return result
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# ══════════════════════════════════════════════════════════════════════
# CARSI 模式 handler 函数
# ══════════════════════════════════════════════════════════════════════


async def handle_login(args: dict) -> list[TextContent]:
    """
    CARSI 登录处理。
    流程：创建 CarsiAuth 实例 → 启动 Playwright 浏览器 → 通过 CARSI 联邦认证登录指定数据库。
    登录成功后，_page 和 _current_db 会保存在全局变量中供后续工具使用。
    支持 force=True 强制重新登录（清除旧 session）。
    """
    global _auth, _page, _current_db

    database = args["database"]
    if database not in list_dbs():
        return [TextContent(type="text", text=f"Unknown database: {database}. Available: {DB_LIST}")]

    # 获取凭证：优先使用参数传入，其次读取环境变量
    username = args.get("username") or os.environ.get("XIDIAN_USERNAME")
    password = args.get("password") or os.environ.get("XIDIAN_PASSWORD")
    headless = args.get("headless")
    if headless is None:
        headless = os.environ.get("HEADLESS", os.environ.get("headless", "false")).lower() in ("true", "1", "yes")

    # force=True 时清除旧的 cookie 状态文件
    if args.get("force") and _auth:
        await _auth.clear_state()

    if not username or not password:
        return [TextContent(type="text",
            text="Need username+password. Pass as params or set XIDIAN_USERNAME/XIDIAN_PASSWORD env vars.")]

    # 如果已有旧实例，先关闭再创建新的
    if _auth:
        try: await _auth.stop()
        except Exception: pass

    _auth = CarsiAuth(headless=headless)
    await _auth.start()

    result = await _auth.login(database, username, password)
    if result["success"]:
        _page = result["page"]
        _current_db = database
        db_label = get_db(database)["label"]
        return [TextContent(type="text", text=f"Logged into {db_label}. {result.get('message', '')}")]
    else:
        return [TextContent(type="text", text=f"Login failed: {result.get('error', '')}")]


async def _try_cookie_session(db: str) -> bool:
    """
    尝试从磁盘恢复已保存的 Cookie 会话，避免重复登录。

    流程：
    1. 检查 CarsiAuth.STATE_FILE 是否存在且有内容（>50 字节）
    2. 如果存在，创建新的 CarsiAuth 实例并用空凭证调用 login()
    3. CarsiAuth 内部会尝试用保存的 Cookie 恢复会话
    4. 成功则设置全局变量并返回 True，失败则关闭实例返回 False

    用在 search/detail/download 中，当 _auth 为空时自动调用。
    """
    global _auth, _page, _current_db
    from carsi_search.engine import CarsiAuth
    if not CarsiAuth.STATE_FILE.exists() or CarsiAuth.STATE_FILE.stat().st_size <= 50:
        return False
    headless = os.environ.get("HEADLESS", os.environ.get("headless", "true")).lower() in ("true", "1", "yes")
    auth = CarsiAuth(headless=headless)
    await auth.start()
    result = await auth.login(db, "", "")
    if result["success"]:
        _auth = auth
        _page = result["page"]
        _current_db = db
        return True
    await auth.stop()
    return False


async def handle_search(args: dict) -> list[TextContent]:
    """
    CARSI 数据库搜索。如果没有活跃会话，先尝试从 Cookie 恢复。
    返回格式化的论文列表（标题、作者、年份、来源、摘要、URL）。
    """
    global _auth, _page, _current_db

    db = args.get("database") or _current_db
    if not db:
        return [TextContent(type="text", text="No database. Use login first or pass database param.")]

    # 如果没有活跃的浏览器会话，尝试从 Cookie 恢复
    if not _auth or not _page:
        if not await _try_cookie_session(db):
            return [TextContent(type="text", text="Not logged in. Use login tool first.")]
        log.info("[CARSI] Session restored from cookies")

    result = await _auth.search(_page, db, args["query"], page_num=args.get("page", 1))

    if not result.get("success"):
        return [TextContent(type="text", text=f"Search failed: {result.get('error', '')}")]

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
    global _auth, _page, _current_db

    db = args.get("database") or _current_db
    if not _auth or not _page:
        if not await _try_cookie_session(db or "zhizhen"):
            return [TextContent(type="text", text="Not logged in.")]
        log.info("[CARSI] Session restored from cookies")

    result = await _auth.detail(_page, db or "zhizhen", args["url"])

    if not result.get("success"):
        return [TextContent(type="text", text=f"Detail failed: {result.get('error', '')}")]

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
    因为 CNKI 使用 CDP 连接用户真实 Chrome，而 CARSI 模式用的是 Playwright 自带浏览器。
    """
    global _auth, _page, _current_db

    db = args.get("database") or _current_db
    if not _auth or not _page:
        if not await _try_cookie_session(db or "ieee"):
            return [TextContent(type="text", text="Not logged in.")]
        log.info("[CARSI] Session restored from cookies")

    url = args["url"]
    title = args.get("title", "")

    # 第一步：如果 URL 不是 PDF 直链，先获取论文详情找到 PDF 链接
    if "stamp.jsp" not in url and "/pdf/" not in url and "getPDF.jsp" not in url:
        detail_result = await _auth.detail(_page, db or "zhizhen", url)
        if detail_result.get("pdfUrl"):
            url = detail_result["pdfUrl"]
        if not title and detail_result.get("title"):
            title = detail_result["title"]

    # 第二步：将 IEEE stamp.jsp 转换为 getPDF.jsp 直接下载端点
    if "stamp.jsp" in url:
        arnumber = url.split("arnumber=")[-1] if "arnumber=" in url else ""
        if arnumber:
            url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}"

    # 第三步：通过浏览器 JS fetch 下载 PDF（利用浏览器已有的认证 Cookie）
    # 先清除所有路由拦截，避免干扰 fetch 请求
    await _page.unroute("**/*")
    import base64, re
    pdf_b64 = await _page.evaluate(f"""
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
            await _page.goto(url.replace('getPDF.jsp', 'stamp.jsp'), wait_until="domcontentloaded", timeout=45000)
            return [TextContent(type="text",
                text=f"Download failed: response is not a PDF (可能是登录过期或权限不足).\n"
                     f"Opened page in browser for manual download.\nFirst bytes: {snippet[:100]}")]
        # 第五步：保存 PDF 到本地
        # DOWNLOAD_DIR 环境变量控制下载目录，在 .mcp.json 中配置
        download_dir = os.environ.get("DOWNLOAD_DIR", "")
        if not download_dir:
            # Fallback: try to use the directory where the MCP was invoked
            download_dir = os.getcwd()
        downloads_dir = Path(download_dir) / "downloads"
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
        await _page.goto(url.replace('getPDF.jsp', 'stamp.jsp'), wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(2)
        return [TextContent(type="text",
            text=f"Could not auto-download ({pdf_b64[:80]}). Opened in browser.\nURL: {_page.url[:200]}")]


async def handle_status(args: dict) -> list[TextContent]:
    """显示当前会话状态：已注册的数据库列表、当前激活的数据库、Cookie 文件状态。"""
    global _auth, _page, _current_db

    lines = [f"**Registered databases**: {DB_LIST}"]
    for name in list_dbs():
        db = get_db(name)
        marker = " < active" if name == _current_db else ""
        lines.append(f"  - `{name}`: {db['label']}{marker}")

    if _current_db:
        lines.append(f"\nActive: {_current_db}")
        if _page:
            lines.append(f"URL: {_page.url[:100]}")
    else:
        lines.append("\nNot logged in. Use login tool.")

    lines.append(f"\nCookie file: {'exists' if CarsiAuth.STATE_FILE.exists() else 'none'} (reusable)")
    return [TextContent(type="text", text="\n".join(lines))]


async def handle_logout(args: dict) -> list[TextContent]:
    """清除 CARSI 会话：删除持久化 Cookie，重置全局状态。"""
    global _auth, _page, _current_db

    if _auth: await _auth.clear_state()
    _auth = None
    _page = None
    _current_db = None
    return [TextContent(type="text", text="Session cleared. Next login requires credentials.")]


# ══════════════════════════════════════════════════════════════════════
# CNKI 模式 handler 函数
#
# CNKI 使用与 CARSI 完全不同的浏览器连接方式：
# - CARSI 模式：Playwright 启动自己的无头浏览器
# - CNKI 模式：通过 CDP 连接用户已打开的真实 Chrome 浏览器
#
# 原因：知网有严格的反爬虫机制，会检测 Playwright 的指纹特征并拦截请求。
# 通过 CDP 连接用户的真实 Chrome 可以完全绕过此限制。
# ══════════════════════════════════════════════════════════════════════


async def handle_cnki_login(args: dict) -> list[TextContent]:
    """
    CNKI 登录 —— 现已变为 no-op（空操作）。

    历史说明：最初 CNKI 登录也走 CARSI 认证流程，但后来发现知网会拦截 Playwright。
    改用 CDP 连接用户真实 Chrome 后，登录状态直接使用 Chrome 中已有的会话，
    不再需要单独登录。保留此 tool 是为了向后兼容。

    用户只需在 Chrome 中手动登录 CNKI 即可使用 cnki_download。
    """
    return [TextContent(type="text",
        text="CNKI 使用您真实 Chrome 的登录态，无需单独登录。\n"
             "请在 Chrome 中登录 CNKI 后直接使用 cnki_search/cnki_detail/cnki_download。")]


# CNKI 模式的 Playwright 实例和浏览器上下文（与 CARSI 模式的 _auth/_page 独立）
_cnki_playwright = None   # Playwright 实例，用于 CDP 连接
_cnki_context = None      # BrowserContext，通过 CDP 获取


async def _ensure_cnki_browser():
    """
    确保 CNKI 浏览器连接已建立。

    === 为什么用 CDP 而不是 Playwright 自带浏览器？ ===
    知网 (CNKI) 有严格的反爬虫机制，会检测 Playwright 的浏览器指纹特征。
    使用 Playwright launch_browser() 启动的浏览器会被知网识别为自动化工具，
    导致：搜索时弹验证码、下载链接不可用、甚至封禁 IP。
    通过 CDP 连接用户已打开的真实 Chrome 浏览器可以完全绕过此限制，
    因为从知网的角度看，这就是一个正常的用户在浏览。

    === 启动要求 ===
    Chrome 必须使用以下命令启动：
      chrome --remote-debugging-port=9222
    如果不带此参数启动 Chrome，本函数会抛出异常并提示用户。

    === 连接流程 ===
    1. 调用 Playwright 的 connect_over_cdp 连接到 127.0.0.1:9222
    2. 获取已有的 BrowserContext（复用 Chrome 的 session/Cookie）
    3. 如果没有 context 则创建新的（通常不会走到这里）
    """
    global _cnki_playwright, _cnki_context
    # 如果已有连接，直接复用
    if _cnki_context:
        return _cnki_context

    from playwright.async_api import async_playwright
    _cnki_playwright = await async_playwright().start()
    try:
        # 通过 CDP 连接到用户本地 Chrome（需要 --remote-debugging-port=9222）
        browser = await _cnki_playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
    except Exception as e:
        # 连接失败，通常是 Chrome 没有开启远程调试端口
        await _cnki_playwright.stop()
        _cnki_playwright = None
        raise RuntimeError(
            f"无法连接 Chrome CDP。请先启动 Chrome: chrome --remote-debugging-port=9222\n{e}"
        )

    # 复用 Chrome 已有的 context（包含用户的 Cookie 和登录状态）
    _cnki_context = browser.contexts[0] if browser.contexts else await browser.new_context()
    return _cnki_context


async def handle_cnki_search(args: dict) -> list[TextContent]:
    """
    CNKI 论文搜索。通过 CDP Chrome 打开知网搜索页，使用 CnkiAdapter 解析结果。
    搜索无需登录，但遇到验证码时需要用户在浏览器中手动完成。
    """
    ctx = await _ensure_cnki_browser()
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

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
    获取 CNKI 论文详情。通过 CDP Chrome 访问论文详情页，提取完整元数据。
    无需登录，但遇到验证码时需要用户手动处理。
    """
    ctx = await _ensure_cnki_browser()
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
    1. 通过 CDP 连接用户真实 Chrome，查找或复用 CNKI 标签页
    2. 导航到论文详情页，等待页面加载
    3. 检查登录状态：如果用户未登录知网，提示先在 Chrome 中登录
    4. 检查验证码：如果出现滑块验证码，提示用户手动完成
    5. 查找下载按钮 (#pdfDown 或 .btn-dlpdf a)
    6. 使用 Playwright 的 expect_download 拦截浏览器原生下载事件
    7. 将下载的文件保存到 DOWNLOAD_DIR/downloads/ 目录

    === 重要警告 ===
    - CNKI 会拦截 Playwright 自带浏览器，必须通过 CDP 连接用户真实 Chrome
    - 用户必须在 Chrome 中已登录 CNKI，否则无法下载
    - 用户必须已用 --remote-debugging-port=9222 启动 Chrome
    """
    ctx = await _ensure_cnki_browser()
    # 查找已有的 CNKI 标签页复用，避免重复打开
    page = None
    for p in ctx.pages:
        if 'cnki.net' in p.url:
            page = p
            break
    if not page:
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    url = args["url"]
    from playwright.async_api import Error as PwError

    # 导航到论文详情页
    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
    try:
        await page.wait_for_selector('.brief h1', timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(1)

    # 检查登录状态：通过页面上的 "未登录" 样式类名判断
    not_logged = await page.evaluate(
        "() => !!document.querySelector('.downloadlink.icon-notlogged, [class*=\"notlogged\"]')"
    )
    if not_logged:
        return [TextContent(type="text", text="下载需要登录 CNKI。请先在 Chrome 中登录知网账号。")]

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
        # DOWNLOAD_DIR 环境变量控制下载保存位置
        download_dir = os.environ.get("DOWNLOAD_DIR", os.getcwd())
        save_path = Path(download_dir) / "downloads" / fname
        save_path.parent.mkdir(exist_ok=True)
        await dl.save_as(str(save_path))
        return [TextContent(type="text",
            text=f"CNKI PDF 下载成功：{fname}\n"
                 f"大小: {save_path.stat().st_size} bytes\n保存: {save_path}")]
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
