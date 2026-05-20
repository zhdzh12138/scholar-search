# Scholar Search — 统一学术论文搜索

Claude Code Skill + MCP：Semantic Scholar 搜索 + CNKI 知网 + CARSI 机构 PDF 下载。

## 安装

### 1. 安装 Skills 和 Agents（全局可用）

```bash
git clone https://github.com/zhdzh12138/scholar-search.git ~/scholar-search

# 复制到 Claude Code 全局目录（所有项目共享）
cp -r ~/scholar-search/skills/* ~/.claude/skills/
cp -r ~/scholar-search/agents/* ~/.claude/agents/
```

### 2. 安装 MCP 服务器

```bash
pip install playwright mcp
python -m playwright install chromium
```

注册 MCP 服务器（全局配置）：

```bash
claude mcp add carsi-search -- python ~/scholar-search/carsi-search-mcp/server.py
```

或编辑 `.mcp.json`（参考 `.mcp.json.example`）：

```json
{
  "carsi-search": {
    "command": "python",
    "args": ["~/scholar-search/carsi-search-mcp/server.py"],
    "env": {
      "XIDIAN_USERNAME": "你的学号",
      "XIDIAN_PASSWORD": "你的密码",
      "HEADLESS": "true"
    }
  }
}
```

### 3. CNKI 使用准备

CNKI 通过 CDP 连接你的真实 Chrome 浏览器（绕过反爬）：

1. 关闭所有 Chrome 窗口
1. 用调试模式启动 Chrome：

```bash
# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222

# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222
```

3. 在 Chrome 中登录 CNKI（机构登录 → 校外访问 → 选择学校）

### 4. Semantic Scholar API Key（可选）

免费申请：https://www.semanticscholar.org/product/api#api-key-form

无 key 限速 1 req/s，有 key 提升到 10 req/s。

## 使用

在**任意项目**中打开 Claude Code，直接使用：

```text
/scholar-search transformer attention mechanism    # 搜索论文
/scholar-search --detail DOI:10.xxxx              # 论文详情
/scholar-search --citations paper_id              # 引用分析
/scholar-search --recommend paper_id              # 论文推荐
/scholar-search --author "Geoffrey Hinton"        # 作者搜索
/scholar-search 深度学习                           # 自动补充 CNKI
```

## 功能

| 功能 | 数据源 | 实现方式 |
|------|--------|---------|
| 英文论文搜索/详情/引用 | Semantic Scholar | curl API (Skill) |
| 作者搜索/论文推荐 | Semantic Scholar | curl API (Skill) |
| 中文论文搜索/详情 | CNKI 知网 | CDP 连接真实 Chrome |
| CNKI PDF 下载 | CNKI 知网 | CDP + expect_download |
| CNKI 引用导出/Zotero | CNKI 知网 | Chrome DevTools Skill |
| IEEE PDF 下载 | CARSI 机构访问 | Playwright (headless) |

## 工作流

```text
搜索 → S2（唯一入口，覆盖中英文）
  │
  ├─ IEEE PDF 下载 → carsi_download (Playwright headless)
  │   └─ 失败 → carsi_login → 重试
  │
  ├─ CNKI 中文论文 → cnki_search (CDP 真实 Chrome)
  │   └─ CNKI PDF 下载 → cnki_download (CDP)
  │
  └─ 引用导出 → /cnki-export (Chrome DevTools Skill)
```

## 项目结构

```text
scholar-search/
├── skills/                         # 复制到 ~/.claude/skills/
│   ├── scholar/SKILL.md            # 统一搜索 Skill (S2 curl)
│   ├── cnki-download/SKILL.md      # CNKI 下载 (Chrome DevTools 备选)
│   └── cnki-export/SKILL.md        # CNKI 引用导出
├── agents/                         # 复制到 ~/.claude/agents/
│   └── scholar-assistant.md        # 搜索协调 Agent
├── carsi-search-mcp/               # MCP 服务器 (全局注册)
│   ├── server.py                   # 入口 (IEEE + CNKI + Zhizhen)
│   └── carsi_search/               # 数据库适配器
├── .mcp.json.example               # MCP 配置模板
└── README.md
```

## 依赖

| 组件 | 必需 | 用途 |
|------|------|------|
| Claude Code | 是 | Skill 宿主 |
| Chrome + `--remote-debugging-port=9222` | CNKI 需要 | CDP 连接真实浏览器 |
| Playwright + mcp | MCP 需要 | MCP 服务器运行时 |
| S2_API_KEY | 否 | Semantic Scholar（无 key 限速） |
| 西电账号 | CARSI 需要 | IEEE 机构 PDF 下载 |

## 致谢

- [cnki-skills](https://github.com/cookjohn/cnki-skills) — CNKI 知网 Skills
- [carsi-search-mcp](https://github.com/zhdzh12138/carsi-search-mcp) — CARSI 机构访问
- [semantic-scholar-mcp](https://github.com/zhdzh12138/semantic-scholar-mcp) — Semantic Scholar MCP
- [cnki-codex-skills](https://github.com/cfh-7598/cnki-codex-skills) — CDP 连接模式参考

## License

MIT
