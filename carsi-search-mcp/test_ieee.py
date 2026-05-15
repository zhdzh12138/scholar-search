"""Test: IEEE — real auth check via PDF access, not paper count."""
import asyncio, sys, os
sys.path.insert(0, ".")

from carsi_search.engine import CarsiAuth, XIDIAN_ENTITY_ID
from urllib.parse import quote

TIMEOUT = 45000

TEST_PAPER = "https://ieeexplore.ieee.org/document/5288526/"

async def has_institutional_access(page):
    await page.goto(TEST_PAPER, wait_until="domcontentloaded", timeout=TIMEOUT)
    await asyncio.sleep(3)
    result = await page.evaluate("""
        () => {
            const stampLinks = document.querySelectorAll('a[href*="stamp.jsp"]');
            const body = document.body?.innerText || '';
            const denied = body.includes('subscription') || body.includes('purchase')
                        || body.includes('Sign In') || body.includes('login required');
            return {
                stampCount: stampLinks.length,
                denied,
                title: document.title,
                bodySnippet: body.substring(0, 300)
            };
        }
    """)
    print(f"[IEEE] Auth check: stamp={result['stampCount']} title='{result['title'][:60]}'")
    has_access = result['stampCount'] > 0
    return has_access, result

async def accept_cookies(page):
    for btn_text in ["全部接受", "Accept All", "Accept all"]:
        try:
            b = page.locator(f'button:has-text("{btn_text}")').first
            if await b.is_visible(timeout=1500):
                await b.click()
                print(f"[IEEE] Cookie accepted: {btn_text}")
                await asyncio.sleep(1)
                return True
        except Exception:
            pass
    return False

async def main():
    auth = CarsiAuth(headless=False)
    await auth.start()

    try:
        page = await auth.context.new_page()
        page.set_default_timeout(TIMEOUT)

        await page.goto("https://ieeexplore.ieee.org/", wait_until="domcontentloaded", timeout=TIMEOUT)
        await asyncio.sleep(2)
        await accept_cookies(page)

        has_access, info = await has_institutional_access(page)

        if not has_access:
            print("\n[IEEE] -- No institutional access -- logging in...")
            username = os.environ.get("XIDIAN_USERNAME") or input("学号: ").strip()
            password = os.environ.get("XIDIAN_PASSWORD") or input("密码: ").strip()

            wayf_url = (
                "https://ieeexplore.ieee.org/servlet/wayf.jsp"
                f"?entityId={XIDIAN_ENTITY_ID}"
                f"&url={quote('https://ieeexplore.ieee.org/Xplore/home.jsp', safe='')}"
            )
            await page.goto(wayf_url, wait_until="domcontentloaded", timeout=TIMEOUT)
            await asyncio.sleep(2)
            print(f"[IEEE] wayf -> {page.url[:120]}")

            if "idp.xidian.edu.cn" in page.url and "wayf" not in page.url:
                await auth._handle_cas_login(page, username, password)
                await auth._handle_consent_pages(page)
                await auth.save_state()
                print(f"[IEEE] [OK] Session saved. Post-consent: {page.url[:120]}")

                await page.goto("https://ieeexplore.ieee.org/", wait_until="domcontentloaded", timeout=TIMEOUT)
                await asyncio.sleep(2)
                await accept_cookies(page)
                has_access, _ = await has_institutional_access(page)
                print(f"[IEEE] Auth verified: {has_access}")
            else:
                print(f"[IEEE] [WARN] Not at IdP: {page.url[:120]}")
        else:
            print("[IEEE] [OK] Already authenticated via cookies — skipping login")

        if has_access:
            pdf_url = await page.evaluate(
                "() => [...document.querySelectorAll('a')].find(a => a.href.includes('stamp.jsp'))?.href || ''"
            )
            if pdf_url:
                print(f"[IEEE] PDF URL: {pdf_url[:120]}")
                await page.goto(pdf_url, wait_until="domcontentloaded", timeout=TIMEOUT)
                await asyncio.sleep(2)
                print(f"[IEEE] PDF result: {'[OK] OK' if 'stamp' in page.url else '[WARN] Check ' + page.url[:80]}")

            print("\n[IEEE] Search test...")
            await page.goto(
                "https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true&queryText=machine+learning",
                wait_until="domcontentloaded", timeout=TIMEOUT
            )
            await asyncio.sleep(3)
            doc_count = await page.evaluate(
                "() => document.querySelectorAll('a[href*=\"/document/\"').length"
            )
            print(f"[IEEE] Search results: {doc_count} papers")
        else:
            print("\n[IEEE] [WARN] No institutional access — PDF won't be available")

        input("\nPress Enter...")
    finally:
        await auth.stop()

if __name__ == "__main__":
    asyncio.run(main())
