"""
CNKI (中国知网) database adapter — Playwright (headed mode only).

CNKI's anti-bot blocks headless Playwright. This adapter always uses headed mode.
The first call may show a captcha that the user must solve in the browser window.
After that, the session persists and subsequent calls work without interaction.
"""

import asyncio
import urllib.parse
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

    async def login(self, username: str, password: str, carsi_auth=None) -> dict:
        """Login to CNKI: kns.cnki.net → 机构登录 → 校外访问 → fsso.cnki.net → CARSI IdP.
        This ensures session cookies are set on the kns.cnki.net domain."""
        # Step 1: Navigate to kns.cnki.net search page
        await self._navigate(self.home_url)
        await asyncio.sleep(2)

        # Step 2: Click 机构登录 (institutional login)
        try:
            inst_link = self.page.locator('a:has-text("机构登录"), a:has-text("登录")').first
            if await inst_link.count() > 0:
                await inst_link.click()
                await asyncio.sleep(2)
        except Exception:
            pass

        # Step 3: Click 校外访问 (off-campus access) — navigates to fsso.cnki.net
        try:
            offcampus = self.page.locator('a:has-text("校外访问")').first
            if await offcampus.count() > 0:
                await offcampus.click()
                await asyncio.sleep(3)
            else:
                # Try JS click (element may be hidden)
                await self.page.evaluate("""() => {
                    const links = document.querySelectorAll('a');
                    for (const a of links) {
                        if (a.textContent?.includes('校外访问')) { a.click(); return; }
                    }
                }""")
                await asyncio.sleep(3)
        except Exception:
            pass

        # Step 4: Now on fsso.cnki.net — search for Xidian and trigger CARSI
        if "fsso" in self.page.url or "cnki.net" in self.page.url:
            await self.page.evaluate("""() => {
                const input = document.querySelector('input#o');
                if (input) {
                    input.value = "西安电子科技大学";
                    input.dispatchEvent(new KeyboardEvent('keyup', {key: '学', keyCode: 88, bubbles: true}));
                }
            }""")
            await asyncio.sleep(2)
            await self.page.evaluate("""() => {
                const items = document.querySelectorAll('.auto_show div');
                for (const el of items) {
                    if (el.textContent?.includes('西安电子科技大学')) { el.click(); return; }
                }
            }""")
            await asyncio.sleep(3)

        # Step 5: Handle CARSI IdP
        if "idp.xidian.edu.cn" in self.page.url and carsi_auth:
            await carsi_auth._handle_cas_login(self.page, username, password)
            await asyncio.sleep(1)

        for _ in range(5):
            if "idp.xidian.edu.cn" not in self.page.url:
                break
            await self.page.evaluate("""() => {
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    cb.checked = true; cb.dispatchEvent(new Event('change', {bubbles:true}));
                });
                document.querySelectorAll('button, input[type="submit"]').forEach(b => {
                    if (!(b.textContent||b.value||'').includes('拒绝')) b.click();
                });
            }""")
            await asyncio.sleep(3)

        # Step 6: Should redirect back to kns.cnki.net with session
        await asyncio.sleep(3)
        url = self.page.url
        if "cnki.net" in url:
            return {"success": True, "url": url}
        return {"success": False, "url": url}
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

    async def download(self, url: str, **kwargs) -> dict:
        """Download PDF from CNKI. Intercepts new tab, follows redirect chain to docdown.cnki.net."""
        await self._navigate(url)

        try:
            await self.page.wait_for_selector('.brief h1', timeout=15000)
        except Exception:
            return {"success": False, "error": "timeout loading page"}

        if await self._check_captcha():
            return {"success": False, "error": "captcha"}

        info = await self.page.evaluate("""
            () => {
                const notLogged = document.querySelector('.downloadlink.icon-notlogged')
                    || document.querySelector('[class*="notlogged"]');
                if (notLogged) return { error: 'not_logged_in' };
                const title = document.querySelector('.brief h1')?.innerText?.trim()
                    ?.replace(/\\s*网络首发\\s*$/, '') || '';
                const pdfLink = document.querySelector('#pdfDown, .btn-dlpdf a');
                const cajLink = document.querySelector('#cajDown, .btn-dlcaj a');
                const link = pdfLink || cajLink;
                const format = pdfLink ? 'PDF' : 'CAJ';
                return link ? { format, title } : { error: 'no_download_link' };
            }
        """)

        if info.get("error"):
            return {"success": False, "error": info["error"]}

        # Click download — try new tab first, then direct download
        try:
            async with self.page.context.expect_page(timeout=10000) as np_info:
                await self.page.evaluate("""() => {
                    const link = document.querySelector('#pdfDown, .btn-dlpdf a, #cajDown, .btn-dlcaj a');
                    if (link) link.click();
                }""")
            dl_page = await np_info.value
            await dl_page.wait_for_load_state("domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # Follow redirect chain: bar.cnki.net → docdown.cnki.net
            pdf_url = None
            for _ in range(30):
                current = dl_page.url
                if "docdown.cnki.net" in current:
                    pdf_url = current
                    break
                if "login.cnki.net" in current:
                    return {"success": False, "error": "not_logged_in",
                            "message": "下载需要先通过 fsso.cnki.net 校外访问登录。请先调用 cnki_login。"}
                await asyncio.sleep(1)

            if pdf_url:
                pdf_b64 = await dl_page.evaluate("""async () => {
                    try {
                        const resp = await fetch(window.location.href, {credentials: 'include'});
                        if (!resp.ok) return 'HTTP ' + resp.status;
                        const buf = await resp.arrayBuffer();
                        const bytes = new Uint8Array(buf);
                        let b = '';
                        for (let i = 0; i < bytes.byteLength; i++) b += String.fromCharCode(bytes[i]);
                        return btoa(b);
                    } catch(e) { return 'ERROR:' + e.message; }
                }""")

                if pdf_b64 and not pdf_b64.startswith(('ERROR', 'HTTP')):
                    import base64
                    data = base64.b64decode(pdf_b64)
                    if data[:4] == b'%PDF':
                        download_dir = os.environ.get("DOWNLOAD_DIR", os.getcwd())
                        save_dir = Path(download_dir) / "downloads"
                        save_dir.mkdir(exist_ok=True)
                        save_path = save_dir / f"{info['title'][:60]}.pdf"
                        save_path.write_bytes(data)
                        return {"success": True, "format": "PDF", "title": info["title"],
                                "path": str(save_path), "size": len(data)}

        except Exception:
            # expect_page timed out — try direct download event
            try:
                async with self.page.expect_download(timeout=15000) as dl_info:
                    pass  # download may have already been triggered
                download = await dl_info.value
                download_dir = os.environ.get("DOWNLOAD_DIR", os.getcwd())
                save_path = Path(download_dir) / "downloads" / (download.suggested_filename or f"{info['title'][:60]}.pdf")
                save_path.parent.mkdir(exist_ok=True)
                await download.save_as(str(save_path))
                return {"success": True, "format": info["format"], "title": info["title"],
                        "path": str(save_path), "size": save_path.stat().st_size}
            except Exception:
                pass

        return {"success": False, "error": "download_failed", "title": info["title"]}
