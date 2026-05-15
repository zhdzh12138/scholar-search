---
name: scholar-search
description: >
  统一学术论文搜索 - Semantic Scholar 搜索英文论文, CNKI 搜索中文论文,
  CARSI 下载 IEEE 机构 PDF。自动路由最佳数据源。
  Triggers on: '/scholar-search', 'search papers', 'find papers', '论文搜索', '搜索论文', 'academic search'.
argument-hint: "[搜索词] [--cnki | --carsi-download URL | --detail PAPER_ID | --citations PAPER_ID | --recommend PAPER_ID | --author NAME]"
---

# 统一学术论文搜索

你是学术论文搜索助手。根据用户需求自动选择最佳数据源。

## 数据源路由

| 用户意图 | 标志 | 数据源 | 执行方式 |
|---------|------|--------|---------|
| 英文论文/通用搜索 | (默认) | Semantic Scholar | Bash curl REST API |
| 中文论文/核心期刊 | `--cnki` 或 S2 无中文结果 | CNKI 知网 | 调用 /cnki-search Skill |
| IEEE 论文 PDF 下载 | `--carsi-download URL` | CARSI 机构访问 | 调用 carsi-mcp 工具 |
| 论文详情 | `--detail ID` | Semantic Scholar | Bash curl REST API |
| 引用/参考文献 | `--citations ID` | Semantic Scholar | Bash curl REST API |
| 论文推荐 | `--recommend ID` | Semantic Scholar | Bash curl REST API |
| 作者搜索 | `--author NAME` | Semantic Scholar | Bash curl REST API |
| 保存论文到本地 | `--save` | 本地文件 | Bash 写入 Research/ 目录 |

**解析 $ARGUMENTS**：从用户输入中提取搜索词和标志。例如：
- `"transformer attention"` → 搜索词: transformer attention, 源: S2
- `"深度学习 --cnki"` → 搜索词: 深度学习, 源: CNKI
- `"--detail 10.1093/mind/lix.236.433"` → 获取 DOI 论文详情

---

## Semantic Scholar (默认数据源)

### API Key

从环境变量 `S2_API_KEY` 读取。如果未设置，省略 `-H` 头（限速 1 req/s，有 key 为 10 req/s）。

构造 curl 时：如果 `$S2_API_KEY` 非空，添加 `-H "x-api-key: $S2_API_KEY"`；否则不加。

### 搜索论文

```bash
QUERY="{URL_ENCODED_QUERY}"
API_KEY_HEADER=""
if [ -n "$S2_API_KEY" ]; then API_KEY_HEADER="-H x-api-key:$S2_API_KEY"; fi
curl -s "https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=$QUERY&limit=20&fields=title,authors,year,citationCount,venue,abstract,externalIds,openAccessPdf,publicationDate,fieldsOfStudy,tldr,isOpenAccess,journal,publicationTypes" $API_KEY_HEADER
```

**注意**：使用 `search/bulk` 端点（比 `search` 更宽松的速率限制）。

**URL 编码**：搜索词中的空格替换为 `+`，中文需要 URL encode。

### 获取论文详情

支持的 ID 类型：DOI, ArXiv ID (如 `ArXiv:2301.07041`), CorpusId (如 `CorpusId:14636783`), S2 paper ID (SHA hash), MAG, ACL, PubMed, DBLP。

```bash
curl -s "https://api.semanticscholar.org/graph/v1/paper/{PAPER_ID}?fields=title,authors,year,abstract,citationCount,venue,externalIds,openAccessPdf,tldr,referenceCount,influentialCitationCount,publicationTypes,journal,keywords,fieldsOfStudy"
```

### 引用和参考文献

```bash
# 被谁引用 (citations)
curl -s "https://api.semanticscholar.org/graph/v1/paper/{ID}/citations?fields=title,authors,year,isInfluential,contexts&limit=20"
# 该论文的参考文献 (references)
curl -s "https://api.semanticscholar.org/graph/v1/paper/{ID}/references?fields=title,authors,year,isInfluential&limit=20"
```

### 论文推荐

```bash
curl -s "https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{PAPER_ID}?limit=20&fields=title,authors,year,citationCount,venue,abstract"
```

### 作者搜索

```bash
curl -s "https://api.semanticscholar.org/graph/v1/author/search?query={NAME}&fields=name,affiliations,paperCount,citationCount,hIndex&limit=10"
```

### 标题精确匹配

```bash
curl -s "https://api.semanticscholar.org/graph/v1/paper/search?query={TITLE}&limit=1&fields=title,authors,year,citationCount,venue,externalIds,abstract&match_title=true"
```

### 输出格式

解析 JSON 响应，格式化为可读列表：

```
搜索 "{query}"：共 {total} 条结果

[1] **{title}**
    作者: {authors前5人}
    年份: {year} | 会议: {venue} | 引用: {citationCount}
    DOI: {DOI} | PDF: {openAccessPdf.url}
    TLDR: {tldr.text 或 abstract前300字}

[2] ...
```

**DOI 格式**：从 `externalIds.DOI` 提取。
**PDF 链接**：从 `openAccessPdf.url` 提取。
**作者显示**：前5人用逗号分隔，超过5人显示 "et al. (共N人)"。

---

## CNKI 搜索 (中文论文)

**触发条件**：用户加 `--cnki` 标志，或 Semantic Scholar 搜索结果中无中文论文。

**前提**：Chrome DevTools MCP 已注册，Chrome 已启动并打开 CNKI。

### 执行

直接调用对应的 CNKI Skills：

1. **搜索**: `/cnki-search {关键词}` 或 `/cnki-advanced-search {筛选条件}`
2. **翻页/排序**: `/cnki-navigate-pages next` 或 `sort by date`
3. **论文详情**: `/cnki-paper-detail {URL}`
4. **期刊查询**: `/cnki-journal-search {期刊名}`
5. **期刊索引**: `/cnki-journal-index {期刊名}`
6. **导出引用**: `/cnki-export zotero {URL}` 或 `/cnki-export ris {URL}`
7. **下载**: `/cnki-download {URL}`

**如果 Chrome DevTools MCP 未安装**，提示用户：
```
需要 Chrome DevTools MCP 才能搜索 CNKI。安装命令：
claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest
```

---

## CARSI IEEE 下载

**触发条件**：用户使用 `--carsi-download` 标志，或需要下载 IEEE 论文 PDF。

**前提**：carsi-search-mcp 已注册为 MCP server。

### 执行

1. **登录**: 调用 `carsi_login(database="ieee")` (首次或会话过期时)
2. **搜索**: 调用 `carsi_search(query="论文标题")` 找到论文
3. **下载**: 调用 `carsi_download(url="论文URL")` 下载 PDF

### 首次使用配置

```
需要 CARSI MCP 才能通过机构权限下载 IEEE PDF。
安装: pip install -r carsi-search-mcp/requirements.txt
配置: 在 .mcp.json 中注册 carsi-search-mcp (设置 XIDIAN_USERNAME/XIDIAN_PASSWORD)
```

**如果 carsi-mcp 未安装**，提供替代方案：
- 检查论文是否有 Open Access PDF 链接 (从 S2 的 openAccessPdf 字段)
- 提供论文的 IEEE 页面 URL 让用户手动下载

---

## 保存论文到本地

**触发条件**：用户使用 `--save` 标志，或明确要求保存论文。

### 步骤

1. 创建目录（如不存在）:
```bash
mkdir -p Research/papers
```

2. 生成文件名: `{source}_{title_clean}.md`（source 为 s2/cnki/ieee，title_clean 取前30个字符，替换特殊字符）

3. 写入结构化 Markdown:

```markdown
# {title}

## 基本信息
- **标题**: {title}
- **作者**: {authors}
- **年份**: {year}
- **期刊/会议**: {venue}
- **DOI**: {doi}
- **来源**: Semantic Scholar / CNKI / IEEE

## 学术指标
- **引用数**: {citationCount}
- **参考文献数**: {referenceCount}
- **开放获取**: {isOpenAccess}

## 摘要
{abstract 或 TLDR}

## 关键词
{keywords 或 fieldsOfStudy}

## 链接
- **论文页面**: {url}
- **PDF**: {pdf_url}

---
## AI 笔记 / 阅读记录
*待补充*
```

4. 更新索引:
```bash
# 如果 Research/README.md 不存在，创建表头
# 追加一行: | 日期 | 标题 | 来源 | 引用数 |
```

---

## 完整工作流示例

### 示例 1: 搜索英文论文
```
用户: /scholar-search transformer attention mechanism
→ 执行 S2 bulk search
→ 返回格式化列表
```

### 示例 2: 搜索中文论文
```
用户: /scholar-search 深度学习 --cnki
→ 调用 /cnki-search 深度学习
→ 返回 CNKI 结果
```

### 示例 3: 获取论文详情
```
用户: /scholar-search --detail 10.1093/mind/lix.236.433
→ curl S2 API 获取详情
→ 返回完整元数据
```

### 示例 4: 下载 IEEE PDF
```
用户: /scholar-search --carsi-download https://ieeexplore.ieee.org/document/123456
→ 调用 carsi_login → carsi_download
→ PDF 下载到本地
```

### 示例 5: 综合流程
```
用户: /scholar-search 自然语言处理
→ S2 搜索返回结果 (主要是英文论文)
→ 用户: "搜不到中文的，用 CNKI"
→ 调用 /cnki-search 自然语言处理
→ 用户: "第3篇的 IEEE PDF 怎么下？"
→ 调用 carsi_login → carsi_download
→ 用户: "保存第1和第3篇"
→ 写入 Research/papers/ 并更新索引
```
