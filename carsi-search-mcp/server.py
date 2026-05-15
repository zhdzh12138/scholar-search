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
            description="Open a paper PDF/download page in the browser.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Paper detail URL (or direct PDF URL)"},
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

    # Get detail to find PDF link
    if "stamp.jsp" not in url and "/pdf/" not in url and "getPDF.jsp" not in url:
        detail_result = await _auth.detail(_page, db or "zhizhen", url)
        if detail_result.get("pdfUrl"):
            url = detail_result["pdfUrl"]

    # Convert stamp.jsp to getPDF.jsp (direct download endpoint)
    if "stamp.jsp" in url:
        arnumber = url.split("arnumber=")[-1] if "arnumber=" in url else ""
        if arnumber:
            url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}"

    # Fetch PDF via browser JS (has auth cookies) → base64 → save to disk
    await _page.unroute("**/*")
    import base64
    from datetime import datetime
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
        out_dir = Path(__file__).parent
        save_path = out_dir / f"paper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
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


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
