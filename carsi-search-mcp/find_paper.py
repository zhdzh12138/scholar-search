"""Find paper on IEEE + download PDF. Uses cookies, only prompts if expired."""
import asyncio, sys, os
sys.path.insert(0, ".")

from carsi_search.engine import CarsiAuth, XIDIAN_ENTITY_ID
from urllib.parse import quote

PAPER = "Two-stage reconstruction for Co-array 2D DOA estimation of mixed circular and noncircular signals"
OUT_DIR = r"C:\Users\zh\Desktop\ai\xb4f5"
TIMEOUT = 45000

if not os.environ.get("CHROME_PATH"):
    os.environ["CHROME_PATH"] = r"C:\Users\zh\AppData\Local\ms-playwright\chromium-1140\chrome-win64\chrome.exe"

async def accept_cookies(page):
    for t in ["Accept All", "Accept all", "全部接受"]:
        try:
            b = page.locator(f'button:has-text("{t}")').first
            if await b.is_visible(timeout=1200):
                await b.click(); await asyncio.sleep(1); return True
        except: pass
    return False

async def ensure_ieee_auth(auth, page):
    wayf = (
        "https://ieeexplore.ieee.org/servlet/wayf.jsp"
        f"?entityId={XIDIAN_ENTITY_ID}"
        f"&url={quote('https://ieeexplore.ieee.org/Xplore/home.jsp', safe='')}"
    )
    await page.goto(wayf, wait_until="domcontentloaded", timeout=TIMEOUT)
    await asyncio.sleep(2)
    url = page.url

    if "ieeexplore.ieee.org" in url and "wayf" not in url:
        print("   IdP cookie valid — auto-authenticated!")
        return True

    if "idp.xidian.edu.cn" in url and "wayf" not in url:
        print("   Cookies expired — need login")
        u = os.environ.get("XIDIAN_USERNAME") or input("Xuehao: ").strip()
        p = os.environ.get("XIDIAN_PASSWORD") or input("Password: ").strip()
        if not u or not p:
            return False
        await auth._handle_cas_login(page, u, p)
        await auth._handle_consent_pages(page)
        await auth.save_state()
        print("   Login OK, session saved")
        return True

    print(f"   Unexpected URL: {url[:120]}")
    return "ieeexplore.ieee.org" in url

async def main():
    auth = CarsiAuth(headless=False)
    await auth.start()
    try:
        page = await auth.context.new_page()
        page.set_default_timeout(TIMEOUT)

        print("[1/4] Authenticating...")
        if not await ensure_ieee_auth(auth, page):
            print("   Failed to authenticate")
            return

        await page.goto("https://ieeexplore.ieee.org/", wait_until="domcontentloaded", timeout=TIMEOUT)
        await asyncio.sleep(2)
        await accept_cookies(page)

        print(f"\n[2/4] Searching...")
        search_url = f"https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true&queryText={quote(PAPER)}"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=TIMEOUT)
        await asyncio.sleep(4)
        await accept_cookies(page)

        papers = await page.evaluate("""
            () => {
                const items = document.querySelectorAll('.List-results-items .result-item, xpl-results-item');
                return Array.from(items).slice(0, 3).map(item => {
                    const a = item.querySelector('h3 a, h2 a, [class*="title"] a');
                    const au = item.querySelector('[class*="author"]');
                    const ab = item.querySelector('[class*="abstract"], .description');
                    return {
                        title: a?.textContent?.trim() || '',
                        url: a?.href || '',
                        authors: (au?.textContent || '').trim().replace(/\\s+/g, ' '),
                        abstract: (ab?.textContent || '').trim().substring(0, 600),
                    };
                }).filter(p => p.title);
            }
        """)
        print(f"   {len(papers)} results")
        for i, p in enumerate(papers):
            print(f"   {i+1}. {p['title'][:100]}")

        if not papers:
            print("   No results!"); return
        p = papers[0]

        print(f"\n[3/4] Detail...")
        await page.goto(p['url'], wait_until="domcontentloaded", timeout=TIMEOUT)
        await asyncio.sleep(3)

        d = await page.evaluate("""
            () => {
                const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                const au = [...document.querySelectorAll('.authors-info a, [class*="author"] a')]
                    .map(a => norm(a.textContent)).filter(Boolean);
                const ab = norm(document.querySelector('.abstract-text, [class*="abstract"] div')?.textContent);
                const doi = norm(document.querySelector('[class*="doi"] a')?.textContent);
                const pdf = document.querySelector('a[href*="stamp.jsp"]')?.href || '';
                return { title: norm(document.querySelector('h1')?.textContent),
                         authors: au, abstract: ab?.substring(0, 1000), doi, pdfUrl: pdf };
            }
        """)

        print(f"\n   Title: {d['title']}")
        print(f"   Authors: {', '.join(d['authors'][:10])}")
        print(f"   DOI: {d.get('doi', 'N/A')}")
        print(f"   Abstract: {d['abstract'][:400]}...")

        if d.get('pdfUrl'):
            print(f"\n[4/4] Downloading PDF...")
            arnumber = d['pdfUrl'].split('arnumber=')[-1]
            pdf_url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}"
            print(f"   Fetching: {pdf_url[:100]}")

            filename = d['title'][:60].replace('/','_').replace(':','_').replace('?','_').replace('"','_')
            save_path = os.path.join(OUT_DIR, f"{filename}.pdf")

            import base64
            pdf_b64 = await page.evaluate(f"""
                async () => {{
                    try {{
                        const resp = await fetch('{pdf_url}');
                        const blob = await resp.blob();
                        const buf = await blob.arrayBuffer();
                        const bytes = new Uint8Array(buf);
                        let binary = '';
                        for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
                        return btoa(binary);
                    }} catch(e) {{
                        return 'ERROR:' + e.message;
                    }}
                }}
            """)

            if pdf_b64 and pdf_b64.startswith('ERROR:'):
                print(f"   JS fetch failed: {pdf_b64} — fallback to page.goto")
                await page.goto(pdf_url, wait_until="domcontentloaded", timeout=TIMEOUT)
                await asyncio.sleep(3)
                print(f"   PDF page open. Ctrl+S to save.")
            elif pdf_b64:
                pdf_data = base64.b64decode(pdf_b64)
                with open(save_path, "wb") as f:
                    f.write(pdf_data)
                print(f"   Saved: {save_path} ({len(pdf_data)} bytes)")
            else:
                print(f"   Empty response — fallback to page.goto")
                await page.goto(pdf_url, wait_until="domcontentloaded", timeout=TIMEOUT)
                await asyncio.sleep(3)
        else:
            print("\n[4/4] No PDF link")

        input("\nPress Enter...")
    finally:
        await auth.stop()

if __name__ == "__main__":
    asyncio.run(main())
