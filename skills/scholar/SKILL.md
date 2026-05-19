---
name: scholar-search
description: >
  统一学术论文搜索 - Semantic Scholar 搜索所有论文, CARSI 下载 IEEE 机构 PDF, CNKI 补充中文论文。
  Triggers on: '/scholar-search', 'search papers', 'find papers', '论文搜索', '搜索论文', 'academic search'.
argument-hint: "[搜索词] [--detail ID | --citations ID | --recommend ID | --author NAME]"
---

# 统一学术论文搜索

## Step 1: 用 Semantic Scholar 搜索

通过 curl 调用 S2 bulk API（速率限制最宽松）。解析返回的 JSON，格式化展示。

```bash
curl -s "https://api.semanticscholar.org/graph/v1/paper/search/bulk?query={URL_ENCODED_QUERY}&limit=20&fields=title,authors,year,citationCount,venue,externalIds,openAccessPdf,isOpenAccess"
```

- 空格替换为 `+`，中文需要 URL encode
- `data` 数组中每个对象是一篇论文
- DOI 在 `externalIds.DOI`
- PDF 在 `openAccessPdf.url`
- 作者取 `authors[].name`，前5人，超过显示 "et al."

**格式化为**：

```
[1] **{title}**
    作者: {前5人}  |  年份: {year}  |  引用: {citationCount}
    会议: {venue}  |  DOI: {externalIds.DOI}
    PDF: {openAccessPdf.url}
```

## Step 2: 判断是否需要 CNKI 补充

**自动触发 CNKI 的条件**（满足任一）：
- S2 结果少于 10 条
- 结果中几乎没有中文论文
- 用户明确要求中文

CNKI 搜索：调用 `cnki_search(query="{关键词}")`

**注意**：CNKI 会打开浏览器窗口（有头模式），首次可能需手动过滑块验证，后续自动复用会话。

## Step 3: IEEE 详情/下载 → CARSI

用户对 IEEE 论文需要详情或 PDF 时直接调用：

- `carsi_detail(url="论文URL", database="ieee")` — 详情
- `carsi_download(url="论文URL", title="论文标题", database="ieee")` — 下载

**如果失败**：`carsi_login(database="ieee")` → `carsi_status()` → 重试

## 其他 S2 操作

```bash
# 论文详情 (by DOI / ArXiv ID / S2 paper ID)
curl -s "https://api.semanticscholar.org/graph/v1/paper/{PAPER_ID}?fields=title,authors,year,abstract,citationCount,venue,externalIds,openAccessPdf,tldr,referenceCount,journal,keywords"

# 引用该论文的文献（字段在 citingPaper 中）
curl -s "https://api.semanticscholar.org/graph/v1/paper/{ID}/citations?fields=title,authors,year,isInfluential&limit=20"

# 参考文献（字段在 citedPaper 中）
curl -s "https://api.semanticscholar.org/graph/v1/paper/{ID}/references?fields=title,authors,year,isInfluential&limit=20"

# 论文推荐
curl -s "https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{PAPER_ID}?limit=20&fields=title,authors,year,citationCount,venue"

# 作者搜索
curl -s "https://api.semanticscholar.org/graph/v1/author/search?query={NAME}&fields=name,affiliations,paperCount,citationCount,hIndex&limit=10"
```

## CNKI 知网

- `cnki_search(query="关键词")` — 搜索（返回标题、作者、期刊、日期、引用数）
- `cnki_detail(url="详情页URL")` — 详情（返回摘要、关键词、基金、DOI、单位等）

验证码错误时提示用户在浏览器中手动完成后重试。

## 工作流示例

```
用户: /scholar-search transformer attention mechanism
→ curl S2 bulk API → 解析 JSON → 格式化展示

用户: 第3篇详情
→ curl S2 paper API → 格式化展示

用户: IEEE PDF 下载
→ carsi_download(url, title) → PDF 保存到 downloads/

用户: 搜不到中文
→ cnki_search(query="{关键词}") → 展示 CNKI 结果
```
