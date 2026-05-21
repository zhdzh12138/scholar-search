# carsi-search-mcp

MCP server for academic paper search and PDF download via CDP connection to real Chrome.

## Architecture

All databases share a single **CDP connection** to the user's real Chrome browser.
No automated login — the user logs in manually once, cookies are saved and restored automatically.

```
chrome --remote-debugging-port=9222     ← launched automatically if not running
       ↓
CDP connection (carsi_search/engine.py) ← cookie save/restore
       ↓
┌──────────┬──────────┬──────────┐
│   IEEE   │   CNKI   │  Zhizhen │
│  CARSI   │  CDP     │  CARSI   │
└──────────┴──────────┴──────────┘
```

## Databases

| Database | Search | Detail | Download | Auth |
|----------|--------|--------|----------|------|
| IEEE Xplore | ✅ | ✅ | ✅ | CARSI (manual login in Chrome) |
| CNKI 知网 | ✅ | ✅ | ✅ | CNKI login (manual login in Chrome) |
| Zhizhen 超星 | ✅ | ✅ | - | CARSI (manual login in Chrome) |

## Install

```bash
pip install playwright mcp
python -m playwright install chromium
```

## Usage

1. Start Claude Code in the project directory
2. On first use, Claude will auto-launch Chrome with `--remote-debugging-port=9222`
3. **Log in manually** in the Chrome window:
   - CNKI: click "机构登录" → CARSI → login with school credentials
   - IEEE: click "Institutional Sign In" → CARSI → login with school credentials
4. Cookies are saved automatically — subsequent sessions skip login
5. PDFs are saved to `Scholar_search/downloads/`

## Tools

| Tool | Description |
|------|-------------|
| `login` | Connect to Chrome and check database login status |
| `search` | Search papers in IEEE/Zhizhen (requires CARSI login) |
| `detail` | Get paper metadata |
| `download` | Download PDF via browser JS fetch (IEEE/Zhizhen) |
| `cnki_search` | Search CNKI (auto-connects if needed) |
| `cnki_detail` | Get CNKI paper metadata |
| `cnki_download` | Download CNKI PDF/CAJ via browser native download |
| `status` | Show CDP connection status |
| `logout` | Disconnect CDP (does NOT close Chrome) |
