#!/usr/bin/env python3
"""Semantic Scholar API helper - calls API and returns formatted text.

Usage:
    python s2.py search "query" [--limit N]
    python s2.py detail PAPER_ID
    python s2.py citations PAPER_ID [--limit N]
    python s2.py references PAPER_ID [--limit N]
    python s2.py recommend PAPER_ID [--limit N]
    python s2.py author "name" [--limit N]
"""

import sys
import os
import json
import urllib.request
import urllib.parse
import urllib.error

S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_REC = "https://api.semanticscholar.org/recommendations/v1"

PAPER_FIELDS = "title,authors,year,citationCount,venue,abstract,externalIds,openAccessPdf,publicationDate,fieldsOfStudy,isOpenAccess,journal,publicationTypes,referenceCount,influentialCitationCount"
PAPER_FIELDS_FULL = PAPER_FIELDS + ",tldr,keywords"  # for single-paper detail endpoint
CITATION_FIELDS = "title,authors,year,isInfluential,contexts"
AUTHOR_FIELDS = "name,affiliations,paperCount,citationCount,hIndex"


def _api_key_header():
    key = os.environ.get("S2_API_KEY", "")
    return {"x-api-key": key} if key else {}


def _get(url):
    headers = _api_key_header()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {body[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def _fmt_authors(authors, max_show=5):
    if not authors:
        return "Unknown"
    names = [a.get("name", "?") for a in authors[:max_show]]
    text = ", ".join(names)
    if len(authors) > max_show:
        text += f" et al. (共{len(authors)}人)"
    return text


def _fmt_paper(p, index=None):
    prefix = f"[{index}] " if index else ""
    doi = (p.get("externalIds") or {}).get("DOI", "")
    oa = p.get("openAccessPdf") or {}
    pdf_url = oa.get("url", "")
    tldr = p.get("tldr") or {}
    tldr_text = tldr.get("text", "") if isinstance(tldr, dict) else ""

    lines = [f"{prefix}**{p.get('title', '?')}**"]
    lines.append(f"  作者: {_fmt_authors(p.get('authors'))}")
    year = p.get("year", "?")
    venue = p.get("venue") or ""
    cites = p.get("citationCount", 0)
    lines.append(f"  年份: {year} | 会议: {venue} | 引用: {cites}")

    inf = p.get("influentialCitationCount")
    ref_count = p.get("referenceCount")
    extra = []
    if inf: extra.append(f"Influential: {inf}")
    if ref_count: extra.append(f"References: {ref_count}")
    if extra:
        lines.append(f"  {' | '.join(extra)}")

    journal = p.get("journal") or {}
    if isinstance(journal, dict):
        vol = journal.get("volume", "")
        pages = journal.get("pages", "")
        if vol or pages:
            lines.append(f"  期刊: Vol.{vol} pp.{pages}")

    pub_types = p.get("publicationTypes")
    if pub_types:
        lines.append(f"  类型: {', '.join(pub_types)}")

    is_oa = p.get("isOpenAccess")
    if is_oa is not None:
        lines.append(f"  访问: {'开放获取' if is_oa else '付费'}")

    if doi:
        lines.append(f"  DOI: {doi}")
    lines.append(f"  URL: {p.get('url', '')}")
    if pdf_url:
        lines.append(f"  PDF: {pdf_url}")

    if tldr_text:
        lines.append(f"  TLDR: {tldr_text[:300]}")
    elif p.get("abstract"):
        lines.append(f"  摘要: {p['abstract'][:300]}...")

    keywords = p.get("keywords")
    if keywords:
        lines.append(f"  关键词: {', '.join(keywords[:8])}")

    fields = p.get("fieldsOfStudy")
    if fields:
        lines.append(f"  领域: {', '.join(fields)}")

    return "\n".join(lines)


def cmd_search(args):
    query = args[0] if args else ""
    limit = 20
    if "--limit" in args:
        idx = args.index("--limit")
        limit = int(args[idx + 1])

    encoded = urllib.parse.quote_plus(query)
    url = f"{S2_BASE}/paper/search/bulk?query={encoded}&limit={limit}&fields={PAPER_FIELDS}"
    data = _get(url)

    if "error" in data:
        return f"错误: {data['error']}"

    total = data.get("total", 0)
    papers = data.get("data", [])
    out = [f"搜索 \"{query}\"：共 {total} 条结果\n"]
    for i, p in enumerate(papers):
        out.append(_fmt_paper(p, i + 1))
    return "\n\n".join(out)


def cmd_detail(args):
    paper_id = args[0] if args else ""
    url = f"{S2_BASE}/paper/{urllib.parse.quote(paper_id, safe=':')}/?fields={PAPER_FIELDS_FULL}"
    data = _get(url)

    if "error" in data:
        return f"错误: {data['error']}"

    return _fmt_paper(data)


def cmd_citations(args):
    paper_id = args[0] if args else ""
    limit = 20
    if "--limit" in args:
        idx = args.index("--limit")
        limit = int(args[idx + 1])

    url = f"{S2_BASE}/paper/{urllib.parse.quote(paper_id, safe=':')}/citations?fields={CITATION_FIELDS}&limit={limit}"
    data = _get(url)

    if "error" in data:
        return f"错误: {data['error']}"

    items = data.get("data", [])
    total = data.get("total", len(items))
    out = [f"引用该论文的文献：共 {total} 条\n"]
    for i, item in enumerate(items):
        p = item.get("citingPaper", {})
        extra = ""
        if item.get("isInfluential"):
            extra += " [重要引用]"
        contexts = item.get("contexts", [])
        if contexts:
            extra += f"\n    上下文: {contexts[0][:150]}..."
        out.append(_fmt_paper(p, i + 1) + extra)
    return "\n\n".join(out)


def cmd_references(args):
    paper_id = args[0] if args else ""
    limit = 20
    if "--limit" in args:
        idx = args.index("--limit")
        limit = int(args[idx + 1])

    url = f"{S2_BASE}/paper/{urllib.parse.quote(paper_id, safe=':')}/references?fields={CITATION_FIELDS}&limit={limit}"
    data = _get(url)

    if "error" in data:
        return f"错误: {data['error']}"

    items = data.get("data", [])
    total = data.get("total", len(items))
    out = [f"参考文献：共 {total} 条\n"]
    for i, item in enumerate(items):
        p = item.get("citedPaper", {})
        extra = ""
        if item.get("isInfluential"):
            extra += " [重要引用]"
        out.append(_fmt_paper(p, i + 1) + extra)
    return "\n\n".join(out)


def cmd_recommend(args):
    paper_id = args[0] if args else ""
    limit = 20
    if "--limit" in args:
        idx = args.index("--limit")
        limit = int(args[idx + 1])

    url = f"{S2_REC}/papers/forpaper/{urllib.parse.quote(paper_id, safe=':')}?limit={limit}&fields={PAPER_FIELDS}"
    data = _get(url)

    if "error" in data:
        return f"错误: {data['error']}"

    papers = data.get("recommendedPapers", [])
    out = [f"推荐论文：共 {len(papers)} 条\n"]
    for i, p in enumerate(papers):
        out.append(_fmt_paper(p, i + 1))
    return "\n\n".join(out)


def cmd_author(args):
    query = args[0] if args else ""
    limit = 10
    if "--limit" in args:
        idx = args.index("--limit")
        limit = int(args[idx + 1])

    encoded = urllib.parse.quote_plus(query)
    url = f"{S2_BASE}/author/search?query={encoded}&fields={AUTHOR_FIELDS}&limit={limit}"
    data = _get(url)

    if "error" in data:
        return f"错误: {data['error']}"

    authors = data.get("data", [])
    total = data.get("total", 0)
    out = [f"搜索作者 \"{query}\"：共 {total} 条结果\n"]
    for i, a in enumerate(authors):
        affs = ", ".join(a.get("affiliations", []) or []) or "N/A"
        out.append(
            f"[{i+1}] **{a.get('name', '?')}**\n"
            f"  机构: {affs}\n"
            f"  论文: {a.get('paperCount', 0)} | 引用: {a.get('citationCount', 0)} | h-index: {a.get('hIndex', 0)}"
        )
    return "\n\n".join(out)


COMMANDS = {
    "search": cmd_search,
    "detail": cmd_detail,
    "citations": cmd_citations,
    "references": cmd_references,
    "recommend": cmd_recommend,
    "author": cmd_author,
}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}. Available: {', '.join(COMMANDS)}")
        sys.exit(1)

    result = COMMANDS[cmd](sys.argv[2:])
    print(result)
