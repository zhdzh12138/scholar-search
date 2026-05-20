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

### 2. 安装 CARSI MCP（可选，用于 IEEE PDF 下载）

```bash
pip install playwright mcp
python -m playwright install chromium
```

注册 MCP 服务器（全局配置，所有项目共享）：

```bash
claude mcp add carsi-search -- python ~/scholar-search/carsi-search-mcp/server.py
```

或手动编辑 `~/.claude/settings.json`，在 `mcpServers` 中添加：

```json
{
  "carsi-search": {
    "command": "python",
    "args": ["C:/Users/你的用户名/scholar-search/carsi-search-mcp/server.py"],
    "env": {
      "XIDIAN_USERNAME": "你的学号",
      "XIDIAN_PASSWORD": "你的密码",
      "HEADLESS": "true"
    }
  }
}
```

### 3. 设置 Semantic Scholar API Key（可选）

免费申请：https://www.semanticscholar.org/product/api#api-key-form

设置环境变量后速率从 1 req/s 提升到 10 req/s。

## 使用

在**任意项目**中打开 Claude Code，直接使用：

```
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
| 中文论文搜索/详情 | CNKI 知网 | carsi-mcp (Playwright) |
| CNKI PDF 下载 | CNKI 知网 | chrome-devtools Skill |
| CNKI 引用导出/Zotero | CNKI 知网 | chrome-devtools Skill |
| IEEE PDF 下载 | CARSI 机构访问 | carsi-mcp (Playwright) |

## 工作流

```text
搜索 → S2（唯一入口，覆盖中英文）
  │
  ├─ IEEE PDF 下载 → carsi_download (Playwright)
  │   └─ 失败 → carsi_login → 重试
  │
  ├─ CNKI 中文论文 → cnki_search (Playwright)
  │   └─ CNKI PDF 下载 → /cnki-download (Chrome DevTools)
  │
  └─ 引用导出 → /cnki-export (Chrome DevTools)
```

## 项目结构

```text
scholar-search/
├── skills/                         # 复制到 ~/.claude/skills/
│   └── scholar/SKILL.md            # 统一搜索 Skill（自包含，用 curl）
│   └── cnki-*/SKILL.md             # CNKI Skills（Chrome DevTools MCP）
├── agents/                         # 复制到 ~/.claude/agents/
│   └── scholar-assistant.md        # 搜索协调 Agent
└── carsi-search-mcp/               # MCP 服务器（全局注册一次）
    ├── server.py                   # 入口
    └── carsi_search/               # IEEE + CNKI + Zhizhen 适配器
```

## 依赖

| 组件 | 必需 | 用途 |
|------|------|------|
| Claude Code | 是 | Skill 宿主 |
| S2_API_KEY | 否 | Semantic Scholar（无 key 限速） |
| Playwright + mcp | CARSI/CNKI 需要 | MCP 服务器运行时 |
| 西电账号 | CARSI 需要 | IEEE 机构 PDF 下载 |

## 致谢

- [cnki-skills](https://github.com/cookjohn/cnki-skills) — CNKI 知网 Skills
- [carsi-search-mcp](https://github.com/zhdzh12138/carsi-search-mcp) — CARSI 机构访问
- [semantic-scholar-mcp](https://github.com/zhdzh12138/semantic-scholar-mcp) — Semantic Scholar MCP

## License

MIT
