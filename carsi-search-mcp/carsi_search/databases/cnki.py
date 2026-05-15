"""
CNKI (中国知网) database adapter — Playwright (headed mode only).

CNKI's anti-bot blocks headless Playwright. This adapter always uses headed mode.
The first call may show a captcha that the user must solve in the browser window.
After that, the session persists and subsequent calls work without interaction.
"""

import asyncio
from .base import BaseAdapter


class CnkiAdapter(BaseAdapter):
    name = "cnki"
    home_url = "https://kns.cnki.net/kns8s/search"

    async def search(self, query: str, **kwargs) -> dict:
        await self._navigate(self.home_url)

        # Wait for search input (may need captcha solve first)
        try:
            await self.page.wait_for_selector('input.search-input', timeout=90000)
        except Exception:
            return {"success": False, "error": "timeout — CNKI 可能显示了验证码，请在浏览器中完成后重试"}

        # Check captcha
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

        # Extract results
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
