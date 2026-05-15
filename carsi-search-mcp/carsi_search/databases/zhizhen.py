"""
Zhizhen / Chaoxing (智真/超星发现) database adapter.
"""

import asyncio
from playwright.async_api import Page
from .base import BaseAdapter


DOC_TYPE_PREFIX = {1: "JN", 2: "JN", 11: "BK", 3: "DT", 4: "CP", 10: "PT", 6: "ST", 8: "VI", 13: "NP", 21: "TR", 46: "LW", 47: "CA", 85: "IMG"}
DOC_TYPE_CHANNEL = {1: "1,2", 11: "11,12", 3: "3", 4: "4", 10: "10", 6: "6", 8: "8", 13: "13", 21: "21", 46: "46", 47: "47", 85: "85"}


class ZhizhenAdapter(BaseAdapter):
    name = "zhizhen"
    home_url = "https://ss.zhizhen.com/"

    async def search(self, query: str, **kwargs) -> dict:
        field = kwargs.get("field", "Z")
        doc_types = kwargs.get("doc_types", [])
        year_start = kwargs.get("year_start")
        year_end = kwargs.get("year_end")
        language = kwargs.get("language")
        page_num = kwargs.get("page", 1)
        page_size = kwargs.get("page_size", 15)
        sort = kwargs.get("sort")
        adv = kwargs.get("adv")

        if adv:
            expr = adv
        else:
            inner = f"({field}='{query}')"
            if year_start or year_end:
                ys = year_start or "null"
                ye = year_end or "null"
                inner = f"({inner})AND({ys}<Y<{ye})"
            if doc_types:
                prefix = DOC_TYPE_PREFIX.get(doc_types[0])
                if prefix:
                    inner = f"{prefix}({inner})"
            expr = inner

        search_url = f"https://ss.zhizhen.com/s?adv={expr}&aorp=a"
        if language:
            search_url += f"&strchoren={language}"
        if doc_types and DOC_TYPE_CHANNEL.get(doc_types[0]):
            search_url += f"&strchannel={DOC_TYPE_CHANNEL[doc_types[0]]}"
        if page_size != 15:
            search_url += f"&size={page_size}"
        if sort is not None:
            search_url += f"&isort={sort}"

        print(f"[Zhizhen] Search URL: {search_url[:150]}")

        await self._navigate(search_url)
        await asyncio.sleep(1)

        return await self.page.evaluate("""
            () => {
                const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                const totalEl = document.querySelector('.cur-search-count');
                const total = totalEl ? norm(totalEl.textContent).replace(/,/g, '') : '';
                const cards = document.querySelectorAll('.zyList');
                const papers = Array.from(cards).map(card => {
                    const titleA = card.querySelector('.card_name h3 a[href*="detail_"]');
                    const source = (() => {
                        const li = Array.from(card.querySelectorAll('li')).find(
                            li => norm(li.querySelector('span')?.textContent) === '出处'
                        );
                        return norm(li?.querySelector('.zylist_font')?.textContent);
                    })();
                    const dxid = card.querySelector('h3[data-id]')?.dataset?.id
                        || new URL(titleA?.href || '').searchParams.get('dxid');
                    return {
                        title: norm(titleA?.textContent),
                        url: titleA?.href || '',
                        dxid,
                        authors: (() => {
                            const li = Array.from(card.querySelectorAll('li')).find(
                                li => norm(li.querySelector('span')?.textContent) === '作者'
                            );
                            return norm(li?.querySelector('.zylist_font')?.textContent);
                        })(),
                        source,
                        year: (source?.match(/\\b(19|20)\\d{2}\\b/) || [])[0] || '',
                        keywords: (() => {
                            const li = Array.from(card.querySelectorAll('li')).find(
                                li => norm(li.querySelector('span')?.textContent) === '关键词'
                            );
                            return norm(li?.querySelector('.zylist_font')?.textContent);
                        })(),
                        abstract: (() => {
                            const li = Array.from(card.querySelectorAll('li')).find(
                                li => norm(li.querySelector('span')?.textContent) === '摘要'
                            );
                            return norm(li?.querySelector('.zylist_font')?.textContent);
                        })(),
                        cited_by: (() => {
                            const el = card.querySelector('.hitsNum a[href*="refdetail"]');
                            return el ? norm(el.textContent).replace('被引量：', '') : '';
                        })(),
                    };
                }).filter(p => p.title);
                return { success: true, total, papers };
            }
        """)

    async def detail(self, url: str, **kwargs) -> dict:
        dxid = kwargs.get("dxid", "")
        await self._navigate(url)
        await asyncio.sleep(1)

        data = await self.page.evaluate("""
            async (dxid) => {
                const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                const findField = (label) => {
                    const dls = Array.from(document.querySelectorAll('dl.card_line, dl.clearfix, dl'));
                    const clean = s => (s || '').replace(/\\s+/g, '');
                    const target = clean(label);
                    const dl = dls.find(el => {
                        const dtText = clean(el.querySelector('dt')?.textContent || el.querySelector('span.label')?.textContent || '');
                        return dtText && dtText.includes(target);
                    });
                    const dd = dl?.querySelector('dd') || dl?.querySelector('span.zylist_font');
                    return norm(dd?.textContent);
                };
                const findLinks = (label) => {
                    const dls = Array.from(document.querySelectorAll('dl.card_line'));
                    const clean = s => (s || '').replace(/\\s+/g, '');
                    const target = clean(label);
                    const dl = dls.find(dl => clean(dl.querySelector('dt span')?.textContent) === target);
                    return Array.from(dl?.querySelectorAll('dd a') || []).map(a => norm(a.textContent)).filter(Boolean);
                };

                const absEl = document.querySelector('#detailAllAbstractId dd') || document.querySelector('#detailSubAbstractId dd');
                const absClone = absEl?.cloneNode(true);
                absClone?.querySelectorAll('a').forEach(a => a.remove());
                const abstract = norm(absClone?.textContent);

                const venue = ['期刊名', '会议名称', '会议'].map(findField).find(Boolean) || '';
                const doi = findField('d o i');
                const year = findField('年份');

                let citation = '';
                if (dxid) {
                    try {
                        const resp = await fetch(`/fav/outputDetailRefer?type=3&dxid=${dxid}`);
                        citation = (await resp.text()).trim();
                    } catch(e) {}
                }

                return {
                    abstract, venue, doi, year,
                    keywords: findLinks('关键词'),
                    authors: findLinks('作者').length ? findLinks('作者') :
                        (findField('作者') || '').split(/[;；,，]/).map(s => norm(s)).filter(Boolean),
                    affiliation: findField('作者单位'),
                    funding: findField('基金'),
                    volume: findField('卷号'),
                    issue: findField('期号'),
                    pages: findField('页码'),
                    issn: findField('I S S N'),
                    impactFactor: (document.querySelector('.Influence')?.textContent?.match(/^[\\d.]+/) || [])[0] || null,
                    indexing: Array.from(document.querySelectorAll('.FindLabel')).map(el => el.textContent.trim()).filter(Boolean),
                    citation,
                };
            }
        """, dxid)

        return {"success": True, **data}
