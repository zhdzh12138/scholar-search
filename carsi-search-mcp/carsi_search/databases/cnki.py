"""
CNKI (中国知网) database adapter — Playwright (headed mode only).

CNKI's anti-bot blocks headless Playwright. This adapter always uses headed mode.
The first call may show a captcha that the user must solve in the browser window.
After that, the session persists and subsequent calls work without interaction.
"""

import asyncio
from .base import BaseAdapter


# Sort option IDs on CNKI results page
SORT_MAP = {
    "relevance": "FFD",
    "date": "PT",
    "citations": "CF",
    "downloads": "DFR",
}


class CnkiAdapter(BaseAdapter):
    name = "cnki"
    home_url = "https://kns.cnki.net/kns8s/search"
    adv_url = "https://kns.cnki.net/kns/AdvSearch?classid=7NS01R8M"

    async def search(self, query: str, **kwargs) -> dict:
        """Basic keyword search with optional pagination and sort."""
        page_num = kwargs.get("page", 1)
        sort = kwargs.get("sort")  # "relevance", "date", "citations", "downloads"
        author = kwargs.get("author")
        journal = kwargs.get("journal")
        year_start = kwargs.get("year_start")
        year_end = kwargs.get("year_end")

        # If advanced filters are provided, use advanced search
        if author or journal or year_start or year_end:
            return await self._advanced_search(
                query, author=author, journal=journal,
                year_start=year_start, year_end=year_end,
                sort=sort,
            )

        await self._navigate(self.home_url)

        # Wait for search input
        try:
            await self.page.wait_for_selector('input.search-input', timeout=90000)
        except Exception:
            return {"success": False, "error": "timeout — CNKI 可能显示了验证码，请在浏览器中完成后重试"}

        if await self._check_captcha():
            return {"success": False, "error": "captcha — 请在浏览器中手动完成滑块验证后重试"}

        # Fill and submit
        await self.page.fill('input.search-input', query)
        await self.page.click('input.search-btn')

        # Wait for results
        try:
            await self.page.wait_for_function(
                "document.body.innerText.includes('条结果')", timeout=30000
            )
        except Exception:
            return {"success": False, "error": "timeout waiting for results"}

        await asyncio.sleep(0.5)

        if await self._check_captcha():
            return {"success": False, "error": "captcha"}

        # Apply sort if specified
        if sort and sort in SORT_MAP:
            await self._apply_sort(SORT_MAP[sort])

        # Navigate to specific page if not first
        if page_num > 1:
            await self._go_to_page(page_num)

        return await self._extract_results()

    async def _advanced_search(self, query, author=None, journal=None,
                               year_start=None, year_end=None, sort=None) -> dict:
        """Advanced search with field filters using CNKI old-style interface."""
        await self._navigate(self.adv_url)

        try:
            await self.page.wait_for_selector('input#txt_1_value1', timeout=30000)
        except Exception:
            return {"success": False, "error": "timeout loading advanced search page"}

        if await self._check_captcha():
            return {"success": False, "error": "captcha"}

        # Fill subject (主题) field with query
        await self.page.fill('input#txt_1_value1', query)

        # Fill author if provided
        if author:
            try:
                # Click dropdown to switch field type to author
                sel = await self.page.query_selector('select#txt_1_special1')
                if sel:
                    await sel.select_option(value='AU')
                await self.page.fill('input#txt_1_value1', author)
                # Need to re-fill subject in a different row
                # Actually, use the second row for author
                sel2 = await self.page.query_selector('select#txt_2_special1')
                if sel2:
                    await sel2.select_option(value='SU')
                await self.page.fill('input#txt_2_value1', query)
                # Re-set first row to author
                await self.page.fill('input#txt_1_value1', author)
            except Exception:
                pass

        # Fill journal source if provided
        if journal:
            try:
                sel = await self.page.query_selector('select#txt_2_special1')
                if sel:
                    await sel.select_option(value='LY')
                await self.page.fill('input#txt_2_value1', journal)
            except Exception:
                pass

        # Set date range if provided
        if year_start or year_end:
            try:
                start = year_start or "1900"
                end = year_end or "2026"
                date_input = await self.page.query_selector('input#txt_1_datestart')
                if date_input:
                    await self.page.fill('input#txt_1_datestart', start)
                    await self.page.fill('input#txt_1_dateend', end)
            except Exception:
                pass

        # Submit
        await self.page.click('input.btn-search')
        await asyncio.sleep(2)

        # Wait for results
        try:
            await self.page.wait_for_function(
                "document.body.innerText.includes('条结果') || document.body.innerText.includes('找到')",
                timeout=30000
            )
        except Exception:
            return {"success": False, "error": "timeout waiting for results"}

        await asyncio.sleep(0.5)

        if await self._check_captcha():
            return {"success": False, "error": "captcha"}

        if sort and sort in SORT_MAP:
            await self._apply_sort(SORT_MAP[sort])

        return await self._extract_results()

    async def _apply_sort(self, sort_id: str):
        """Click sort option on results page."""
        try:
            await self.page.click(f'a#{sort_id}')
            await self.page.wait_for_function(
                "document.body.innerText.includes('条结果')", timeout=15000
            )
            await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _go_to_page(self, page_num: int):
        """Navigate to a specific page number."""
        try:
            page_input = await self.page.query_selector('input.countPageMark')
            if page_input:
                await page_input.fill(str(page_num))
                await page_input.press('Enter')
                await self.page.wait_for_function(
                    "document.body.innerText.includes('条结果')", timeout=15000
                )
                await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _extract_results(self) -> dict:
        """Extract search results from current page."""
        result = await self.page.evaluate("""
            () => {
                const rows = document.querySelectorAll('.result-table-list tbody tr');
                const results = Array.from(rows).map(row => {
                    const titleLink = row.querySelector('td.name a.fz14');
                    const authors = Array.from(
                        row.querySelectorAll('td.author a.KnowledgeNetLink') || []
                    ).map(a => a.innerText?.trim());
                    return {
                        title: titleLink?.innerText?.trim() || '',
                        url: titleLink?.href || '',
                        authors: authors.join('; '),
                        journal: row.querySelector('td.source a')?.innerText?.trim() || '',
                        date: row.querySelector('td.date')?.innerText?.trim() || '',
                        citations: row.querySelector('td.quote')?.innerText?.trim() || '',
                        downloads: row.querySelector('td.download')?.innerText?.trim() || '',
                    };
                }).filter(p => p.title);
                return {
                    success: true,
                    total: document.querySelector('.pagerTitleCell')?.innerText?.match(/([\\d,]+)/)?.[1] || '0',
                    page: document.querySelector('.countPageMark')?.innerText || '1/1',
                    papers: results,
                };
            }
        """)
        return result

    async def detail(self, url: str, **kwargs) -> dict:
        await self._navigate(url)

        try:
            await self.page.wait_for_selector('.brief', timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(0.5)

        if await self._check_captcha():
            return {"success": False, "error": "captcha"}

        result = await self.page.evaluate("""
            () => {
                const brief = document.querySelector('.brief');
                if (!brief) return { success: false, error: 'Paper detail section not found' };

                const title = (brief.querySelector('h1')?.innerText?.trim() || '')
                    .replace(/\\s*附视频\\s*$/, '')
                    .replace(/\\s*网络首发\\s*$/, '');

                const authorH3s = brief.querySelectorAll('h3.author');
                const authors = [];
                if (authorH3s[0]) {
                    authorH3s[0].querySelectorAll('a').forEach(a => {
                        authors.push(a.innerText?.replace(/\\d+$/, '').trim());
                    });
                }
                const affiliations = [];
                if (authorH3s.length > 1) {
                    authorH3s[1].querySelectorAll('a').forEach(a => {
                        affiliations.push(a.innerText?.trim());
                    });
                }

                const abstract = document.querySelector('.abstract-text')?.innerText?.trim() || '';
                const keywordsP = document.querySelector('p.keywords');
                const keywords = keywordsP
                    ? Array.from(keywordsP.querySelectorAll('a')).map(a => a.innerText?.replace(/;$/, '').trim())
                    : [];
                const fund = document.querySelector('p.funds')?.innerText?.trim() || '';
                const classification = document.querySelector('.clc-code')?.innerText?.trim() || '';
                const journal = document.querySelector('.doc-top')?.querySelector('a')?.innerText?.trim() || '';
                const pubInfo = document.querySelector('.head-time')?.innerText?.trim() || '';
                const doi = document.querySelector('.top-tip span a[href*="doi.org"]')?.innerText?.trim() || '';
                const isOnlineFirst = !!brief.querySelector('.icon-shoufa');

                return {
                    success: true, title, authors, affiliations, abstract, keywords,
                    fund, classification, journal, pubInfo, doi, isOnlineFirst,
                };
            }
        """)
        return result

    async def _check_captcha(self) -> bool:
        try:
            el = await self.page.query_selector('#tcaptcha_transform_dy')
            if el:
                box = await el.bounding_box()
                if box and box["y"] >= 0:
                    return True
        except Exception:
            pass
        return False
