# Scholar Search — 统一学术论文搜索

Claude Code Skill + MCP：Semantic Scholar 搜索 + CNKI 知网 + IEEE/万方 CARSI PDF 下载。

所有数据库通过 **CDP 连接用户真实 Chrome**，无需自动化登录 — 用户手动登录一次，cookie 自动保存恢复。

```
chrome --remote-debugging-port=9222     ← 自动启动（如未运行）
       ↓
CDP 连接 (carsi_search/engine.py)      ← cookie 保存/恢复
       ↓
┌──────────┬──────────┬──────────┐
│   IEEE   │   CNKI   │  Zhizhen │
│  CARSI   │   CDP    │  CARSI   │
└──────────┴──────────┴──────────┘
```

## 安装

### 1. Skills 和 Agents（全局可用）

```bash
git clone https://github.com/zhdzh12138/scholar-search.git ~/scholar-search

# 复制到 Claude Code 全局目录（所有项目共享）
cp -r ~/scholar-search/skills/* ~/.claude/skills/
cp -r ~/scholar-search/agents/* ~/.claude/agents/
```

### 2. MCP 服务器

```bash
pip install playwright mcp
python -m playwright install chromium
```

注册 MCP（全局配置）：

```bash
claude mcp add carsi-search -- python ~/scholar-search/carsi-search-mcp/server.py
```

或编辑 `.mcp.json`（参考 `.mcp.json.example`）：

```json
{
  "carsi-search": {
    "command": "python",
    "args": ["~/scholar-search/carsi-search-mcp/server.py"]
  }
}
```

### 3. Semantic Scholar API Key（可选）

免费申请：https://www.semanticscholar.org/product/api#api-key-form

无 key 限速 1 req/s，有 key 提升到 10 req/s。

## 使用

### Skill 命令

```text
/scholar transformer attention mechanism    # 搜索论文
/scholar --detail DOI:10.xxxx              # 论文详情
/scholar --citations paper_id              # 引用分析
/scholar --recommend paper_id              # 论文推荐
/scholar --author "Geoffrey Hinton"        # 作者搜索
/scholar 深度学习                           # 自动补充 CNKI
```

### MCP 工具（IEEE / CNKI / 万方）

| 工具 | 说明 |
|------|------|
| `login` | 连接 Chrome 并检测数据库登录状态 |
| `search` | 搜索 IEEE/Zhizhen 论文（需 CARSI 登录） |
| `detail` | 获取论文元数据 |
| `download` | 下载 PDF（IEEE/Zhizhen 用 JS fetch） |
| `cnki_search` | 搜索 CNKI（自动连接 Chrome） |
| `cnki_detail` | 获取 CNKI 论文元数据 |
| `cnki_download` | 下载 CNKI PDF/CAJ（浏览器原生下载） |
| `status` | 显示 CDP 连接状态 |
| `logout` | 断开 CDP（不关闭 Chrome） |

### 首次使用

1. 打开 Claude Code
2. 首次调用时会**自动启动 Chrome**（带 `--remote-debugging-port=9222`）
3. 在 Chrome 窗口中**手动登录**：
   - CNKI：点击"机构登录" → 校外访问 → 选择学校
   - IEEE：点击"Institutional Sign In" → CARSI → 学校认证
4. Cookie 自动保存 — 后续启动无需重新登录
5. 未登录时 Claude 会提示
6. PDF 下载到 `Scholar_search/downloads/`

## 功能

| 功能 | 数据源 | 实现 |
|------|--------|------|
| 英文论文搜索/详情/引用 | Semantic Scholar | curl API (Skill) |
| 作者搜索/论文推荐 | Semantic Scholar | curl API (Skill) |
| 中文论文搜索/详情 | CNKI 知网 | CDP 连接真实 Chrome |
| CNKI PDF/CAJ 下载 | CNKI 知网 | CDP + expect_download |
| IEEE PDF 下载 | IEEE Xplore | CDP + CARSI cookie + JS fetch |
| 万方搜索/详情 | Zhizhen 超星 | CDP + CARSI cookie |

## 工作流

```text
搜索 → S2（唯一入口，覆盖中英文）
  │
  ├─ IEEE PDF 下载 → carsi download     (CDP 真实 Chrome)
  │
  ├─ CNKI 中文论文 → cnki_search         (CDP 真实 Chrome)
  │   └─ CNKI PDF 下载 → cnki_download   (CDP)
  │
  └─ 引用导出 → /cnki-export            (Chrome DevTools Skill)
```

## 项目结构

```text
scholar-search/
├── skills/                         # 复制到 ~/.claude/skills/
│   ├── scholar/SKILL.md            # 统一搜索 Skill (S2 curl)
│   ├── cnki-download/SKILL.md      # CNKI 下载 Skill
│   └── cnki-export/SKILL.md        # CNKI 引用导出
├── agents/                         # 复制到 ~/.claude/agents/
│   └── scholar-assistant.md        # 搜索协调 Agent
├── carsi-search-mcp/               # MCP 服务器 (全局注册)
│   ├── server.py                   # 入口 (IEEE + CNKI + Zhizhen)
│   └── carsi_search/               # CDP 引擎 + 数据库适配器
├── downloads/                      # PDF 下载目录
├── .mcp.json.example               # MCP 配置模板
└── README.md
```

## 依赖

| 组件 | 必需 | 用途 |
|------|------|------|
| Claude Code | 是 | Skill 宿主 |
| Chrome | 是（自动启动） | CDP 连接真实浏览器 |
| Playwright + mcp | 是 | MCP 服务器运行时 |
| S2_API_KEY | 否 | Semantic Scholar（无 key 限速） |
| 西电账号 | CARSI 需要 | IEEE 机构 PDF 下载 |

## 致谢

- [cnki-skills](https://github.com/cookjohn/cnki-skills) — CNKI 知网 Skills
- [carsi-search-mcp](https://github.com/zhdzh12138/carsi-search-mcp) — CARSI 机构访问
- [semantic-scholar-mcp](https://github.com/zhdzh12138/semantic-scholar-mcp) — Semantic Scholar MCP
- [cnki-codex-skills](https://github.com/cfh-7598/cnki-codex-skills) — CDP 连接模式参考

## License

MIT
