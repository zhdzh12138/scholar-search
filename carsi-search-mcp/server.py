#!/usr/bin/env python3
"""
CARSI Academic Database Search MCP Server.

MCP tools:
  login    - Authenticate via CARSI to an academic database
  search   - Search papers in current database
  detail   - Get paper details + PDF links
  download - Open paper PDF in browser
  status   - Check session + list available databases
  logout   - Clear saved session

Add a database: edit registry.py + create adapter in databases/
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

app = Server("carsi-search-mcp")

_auth = None
_page = None
_current_db = None

DB_LIST = ", ".join(list_dbs())


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
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
        Tool(
            name="status",
            description="Check session status and list available databases.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="logout",
            description="Clear saved session cookies.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
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


@app.call_tool()
async def call_tool(name: str, args: dict) -> list[TextContent]:
    global _auth, _page, _current_db
    import time
    t0 = time.time()
    try:
        if name == "login":    result = await handle_login(args)
        elif name == "search":   result = await handle_search(args)
        elif name == "detail":   result = await handle_detail(args)
        elif name == "download": result = await handle_download(args)
        elif name == "status":   result = await handle_status(args)
        elif name == "logout":   result = await handle_logout(args)
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


async def handle_login(args: dict) -> list[TextContent]:
    global _auth, _page, _current_db

    database = args["database"]
    if database not in list_dbs():
        return [TextContent(type="text", text=f"Unknown database: {database}. Available: {DB_LIST}")]

    username = args.get("username") or os.environ.get("XIDIAN_USERNAME")
    password = args.get("password") or os.environ.get("XIDIAN_PASSWORD")
    headless = args.get("headless")
    if headless is None:
        headless = os.environ.get("HEADLESS", os.environ.get("headless", "false")).lower() in ("true", "1", "yes")

    if args.get("force") and _auth:
        await _auth.clear_state()

    if not username or not password:
        return [TextContent(type="text",
            text="Need username+password. Pass as params or set XIDIAN_USERNAME/XIDIAN_PASSWORD env vars.")]

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
    """Try to restore session from saved cookies. Returns True if successful."""
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
    global _auth, _page, _current_db

    db = args.get("database") or _current_db
    if not db:
        return [TextContent(type="text", text="No database. Use login first or pass database param.")]

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
    global _auth, _page, _current_db

    db = args.get("database") or _current_db
    if not _auth or not _page:
        if not await _try_cookie_session(db or "ieee"):
            return [TextContent(type="text", text="Not logged in.")]
        log.info("[CARSI] Session restored from cookies")

    url = args["url"]
    title = args.get("title", "")

    # Get detail to find PDF link (and title if not provided)
    if "stamp.jsp" not in url and "/pdf/" not in url and "getPDF.jsp" not in url:
        detail_result = await _auth.detail(_page, db or "zhizhen", url)
        if detail_result.get("pdfUrl"):
            url = detail_result["pdfUrl"]
        if not title and detail_result.get("title"):
            title = detail_result["title"]

    # Convert stamp.jsp to getPDF.jsp (direct download endpoint)
    if "stamp.jsp" in url:
        arnumber = url.split("arnumber=")[-1] if "arnumber=" in url else ""
        if arnumber:
            url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}"

    # Fetch PDF via browser JS (has auth cookies) → base64 → save to disk
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
        # Validate PDF header — fetch may return HTML error page with 200 status
        if pdf_data[:4] != b'%PDF':
            # Likely an HTML error/login page, not a real PDF
            snippet = pdf_data[:200].decode('utf-8', errors='replace')
            await _page.goto(url.replace('getPDF.jsp', 'stamp.jsp'), wait_until="domcontentloaded", timeout=45000)
            return [TextContent(type="text",
                text=f"Download failed: response is not a PDF (可能是登录过期或权限不足).\n"
                     f"Opened page in browser for manual download.\nFirst bytes: {snippet[:100]}")]
        # Save to downloads/ in the calling project directory
        download_dir = os.environ.get("DOWNLOAD_DIR") or os.getcwd()
        downloads_dir = Path(download_dir) / "downloads"
        downloads_dir.mkdir(exist_ok=True)
        if title:
            # Sanitize title for filename: keep alphanumeric, Chinese, spaces, replace others
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
        # Fallback: open in browser
        await _page.goto(url.replace('getPDF.jsp', 'stamp.jsp'), wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(2)
        return [TextContent(type="text",
            text=f"Could not auto-download ({pdf_b64[:80]}). Opened in browser.\nURL: {_page.url[:200]}")]


async def handle_status(args: dict) -> list[TextContent]:
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
    global _auth, _page, _current_db

    if _auth: await _auth.clear_state()
    _auth = None
    _page = None
    _current_db = None
    return [TextContent(type="text", text="Session cleared. Next login requires credentials.")]


# ── CNKI handlers (no CARSI login required) ─────────────────────────


async def handle_cnki_login(args: dict) -> list[TextContent]:
    """Login to CNKI via CARSI off-campus access."""
    auth = await _ensure_cnki_browser()
    page = auth.context.pages[0] if auth.context.pages else await auth.context.new_page()

    username = args.get("username") or os.environ.get("XIDIAN_USERNAME")
    password = args.get("password") or os.environ.get("XIDIAN_PASSWORD")
    if not username or not password:
        return [TextContent(type="text", text="需要学号和密码。")]

    # Direct CARSI URL for CNKI (bypasses fsso.cnki.net autocomplete)
    carsi_url = (
        "https://fsso.cnki.net/Shibboleth.sso/Login"
        "?entityID=https%3A%2F%2Fidp.xidian.edu.cn%2Fidp%2Fshibboleth"
        "&target=https%3A%2F%2Ffsso.cnki.net%2Fcarsi%2Fsecure"
    )
    await page.goto(carsi_url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)

    # Use CARSI engine (handles IdP + consent pages)
    if "idp.xidian.edu.cn" in page.url:
        await auth._handle_cas_login(page, username, password)
        await asyncio.sleep(1)

    # Handle remaining consent pages
    for _ in range(5):
        if "idp.xidian.edu.cn" not in page.url:
            break
        await page.evaluate("""() => {
            document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.checked = true; cb.dispatchEvent(new Event('change', {bubbles:true}));
            });
            document.querySelectorAll('button, input[type="submit"]').forEach(b => {
                if (!(b.textContent||b.value||'').includes('拒绝')) b.click();
            });
        }""")
        await asyncio.sleep(3)

    if "cnki.net" in page.url:
        await auth.context.storage_state(path=str(CNKI_STATE_FILE))
        return [TextContent(type="text", text=f"CNKI 校外登录成功！已保存会话。\n页面: {page.url[:100]}")]
    else:
        return [TextContent(type="text", text=f"登录流程完成，请检查浏览器。\n页面: {page.url[:100]}")]

_carsiauth_for_cnki = None
CNKI_STATE_FILE = Path(__file__).parent / ".cnki_state.json"


async def _ensure_cnki_browser():
    """Create a standalone Playwright browser for CNKI (always headed — CNKI blocks headless).
    Restores cookies from previous session if available."""
    global _carsiauth_for_cnki
    if _carsiauth_for_cnki:
        return _carsiauth_for_cnki
    from carsi_search.engine import CarsiAuth
    # Override state file for CNKI
    CarsiAuth.STATE_FILE = CNKI_STATE_FILE
    _carsiauth_for_cnki = CarsiAuth(headless=False)
    await _carsiauth_for_cnki.start()
    return _carsiauth_for_cnki


async def handle_cnki_search(args: dict) -> list[TextContent]:
    auth = await _ensure_cnki_browser()
    page = auth.context.pages[0] if auth.context.pages else await auth.context.new_page()

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
    auth = await _ensure_cnki_browser()
    page = auth.context.pages[0] if auth.context.pages else await auth.context.new_page()

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
    auth = await _ensure_cnki_browser()
    page = auth.context.pages[0] if auth.context.pages else await auth.context.new_page()

    from carsi_search.databases.cnki import CnkiAdapter
    adapter = CnkiAdapter(page)
    result = await adapter.download(args["url"])

    if not result.get("success"):
        err = result.get("error", "unknown")
        if err == "captcha":
            return [TextContent(type="text", text="CNKI 验证码。请在浏览器中手动完成后重试。")]
        if err == "not_logged_in":
            return [TextContent(type="text", text="下载需要登录 CNKI。请在浏览器中登录知网账号后重试。")]
        if err == "no_download_link":
            return [TextContent(type="text", text="未找到下载链接，可能该论文不提供 PDF/CAJ 下载。")]
        return [TextContent(type="text", text=f"CNKI download failed: {err}")]

    return [TextContent(type="text",
        text=f"{result.get('format', '?')} 下载已触发：{result.get('title', '')}\n请在浏览器下载管理器中查看。")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
