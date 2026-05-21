"""
CNKI (中国知网) database adapter — CDP mode only.

=== 为什么不用 Playwright 直接访问 CNKI？===
CNKI 的反爬系统会检测 Playwright 浏览器（无论 headless 还是有头模式），
直接跳转到滑块验证页（blockPuzzle）。验证无法自动完成。

=== 解决方案：CDP 连接用户的真实 Chrome ===
通过 CDP (Chrome DevTools Protocol) 连接用户已打开的 Chrome 浏览器：
- 用户在自己的 Chrome 中登录 CNKI（机构登录 → 校外访问）
- 代码通过 `playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")` 连接
- CNKI 无法检测到自动化（因为是真实浏览器）
- 搜索、详情、下载全部正常工作

=== 前提条件 ===
1. Chrome 必须以调试模式启动: chrome --remote-debugging-port=9222
2. 用户必须在 Chrome 中登录 CNKI
3. 端口 9222 必须可访问（curl http://127.0.0.1:9222/json/version 验证）

=== 经过验证的 CNKI DOM 选择器 ===
搜索结果:
  - 搜索输入框: input.search-input
  - 搜索按钮: input.search-btn
  - 结果行: .result-table-list tbody tr
  - 标题链接: td.name a.fz14
  - 作者: td.author a.KnowledgeNetLink
  - 期刊: td.source a
  - 日期: td.date
  - 引用数: td.quote
  - 下载数: td.download
  - 结果总数: .pagerTitleCell
  - 翻页输入: input.countPageMark
  - 验证码: #tcaptcha_transform_dy (getBoundingClientRect().top >= 0 表示可见)

详情页:
  - 标题: .brief h1 (需去除 "网络首发"/"附视频" 后缀)
  - 作者: h3.author (第一个是作者，第二个是单位)
  - 摘要: .abstract-text
  - 关键词: p.keywords a
  - 基金: p.funds
  - 分类号: .clc-code
  - 期刊: .doc-top a
  - DOI: .top-tip span a[href*="doi.org"]
  - 下载: #pdfDown / #cajDown / .btn-dlpdf a / .btn-dlcaj a
  - 未登录: .downloadlink.icon-notlogged

=== 已知坑 ===
1. CNKI 搜索页和详情页可能在不同标签页打开（target="_blank"）
2. 验证码出现后需要用户手动滑块验证
3. fsso.cnki.net 的学校搜索用 JS 自动补全，需要触发 keyup 事件
4. CNKI 的 bar.cnki.net 下载服务有独立认证，和 kns.cnki.net 不共享 session
"""

import asyncio
import urllib.parse
from .base import BaseAdapter


# CNKI 搜索结果页的排序按钮 ID 映射
SORT_MAP = {
    "relevance": "FFD",    # 相关性排序
    "date": "PT",          # 发表时间
    "citations": "CF",     # 被引量
    "downloads": "DFR",    # 下载量
}


class CnkiAdapter(BaseAdapter):
    name = "cnki"
    home_url = "https://kns.cnki.net/kns8s/search"
    adv_url = "https://kns.cnki.net/kns/AdvSearch?classid=7NS01R8M"

    # ── 登录 ──────────────────────────────────────────────────────
    # CNKI 登录流程: kns.cnki.net → 机构登录 → 校外访问 → fsso.cnki.net → CARSI IdP
    # 注意: 此方法在 CDP 模式下通常不需要调用（用户在 Chrome 中手动登录）
    # 只在 Playwright 新浏览器模式下使用（已被 CDP 模式取代）

    async def login(self, username: str, password: str, carsi_auth=None) -> dict:
        """Login to CNKI via 机构登录 → 校外访问 → fsso.cnki.net → CARSI.

        流程:
        1. 打开 kns.cnki.net
        2. 点击"机构登录"
        3. 点击"校外访问" → 跳转到 fsso.cnki.net
        4. 在 fsso.cnki.net 搜索学校（JS 自动补全）
        5. CARSI IdP 认证（填写账号密码 + 同意条款）
        6. 回到 kns.cnki.net

        注意: fsso.cnki.net 的搜索是 JS 自动补全，需要通过 keyup 事件触发。
        """
        await self._navigate(self.home_url)
        await asyncio.sleep(2)

        # 点击"机构登录"
        try:
            inst_link = self.page.locator('a:has-text("机构登录"), a:has-text("登录")').first
            if await inst_link.count() > 0:
                await inst_link.click()
                await asyncio.sleep(2)
        except Exception:
            pass

        # 点击"校外访问" — 可能是隐藏元素，用 JS click 兜底
        try:
            offcampus = self.page.locator('a:has-text("校外访问")').first
            if await offcampus.count() > 0:
                await offcampus.click()
                await asyncio.sleep(3)
            else:
                await self.page.evaluate("""() => {
                    const links = document.querySelectorAll('a');
                    for (const a of links) {
                        if (a.textContent?.includes('校外访问')) { a.click(); return; }
                    }
                }""")
                await asyncio.sleep(3)
        except Exception:
            pass

        # fsso.cnki.net: 搜索学校并选择
        # 注意: 必须触发 keyup 事件才能激活自动补全，fill() 不够
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

        # CARSI IdP 认证
        if "idp.xidian.edu.cn" in self.page.url and carsi_auth:
            await carsi_auth._handle_cas_login(self.page, username, password)
            await asyncio.sleep(1)

        # 处理同意条款页面（可能有多轮）
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

        await asyncio.sleep(3)
        url = self.page.url
        if "cnki.net" in url:
            return {"success": True, "url": url}
        return {"success": False, "url": url}

    # ── 搜索 ──────────────────────────────────────────────────────

    async def search(self, query: str, **kwargs) -> dict:
        """基础关键词搜索，支持分页和排序。

        如果提供了高级筛选参数（author/journal/year_start/year_end），
        自动切换到高级搜索页面。

        注意: 搜索输入框的 timeout 设为 90 秒，因为首次可能需要手动过验证码。
        """
        page_num = kwargs.get("page", 1)
        sort = kwargs.get("sort")
        author = kwargs.get("author")
        journal = kwargs.get("journal")
        year_start = kwargs.get("year_start")
        year_end = kwargs.get("year_end")

        # 有高级筛选时用 AdvSearch 页面
        if author or journal or year_start or year_end:
            return await self._advanced_search(
                query, author=author, journal=journal,
                year_start=year_start, year_end=year_end,
                sort=sort,
            )

        await self._navigate(self.home_url)

        # 等搜索框出现（可能需要先过验证码）
        try:
            await self.page.wait_for_selector('input.search-input', timeout=90000)
        except Exception:
            return {"success": False, "error": "timeout — CNKI 可能显示了验证码，请在浏览器中完成后重试"}

        if await self._check_captcha():
            return {"success": False, "error": "captcha — 请在浏览器中手动完成滑块验证后重试"}

        await self.page.fill('input.search-input', query)
        await self.page.click('input.search-btn')

        # 等结果加载
        try:
            await self.page.wait_for_function(
                "document.body.innerText.includes('条结果')", timeout=30000
            )
        except Exception:
            return {"success": False, "error": "timeout waiting for results"}

        await asyncio.sleep(0.5)

        if await self._check_captcha():
            return {"success": False, "error": "captcha"}

        if sort and sort in SORT_MAP:
            await self._apply_sort(SORT_MAP[sort])

        if page_num > 1:
            await self._go_to_page(page_num)

        return await self._extract_results()

    async def _advanced_search(self, query, author=None, journal=None,
                               year_start=None, year_end=None, sort=None) -> dict:
        """高级搜索 — 使用 CNKI 的旧版 AdvSearch 界面。

        旧版界面有固定的 input#txt_1_value1 等选择器，比新版更稳定。
        字段代码: SU=主题, AU=作者, LY=来源, TI=篇名, KY=关键词
        """
        await self._navigate(self.adv_url)

        try:
            await self.page.wait_for_selector('input#txt_1_value1', timeout=30000)
        except Exception:
            return {"success": False, "error": "timeout loading advanced search page"}

        if await self._check_captcha():
            return {"success": False, "error": "captcha"}

        await self.page.fill('input#txt_1_value1', query)

        if author:
            try:
                sel = await self.page.query_selector('select#txt_1_special1')
                if sel:
                    await sel.select_option(value='AU')
                await self.page.fill('input#txt_1_value1', author)
                sel2 = await self.page.query_selector('select#txt_2_special1')
                if sel2:
                    await sel2.select_option(value='SU')
                await self.page.fill('input#txt_2_value1', query)
                await self.page.fill('input#txt_1_value1', author)
            except Exception:
                pass

        if journal:
            try:
                sel = await self.page.query_selector('select#txt_2_special1')
                if sel:
                    await sel.select_option(value='LY')
                await self.page.fill('input#txt_2_value1', journal)
            except Exception:
                pass

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

        await self.page.click('input.btn-search')
        await asyncio.sleep(2)

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
        """点击排序按钮并等待结果刷新。"""
        try:
            await self.page.click(f'a#{sort_id}')
            await self.page.wait_for_function(
                "document.body.innerText.includes('条结果')", timeout=15000
            )
            await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _go_to_page(self, page_num: int):
        """跳转到指定页码。CNKI 的页码输入框是 input.countPageMark。"""
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
        """从搜索结果页提取论文列表。

        返回格式:
        {
            "success": true,
            "total": "10,318",
            "page": "1/300",
            "papers": [{"title": "...", "url": "...", "authors": "...", ...}]
        }
        """
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

    # ── 详情 ──────────────────────────────────────────────────────

    async def detail(self, url: str, **kwargs) -> dict:
        """获取论文详情页完整元数据。

        详情页结构: .brief 容器内包含所有信息。
        作者和单位都在 h3.author 中（第一个是作者，第二个是单位）。
        标题需要去除 "网络首发" 和 "附视频" 后缀。
        """
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

                // 标题: 去除后缀
                const title = (brief.querySelector('h1')?.innerText?.trim() || '')
                    .replace(/\\s*附视频\\s*$/, '')
                    .replace(/\\s*网络首发\\s*$/, '');

                // 作者: 第一个 h3.author 是作者，第二个是单位
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

    # ── 辅助方法 ──────────────────────────────────────────────────

    async def _check_captcha(self) -> bool:
        """检查腾讯滑块验证码是否显示。

        #tcaptcha_transform_dy 元素在页面加载时就存在但隐藏在 top:-1000000px。
        只有当 top >= 0 时才是真正的验证码弹窗。
        """
        try:
            el = await self.page.query_selector('#tcaptcha_transform_dy')
            if el:
                box = await el.bounding_box()
                if box and box["y"] >= 0:
                    return True
        except Exception:
            pass
        return False

    # ── 下载 ──────────────────────────────────────────────────────
    # 注意: 此 download 方法只在非 CDP 模式下使用。
    # CDP 模式下，下载由 server.py 的 handle_cnki_download() 处理，
    # 它使用 page.expect_download() 捕获下载事件并保存到项目目录。

    async def download(self, url: str, **kwargs) -> dict:
        """打开 CNKI 下载页面。用户在浏览器中手动完成下载。

        注意: CNKI 的下载链接会打开新标签页（bar.cnki.net → docdown.cnki.net），
        Playwright 的 expect_download 在某些情况下无法捕获。
        所以此方法只点击链接，不负责保存文件。
        """
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

        await self.page.evaluate("""() => {
            const link = document.querySelector('#pdfDown, .btn-dlpdf a, #cajDown, .btn-dlcaj a');
            if (link) link.click();
        }""")

        return {"success": True, "format": info["format"], "title": info["title"],
                "message": f"已在浏览器中打开 {info['format']} 下载页面。文件将保存到浏览器默认下载目录。"}
