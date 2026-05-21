"""
IEEE Xplore database adapter.
"""

import asyncio
from urllib.parse import quote
from playwright.async_api import Page
from .base import BaseAdapter


class IeeeAdapter(BaseAdapter):
    name = "ieee"
    home_url = "https://ieeexplore.ieee.org/"

    async def search(self, query: str, **kwargs) -> dict:
        search_url = (
            "https://ieeexplore.ieee.org/search/searchresult.jsp?"
            f"newsearch=true&queryText={quote(query)}"
        )
        await self._navigate(search_url)
        await asyncio.sleep(4)

        for t in ["Accept All", "Accept all", "全部接受"]:
            try:
                b = self.page.locator(f'button:has-text("{t}")').first
                if await b.is_visible(timeout=1500):
                    await b.click()
                    await asyncio.sleep(1)
                    await self._navigate(search_url)
                    await asyncio.sleep(3)
                    break
            except Exception:
                pass

        result = await self.page.evaluate("""
            () => {
                const items = document.querySelectorAll('.List-results-items .result-item');
                const papers = Array.from(items).slice(0, 30).map(item => {
                    const a = item.querySelector('h3 a, h2 a, [class*="title"] a');
                    const au = item.querySelector('[class*="author"]');
                    const yr = item.querySelector('[class*="year"]');
                    const ab = item.querySelector('[class*="abstract"], .description');
                    const url = a?.href || '';
                    const arnumber = (url.match(/document\\/(\\d+)/) || [])[1] || '';
                    return {
                        title: a?.textContent?.trim() || '',
                        url,
                        authors: (au?.textContent || '').trim().replace(/\\s+/g, ' '),
                        year: (yr?.textContent?.match(/\\d{4}/) || [])[0] || '',
                        abstract: (ab?.textContent || '').trim().substring(0, 300),
                        pdfUrl: arnumber ? 'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=' + arnumber : '',
                    };
                }).filter(p => p.title);

                const body = document.body?.innerText || '';
                const totalMatch = body.match(/([\\d,]+)\\s*[Rr]esults/);
                const total = totalMatch ? totalMatch[1] : '';

                return { success: true, total, papers };
            }
        """)

        return result

    async def detail(self, url: str, **kwargs) -> dict:
        await self._navigate(url)

        try:
            show_more = await self.page.query_selector(
                'button.more-less-btn, button[data-testid="abstract-more"], '
                '[class*="abstract"] button, [class*="show-more"], '
                'button:has-text("Show More Metadata"), button:has-text("Show More")'
            )
            if show_more:
                await show_more.click()
                await self.page.wait_for_timeout(500)
        except Exception:
            pass

        data = await self.page.evaluate("""
            () => {
                const norm = s => (s || '').replace(/\\s+/g, ' ').trim();

                const title = norm(document.querySelector('h1')?.textContent
                    || document.querySelector('.document-title')?.textContent);

                const authors = Array.from(
                    document.querySelectorAll('.authors-info a, .author a, [class*="author"] a')
                ).map(a => norm(a.textContent)).filter(Boolean);

                const abstractEl = document.querySelector('div.abstract-text-content, .abstract-text, .article-abstract');
                let abstract = '';
                if (abstractEl) {
                    const clone = abstractEl.cloneNode(true);
                    clone.querySelectorAll('.MathJax, .MathJax_Display, script, .mjx-math, .katex-html').forEach(el => el.remove());
                    abstract = norm(clone.textContent);
                }

                const doi = norm(
                    document.querySelector('.stats-document-abstract-doi, [class*="doi"] a')?.textContent
                );

                const keywords = Array.from(
                    document.querySelectorAll('.keyword a, .keywords a, [class*="keyword"] a')
                ).map(a => norm(a.textContent)).filter(Boolean);

                const pdfLink = document.querySelector('a[href*="stamp.jsp"], a[href*="pdf"], .pdf-link a');
                const pdfUrl = pdfLink?.href || '';

                return { title, authors, abstract, doi, keywords, pdfUrl };
            }
        """)

        return {"success": True, **data}
