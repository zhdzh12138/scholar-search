# carsi-search-mcp

MCP server for academic paper search and download via CARSI institutional access.

## Databases

- **IEEE Xplore** - search, detail, PDF download via CARSI (Xidian University)
- **CNKI 知网** - search, detail, PDF download via CDP (real Chrome browser)
- **Zhizhen 超星** - search, detail via CARSI

## Install

```bash
pip install playwright mcp
python -m playwright install chromium
```

## CNKI

Requires Chrome with `--remote-debugging-port=9222` and user logged in to CNKI.
