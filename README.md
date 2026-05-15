# Scholar Search - 统一学术论文搜索

一个 Claude Code 项目，将 Semantic Scholar、CNKI 知网、CARSI 机构访问整合为统一的学术搜索入口。

## 功能概览

| 数据源 | 用途 | 技术实现 |
|--------|------|----------|
| **Semantic Scholar** | 英文论文搜索 (默认) | REST API via curl |
| **CNKI 知网** | 中文论文/核心期刊 | Chrome DevTools MCP |
| **CARSI 机构访问** | IEEE PDF 下载 | Playwright MCP |

### 支持的操作

- 关键词搜索 (S2 / CNKI)
- 论文详情获取 (DOI, ArXiv, S2 ID)
- 引用/参考文献网络分析
- 论文推荐
- 作者搜索
- 期刊索引查询 (SCI/EI/CSSCI/北大核心)
- IEEE 机构 PDF 下载
- 论文保存到本地 Markdown
- 引用导出到 Zotero

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/YOUR_USERNAME/scholar-search.git
cd scholar-search
```

### 2. 配置 Semantic Scholar API Key (可选)

免费申请: https://www.semanticscholar.org/product/api#api-key

设置环境变量 (无 key 也可用，限速 1 req/s)：

```bash
# Windows
set S2_API_KEY=your_key_here

# Linux/Mac
export S2_API_KEY=your_key_here
```

或在 Claude Code 的 MCP 配置中设置。

### 3. 注册 MCP 服务 (可选)

**CARSI MCP** (用于 IEEE 机构 PDF 下载):

```bash
# 安装依赖
cd carsi-search-mcp
pip install -r requirements.txt
playwright install chromium
cd ..

# 在 .mcp.json 中配置西电账号
# 编辑 .mcp.json，填入 XIDIAN_USERNAME 和 XIDIAN_PASSWORD
```

**Chrome DevTools MCP** (用于 CNKI 搜索):

```bash
claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest
```

### 4. 开始使用

在 Claude Code 中打开此项目目录，即可使用：

```
/scholar-search transformer attention mechanism    # 搜索英文论文
/scholar-search 深度学习 --cnki                     # 搜索中文论文
/scholar-search --detail DOI:10.xxxx               # 获取论文详情
/scholar-search --citations paper_id                # 查看引用
/scholar-search --recommend paper_id                # 论文推荐
/cnki-search 人工智能                                # 直接搜 CNKI
/cnki-journal-index 中国科学                         # 查期刊索引
```

## 项目结构

```
Scholar_search/
├── .claude/
│   ├── skills/
│   │   ├── scholar/SKILL.md           # 统一路由 Skill (核心)
│   │   ├── cnki-search/SKILL.md       # CNKI 基础搜索
│   │   ├── cnki-advanced-search/      # CNKI 高级搜索 (SCI/EI/CSSCI)
│   │   ├── cnki-paper-detail/         # CNKI 论文详情
│   │   ├── cnki-journal-search/       # 期刊查询
│   │   ├── cnki-journal-index/        # 期刊索引/影响因子
│   │   ├── cnki-journal-toc/          # 期刊目录浏览
│   │   ├── cnki-download/             # CNKI PDF/CAJ 下载
│   │   ├── cnki-export/               # 引用导出 + Zotero
│   │   ├── cnki-parse-results/        # 解析搜索结果
│   │   └── cnki-navigate-pages/       # 翻页/排序
│   ├── agents/
│   │   ├── scholar-assistant.md        # 统一搜索 Agent
│   │   └── cnki-researcher.md          # CNKI 专用 Agent
│   └── settings.local.json             # 权限配置
├── carsi-search-mcp/                   # CARSI MCP 服务器 (可选)
│   ├── server.py                       # MCP 入口
│   ├── requirements.txt
│   └── carsi_search/                   # 适配器: IEEE, Zhizhen
├── .mcp.json                           # MCP 服务器注册
├── .gitignore
└── README.md
```

## 数据源详解

### Semantic Scholar (默认)

[Semantic Scholar](https://www.semanticscholar.org/) 是 Allen AI 维护的免费学术搜索引擎，覆盖 2 亿+ 论文。

**优势**: 最全面的英文论文库，支持引用网络分析、论文推荐、全文片段搜索。
**限制**: 中文论文覆盖较少。
**认证**: 可选 API Key (免费申请)。

### CNKI 知网

[中国知网](https://www.cnki.net/) 是中国最大的学术数据库。

**优势**: 最全的中文学术资源，支持核心期刊筛选 (SCI/EI/CSSCI/北大核心)。
**限制**: 需要 Chrome 浏览器 + DevTools MCP，部分功能需要 CNKI 账号登录。
**认证**: 手动登录 CNKI。

### CARSI 机构访问

通过 [CARSI](https://www.carsi.edu.cn/) 联盟认证获取学术数据库的机构访问权限。

**优势**: 可下载 IEEE 等数据库的付费 PDF。
**限制**: 需要西电 (或其他 CARSI 联盟高校) 账号。
**认证**: XIDIAN_USERNAME + XIDIAN_PASSWORD 环境变量。

## 使用场景示例

### 场景 1: 综合文献调研

```
你: /scholar-search large language model reasoning
Claude: [S2 搜索结果: 20 篇论文]

你: 看看第3篇的详情和引用
Claude: [论文详情 + 引用列表]

你: 推荐类似的论文
Claude: [推荐结果]

你: 保存第1和第3篇到本地
Claude: [写入 Research/papers/ 并更新索引]
```

### 场景 2: 中文论文搜索

```
你: /scholar-search 大语言模型 --cnki
Claude: [CNKI 搜索结果]

你: 看看第2篇的详情
Claude: [论文详情，含核心收录、影响因子]

你: 导出到 Zotero
Claude: [Zotero 导出完成]
```

### 场景 3: IEEE PDF 下载

```
你: /scholar-search --carsi-download https://ieeexplore.ieee.org/document/123456
Claude: [CARSI 登录 → 搜索 → 下载 PDF]
```

## 依赖

| 组件 | 必需? | 用途 |
|------|-------|------|
| Claude Code | 是 | Skill/Agent 宿主 |
| S2_API_KEY | 否 | Semantic Scholar (无 key 限速) |
| Chrome DevTools MCP | CNKI 需要 | 浏览器自动化 |
| carsi-search-mcp | CARSI 需要 | IEEE 机构 PDF 下载 |
| Python 3.10+ | CARSI 需要 | MCP 服务器运行时 |
| Zotero Desktop | 否 | 引用导出 |

## 致谢

本项目整合了以下开源项目的功能：

- [semantic-scholar-mcp](https://github.com/zhdzh12138/semantic-scholar-mcp) - Semantic Scholar MCP 服务器
- [carsi-search-mcp](https://github.com/zhdzh12138/carsi-search-mcp) - CARSI 学术数据库搜索
- [cnki-skills](https://github.com/cookjohn/cnki-skills) - CNKI 知网 Skills
- [library-access-mcp](https://github.com/yang-kun-long/library-access-mcp) - 图书馆访问 MCP
- [ieee-xplore-mcp](https://github.com/zhdzh12138/ieee-xplore-mcp) - IEEE Xplore MCP

## License

MIT
