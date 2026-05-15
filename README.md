# Scholar Search — 统一学术论文搜索

Claude Code Skill 集合：Semantic Scholar 搜索 + CNKI 知网 + CARSI 机构 PDF 下载。

## 快速开始

### 1. 克隆到任意位置

```bash
git clone https://github.com/zhdzh12138/scholar-search.git ~/scholar-search
```

### 2. 复制到你的项目

```bash
# 进入你的工作项目
cd /path/to/your-project

# 复制 skills 和 agents
cp -r ~/scholar-search/skills .claude/skills
cp -r ~/scholar-search/agents .claude/agents

# 复制辅助脚本（S2 API 调用 + 格式化）
cp -r ~/scholar-search/scripts .
```

### 3. 配置 CARSI MCP（可选，用于 IEEE 机构 PDF 下载）

```bash
# 复制 MCP 配置模板
cp ~/scholar-search/.mcp.json.example .mcp.json

# 编辑 .mcp.json，填入你的学号密码
# 将 args 中的路径改为实际路径
```

`.mcp.json` 示例：

```json
{
  "mcpServers": {
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
}
```

### 4. 安装 CARSI 依赖（可选）

```bash
pip install playwright mcp
python -m playwright install chromium
```

### 5. 开始使用

重启 Claude Code，在你的项目中使用：

```text
/scholar-search transformer attention mechanism    # 搜索论文
/scholar-search --detail DOI:10.xxxx              # 论文详情
/scholar-search --citations paper_id              # 查看引用
/scholar-search 深度学习 --cnki                    # CNKI 中文搜索
```

## 功能

| 功能 | 命令 | 数据源 |
|------|------|--------|
| 搜索论文 | `/scholar-search {关键词}` | Semantic Scholar |
| 论文详情 | `/scholar-search --detail {ID}` | Semantic Scholar |
| 引用分析 | `/scholar-search --citations {ID}` | Semantic Scholar |
| 论文推荐 | `/scholar-search --recommend {ID}` | Semantic Scholar |
| 作者搜索 | `/scholar-search --author {名字}` | Semantic Scholar |
| 中文论文 | `/cnki-search {关键词}` | CNKI 知网 |
| 高级搜索 | `/cnki-advanced-search {条件}` | CNKI (SCI/EI/CSSCI) |
| 期刊查询 | `/cnki-journal-search {期刊名}` | CNKI |
| 期刊索引 | `/cnki-journal-index {期刊名}` | CNKI |
| IEEE PDF 下载 | `carsi_download(url, title)` | CARSI 机构访问 |
| 导出到 Zotero | `/cnki-export zotero {URL}` | CNKI |

## 项目结构

```text
scholar-search/
├── README.md
├── LICENSE
├── agents/                         # 复制到 .claude/agents/
│   └── scholar-assistant.md        # 统一搜索协调 Agent
├── skills/                         # 复制到 .claude/skills/
│   └── scholar/
│       └── SKILL.md                # 统一搜索 Skill
├── scripts/                        # 复制到项目根目录
│   └── s2.py                       # Semantic Scholar API 辅助脚本
├── carsi-search-mcp/               # CARSI MCP 服务器（可选）
│   ├── server.py
│   └── carsi_search/
├── .mcp.json.example               # MCP 配置模板
├── .gitignore
└── LICENSE
```

## 工作流程

```text
搜索 → S2 (唯一入口，覆盖中英文)
  │
  ├─ IEEE 详情/下载 → carsi_detail / carsi_download
  │   └─ 失败 → carsi_login → 重试
  │
  └─ 中文不足 → /cnki-search 补充
```

## 依赖

| 组件 | 必需 | 用途 |
|------|------|------|
| Claude Code | 是 | Skill 宿主 |
| Python 3.10+ | 是 | scripts/s2.py |
| S2_API_KEY | 否 | Semantic Scholar (无 key 限速) |
| Playwright | CARSI 需要 | IEEE 机构 PDF 下载 |
| CNKI 账号 | CNKI 下载需要 | CNKI PDF 下载 |

## 致谢

- [cnki-skills](https://github.com/cookjohn/cnki-skills) — CNKI 知网 Skills
- [carsi-search-mcp](https://github.com/zhdzh12138/carsi-search-mcp) — CARSI 机构访问
- [semantic-scholar-mcp](https://github.com/zhdzh12138/semantic-scholar-mcp) — Semantic Scholar MCP

## License

MIT
