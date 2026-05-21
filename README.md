# Scholar Search — 学术论文搜索下载 MCP

通过 **CDP 连接用户真实 Chrome**，一站式搜索和下载 IEEE / CNKI 论文。

无需自动化登录 — 用户手动登录一次，cookie 自动保存恢复。

```
chrome --remote-debugging-port=9222     ← 自动启动（如未运行）
       ↓
CDP 连接 (carsi_search/engine.py)      ← cookie 保存/恢复
       ↓
┌──────────┬──────────┐
│   IEEE   │   CNKI   │
│  CARSI   │   CDP    │
└──────────┴──────────┘
```

## 安装

```bash
git clone https://github.com/zhdzh12138/scholar-search.git ~/scholar-search
cd ~/scholar-search
pip install playwright mcp
python -m playwright install chromium
```

注册 MCP（全局配置）：

```bash
claude mcp add cnki-ieee -- python ~/scholar-search/cnki-ieee-download/server.py
```

或编辑 `.mcp.json`（参考 `.mcp.json.example`）：

```json
{
  "carsi-search": {
    "command": "python",
    "args": ["~/scholar-search/cnki-ieee-download/server.py"]
  }
}
```

## MCP 工具

| 工具 | 数据库 | 说明 |
|------|--------|------|
| `login` | 全部 | 连接 Chrome 并检测数据库登录状态 |
| `search` | IEEE | 搜索论文（需登录） |
| `detail` | IEEE | 获取论文元数据 |
| `download` | IEEE | 下载 PDF（浏览器 JS fetch） |
| `cnki_search` | CNKI | 搜索 CNKI（自动连接 Chrome） |
| `cnki_detail` | CNKI | 获取 CNKI 论文元数据 |
| `cnki_download` | CNKI | 下载 PDF/CAJ（浏览器原生下载） |
| `status` | 全部 | 显示 CDP 连接状态和当前数据库 |
| `logout` | 全部 | 断开 CDP（不关闭 Chrome） |

## 首次使用

1. 打开 Claude Code
2. 首次调用 MCP 工具时**自动启动 Chrome**（带 `--remote-debugging-port=9222`）
3. 在 Chrome 窗口中**手动登录**：
   - CNKI：点击"机构登录" → 校外访问 → 选择学校
   - IEEE：点击"Institutional Sign In" → CARSI → 学校认证
4. Cookie 自动保存 — 后续启动无需重新登录
5. 未登录时 Claude 会提示你在 Chrome 中登录
6. PDF 下载到 `Scholar_search/downloads/`

## 功能覆盖

| 功能 | 数据源 | 实现 |
|------|--------|------|
| 英文学术论文搜索 | IEEE Xplore | CDP + CARSI cookie |
| IEEE PDF 下载 | IEEE Xplore | CDP + CARSI cookie + JS fetch |
| 中文学术论文搜索 | CNKI 知网 | CDP 连接真实 Chrome |
| CNKI PDF/CAJ 下载 | CNKI 知网 | CDP + expect_download |

## 项目结构

```text
scholar-search/
├── cnki-ieee-download/             # MCP 服务器
│   └── carsi_search/               # CDP 引擎 + IEEE/CNKI 适配器
│   └── carsi_search/               # CDP 引擎 + 数据库适配器
├── downloads/                      # PDF 下载目录
├── .mcp.json.example               # MCP 配置模板
└── README.md
```

## 依赖

| 组件 | 必需 | 用途 |
|------|------|------|
| Claude Code | 是 | MCP 宿主 |
| Chrome | 是（自动启动） | CDP 连接真实浏览器 |
| Playwright + mcp | 是 | MCP 服务器运行时 |
| 西电账号 | 下载需要 | IEEE CARSI 认证；CNKI 机构登录 |

## 致谢

- [cnki-skills](https://github.com/cookjohn/cnki-skills) — CNKI 知网 Skills
- [cnki-codex-skills](https://github.com/cfh-7598/cnki-codex-skills) — CDP 连接模式参考

## License

MIT
