---
name: scholar-search
description: >
  统一学术论文搜索 - Semantic Scholar 搜索所有论文, CARSI 下载 IEEE 机构 PDF, CNKI 补充中文论文。
  Triggers on: '/scholar-search', 'search papers', 'find papers', '论文搜索', '搜索论文', 'academic search'.
argument-hint: "[搜索词] [--detail ID | --citations ID | --recommend ID | --author NAME]"
---

# 统一学术论文搜索

所有 S2 操作通过 `scripts/s2.py` 脚本执行，脚本负责 API 调用和输出格式化。

---

## Step 1: 搜索（S2 为唯一入口）

```bash
PYTHONIOENCODING=utf-8 python scripts/s2.py search "{搜索词}" --limit 20
```

脚本返回已格式化的论文列表，**直接展示给用户**，不需要额外解析。

## Step 2: 判断是否需要 CNKI 补充

**自动触发 CNKI 的条件**（满足任一）：
- S2 结果少于 10 条
- 结果中几乎没有中文论文（标题无中文字符）
- 用户明确要求中文或使用 `--cnki`

CNKI 搜索：调用 `cnki_search(query="{关键词}")`

**注意**：CNKI 会打开一个浏览器窗口（有头模式），首次使用可能需要手动完成滑块验证。后续调用自动复用会话。

## Step 3: IEEE 论文详情/下载 → CARSI

用户对 IEEE 论文（URL 含 `ieeexplore.ieee.org`）需要详情或 PDF 时：

```
carsi_detail(url="论文URL", database="ieee")
carsi_download(url="论文URL", title="论文标题", database="ieee")
```

**如果失败**：`carsi_login(database="ieee")` → `carsi_status()` → 重试

**如果 carsi-mcp 未安装**：提供 IEEE URL 让用户手动下载。

---

## 其他 S2 操作

全部通过 `scripts/s2.py` 执行，脚本返回格式化文本，直接展示：

```bash
# 论文详情 (by DOI/ArXiv ID/S2 paper ID)
PYTHONIOENCODING=utf-8 python scripts/s2.py detail "{PAPER_ID}"

# 引用该论文的文献
PYTHONIOENCODING=utf-8 python scripts/s2.py citations "{PAPER_ID}" --limit 20

# 参考文献
PYTHONIOENCODING=utf-8 python scripts/s2.py references "{PAPER_ID}" --limit 20

# 论文推荐
PYTHONIOENCODING=utf-8 python scripts/s2.py recommend "{PAPER_ID}" --limit 20

# 作者搜索
PYTHONIOENCODING=utf-8 python scripts/s2.py author "{作者名}" --limit 10
```

## CNKI 知网

CNKI 操作通过 carsi-mcp 工具执行（Playwright 驱动，无需 Chrome DevTools MCP）：

- `cnki_search(query="关键词")` — CNKI 论文搜索（返回标题、作者、期刊、日期、引用数）
- `cnki_detail(url="详情页URL")` — CNKI 论文详情（返回摘要、关键词、基金、DOI、单位等）

**验证码处理**：如果返回 captcha 错误，提示用户在浏览器中手动完成后重试。

## 完整工作流示例

```
用户: /scholar-search transformer attention mechanism
→ python scripts/s2.py search "transformer attention mechanism"
→ 展示格式化结果

用户: 第3篇看看详情
→ python scripts/s2.py detail "{paper_id}"
→ 展示详情

用户: 第3篇的 IEEE PDF 下载
→ carsi_download(url="...", title="...", database="ieee")
→ PDF 保存到 downloads/ 目录，以论文名命名

用户: 搜不到中文的
→ cnki_search(query="{关键词}")
→ 展示 CNKI 结果
```
