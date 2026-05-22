"""
ScienceDirect (Elsevier) database adapter.
"""

import asyncio
from urllib.parse import quote
from playwright.async_api import Page
from .base import BaseAdapter


class ScienceDirectAdapter(BaseAdapter):
    name = "sciencedirect"
    home_url = "https://www.sciencedirect.com/"

    async def search(self, query: str, **kwargs) -> dict:
        search_url = (
            "https://www.sciencedirect.com/search?"
            f"qs={quote(query)}&show=25"
        )
        await self._navigate(search_url)
        await asyncio.sleep(4)

        # 检测 Cloudflare 验证码，等待用户手动完成
        captcha_result = await self._check_and_notify_captcha()
        if captcha_result:
            return captcha_result

        # 等搜索结果加载（标题链接 + PDF 链接）
        try:
            await self.page.wait_for_selector(
                'a[href*="/science/article/pii/"]', timeout=15000
            )
            # 明确等 PDF 链接加载
            try:
                await self.page.wait_for_selector('a.download-link', timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(1)
        except Exception:
            # 可能验证码又出现了
            captcha_result = await self._check_and_notify_captcha()
            if captcha_result:
                return captcha_result
            return {"success": False, "error": "timeout — 搜索结果未加载，可能页面结构变化"}

        result = await self.page.evaluate("""
            () => {
                // 从 "View PDF" 链接提取论文（这些是有 PDF 的）
                const pdfLinks = document.querySelectorAll('a.download-link');
                const papers = [];
                const seenPii = new Set();

                for (const pdfA of pdfLinks) {
                    const m = pdfA.href.match(/\\/pii\\/([A-Z0-9]+)/);
                    if (!m) continue;
                    const pii = m[1];
                    if (seenPii.has(pii)) continue;
                    seenPii.add(pii);

                    // 找到包含标题链接和 PDF 链接的共同祖先
                    let container = pdfA;
                    for (let i = 0; i < 10 && container; i++) {
                        const t = container.querySelector('a[href*="/science/article/pii/"]');
                        if (t && t.textContent.trim().length > 10) break;
                        container = container.parentElement;
                    }

                    // 从容器中找标题链接
                    const titleA = container?.querySelector('a[href*="/science/article/pii/"]');
                    const title = (titleA?.textContent || '').replace(/\\s+/g, ' ').trim();
                    const url = titleA?.href || ('https://www.sciencedirect.com/science/article/pii/' + pii);

                    if (!title || title.length < 5) continue;

                    const authors = container?.querySelector(
                        '[class*="author"], [data-test="author"], .search-result-authors'
                    )?.textContent?.replace(/\\s+/g, ' ')?.trim() || '';

                    const yearMatch = container?.textContent?.match(/\\b(20\\d{2})\\b/);
                    const year = yearMatch ? yearMatch[1] : '';

                    const absEl = container?.querySelector(
                        '[class*="abstract"], [class*="snippet"], .search-result-snippet'
                    );
                    const abstract = (absEl?.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 300);

                    papers.push({ title, url, pii, authors, year, abstract, pdfUrl: pdfA.href });
                }

                // 如果 "View PDF" 链接提取的论文不够，补充没有 PDF 链接的论文
                if (papers.length < 5) {
                    const allLinks = document.querySelectorAll('a[href*="/science/article/pii/"]');
                    for (const a of allLinks) {
                        const href = a.href;
                        const m2 = href.match(/\\/pii\\/([A-Z0-9]+)/);
                        if (!m2) continue;
                        const pii2 = m2[1];
                        if (seenPii.has(pii2)) continue;
                        seenPii.add(pii2);

                        const title2 = (a.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (!title2 || title2.length < 5) continue;

                        const container2 = a.closest('li, div, article, [class*="result"]')
                            || a.parentElement?.parentElement;
                        const authors2 = container2?.querySelector('[class*="author"]')?.textContent?.replace(/\\s+/g, ' ')?.trim() || '';
                        const yearMatch2 = container2?.textContent?.match(/\\b(20\\d{2})\\b/);

                        papers.push({
                            title: title2, url: href, pii: pii2,
                            authors: authors2,
                            year: yearMatch2 ? yearMatch2[1] : '',
                            abstract: '',
                            pdfUrl: href + '/pdfft?isDTMRedir=true&download=true'
                        });
                    }
                }

                const body = document.body?.innerText || '';
                const totalMatch = body.match(/([\\d,]+)\\s*[Rr]esult/);
                const total = totalMatch ? totalMatch[1] : String(papers.length);

                return { success: true, total, papers };
            }
        """)

        return result

    async def detail(self, url: str, **kwargs) -> dict:
        await self._navigate(url)

        captcha_result = await self._check_and_notify_captcha()
        if captcha_result:
            return captcha_result

        try:
            await self.page.wait_for_selector('h1', timeout=15000)
        except Exception:
            pass

        captcha_result = await self._check_and_notify_captcha()
        if captcha_result:
            return captcha_result

        data = await self.page.evaluate("""
            () => {
                const norm = s => (s || '').replace(/\\s+/g, ' ').trim();

                // 标题：去掉常见前缀
                let title = norm(
                    document.querySelector('h1')?.textContent
                    || document.querySelector('[class*="title"]')?.textContent
                );
                title = title.replace(/^(Research paper|Review article|Short communication|Editorial|Letter|Perspective|Case report|Technical note)\\s*/i, '');

                // 作者：从 content-authors 或 author-group 提取
                let authors = [];
                const authorEl = document.querySelector('.content-authors, .author-group');
                if (authorEl) {
                    let authorText = norm(authorEl.textContent || '');
                    // 去掉前缀 "Author links open overlay panel"
                    authorText = authorText.replace(/^Author links open overlay panel\\s*/i, '');
                    // 去掉 "Show more" 等后缀
                    authorText = authorText.replace(/Show m?o?r?e?.*$/i, '').trim();
                    // 按逗号分隔
                    authors = authorText.split(',').map(s => norm(s)).filter(t => t && t.length > 1);
                }

                const abstractEl = document.querySelector(
                    '#abstracts, [class*="abstract"], .abstract.author'
                );
                let abstract = norm(abstractEl?.textContent || '');
                abstract = abstract.replace(/^Abstract\\s*/i, '');

                const doiEl = document.querySelector('a[href*="doi.org"], [class*="doi"]');
                const doiText = doiEl?.href?.match(/doi\\.org\\/(.+)/)?.[1]
                    || norm(doiEl?.textContent);

                const keywords = Array.from(
                    document.querySelectorAll('[class*="keyword"] span, .keyword a')
                ).map(k => norm(k.textContent)).filter(t => t && t !== ';');

                const journal = norm(
                    document.querySelector('a[title*="source"], [class*="publication"], .publication-title-link')?.textContent
                );

                // 查找真正的 PDF 直链
                let pdfUrl = '';
                const pdfLink = document.querySelector(
                    'a.download-link, a[href*="pdf.sciencedirectassets"], a[href*="/pdfft"], a[data-test="pdf-link"]'
                );
                if (pdfLink) {
                    pdfUrl = pdfLink.href;
                }
                // 回退到 /pdfft 模式
                if (!pdfUrl) {
                    const piiMatch = location.href.match(/\\/pii\\/([A-Z0-9]+)/);
                    const pii = piiMatch ? piiMatch[1] : '';
                    if (pii) {
                        pdfUrl = location.origin + '/science/article/pii/' + pii
                            + '/pdfft?isDTMRedir=true&download=true';
                    }
                }

                return {
                    title, authors, abstract, doi: doiText || '',
                    keywords, journal, pdfUrl, url: location.href
                };
            }
        """)

        return {"success": True, **data}

    async def _check_bot_challenge(self) -> bool:
        """检测 Cloudflare bot 验证页面。"""
        try:
            text = await self.page.evaluate(
                "() => document.body?.innerText?.slice(0, 1000) || ''"
            )
            if "Are you a robot" in text:
                return True
            if "Just a moment" in text and ("challenge" in text.lower() or "checking" in text.lower()):
                return True
        except Exception:
            pass
        return False

    async def _check_and_notify_captcha(self) -> dict | None:
        """检测 Cloudflare 验证码，检测到立即返回错误（不等待）。返回 None 表示无验证码。"""
        if await self._check_bot_challenge():
            return {"success": False, "error": "captcha"}
        return None

        return {"success": False, "error": "captcha"}
