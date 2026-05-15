"""
Generic CARSI login engine using Playwright.

Handles the CARSI → IdP → CAS → consent page flow that is common
across virtually all Chinese university libraries accessing academic databases.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright, Page, Browser

# File + console logging
LOG_FILE = Path(__file__).parent.parent / "carsi.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("carsi")


# Xidian University IdP entityID
XIDIAN_ENTITY_ID = "https://idp.xidian.edu.cn/idp/shibboleth"


class CarsiAuth:
    """Generic CARSI authenticator with cookie persistence to skip re-login."""

    STATE_FILE = Path(__file__).parent.parent / ".carsi_state.json"

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.browser: Browser | None = None
        self.context = None
        self._playwright = None

    async def start(self):
        self._playwright = await async_playwright().start()
        chrome_path = os.environ.get("CHROME_PATH")
        launch_kwargs = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1280,900",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            ],
        }
        if chrome_path:
            launch_kwargs["executable_path"] = chrome_path
        self.browser = await self._playwright.chromium.launch(**launch_kwargs)
        # Load saved cookies only if they have content (> 50 bytes = real cookies)
        storage = None
        if self.STATE_FILE.exists() and self.STATE_FILE.stat().st_size > 50:
            storage = str(self.STATE_FILE)
            log.info("[CARSI] Loaded saved session cookies")

        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            storage_state=storage,
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        # Hide automation indicators from bot detection
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            window.chrome = { runtime: {} };
        """)
        return self

    async def save_state(self):
        """Persist browser state (cookies, localStorage) for next session."""
        state = await self.context.storage_state()
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        log.info(f"[CARSI] Session saved")

    async def clear_state(self):
        """Force re-login next time."""
        if self.STATE_FILE.exists():
            self.STATE_FILE.unlink()

    async def stop(self):
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def login(
        self,
        database: str,
        username: str,
        password: str,
        entity_id: str = XIDIAN_ENTITY_ID,
        timeout: int = 90000,
    ) -> dict:
        """
        Login to a database via CARSI.

        Args:
            database: One of 'zhizhen', 'cnki', 'ieee', 'elsevier', etc.
            username: Xidian student/staff ID
            password: Xidian unified auth password
            entity_id: IdP entityID (default: Xidian)
            timeout: Max wait time in ms

        Returns:
            dict with success/error and the authenticated page
        """
        from urllib.parse import quote
        from .registry import get_db as _get_db, list_dbs as _list_dbs
        db_config = _get_db(database)
        if not db_config:
            return {"success": False, "error": f"Unknown database: {database}. Available: {_list_dbs()}"}

        sp_url = db_config["sp_url"].format(entity_id_raw=entity_id, entity_id=quote(entity_id, safe=''))
        page = await self.context.new_page()

        try:
            # ── Navigate to CARSI SP → follows redirects to IdP ──
            log.info(f"[CARSI] Opening {database} CARSI...")
            await page.goto(sp_url, wait_until="domcontentloaded", timeout=60000)

            # Wait for JS redirect to complete (wayf/Shibboleth → IdP)
            await asyncio.sleep(6 if self.headless else 3)
            log.info(f"[CARSI] After redirect: {page.url[:120]}")

            # If still on wayf.jsp (JS redirect didn't fire), wait for it
            if "wayf.jsp" in page.url:
                log.info("[CARSI] Still on wayf.jsp — waiting for redirect to IdP...")
                try:
                    await page.wait_for_url("**/idp.xidian.edu.cn/**", timeout=15000)
                except Exception:
                    log.info(f"[CARSI] wayf.jsp did not redirect, current URL: {page.url[:120]}")

            # Check if already logged in (cookies bypassed IdP)
            if await self._is_on_target(page, database):
                log.info("[CARSI] Cookie auth bypassed IdP — already on target")
                await self._accept_cookies(page, database)
                return {"success": True, "page": page, "message": "Already logged in"}

            # Accept cookie banners
            await self._accept_cookies(page, database)

            # ── Handle login form (IdP or CAS) ──
            await self._handle_cas_login(page, username, password)

            # ── Handle Shibboleth consent pages ──
            await self._handle_consent_pages(page, timeout=30000)

            # ── Wait for arrival at target database ──
            await self._wait_for_target(page, database, timeout=30000)
            log.info(f"[CARSI] ✅ Successfully logged into {database}")
            await self._accept_cookies(page, database)

            # ── Block heavy third-party scripts on database pages ──
            _BLOCKED = (
                "google-analytics", "googletagmanager", "hotjar", "newrelic",
                "doubleclick.net", "facebook.net", "twitter.com", "linkedin.com",
                "bat.bing.com", "qualtrics.com", "onetrust.com", "cookielaw.org",
                "osano.com", "hum.works", "cadmore.media",
                "scholar.google.com", "adobedtm.com",
                "zi-scripts.com", "usabilla.com", "datas3ntinel.com",
            )
            _BLOCKED_TYPES = {"image", "media", "font"}
            async def _block_heavy(route):
                req = route.request
                if req.resource_type in _BLOCKED_TYPES:
                    await route.abort()
                elif any(p in req.url.lower() for p in _BLOCKED):
                    await route.abort()
                else:
                    await route.continue_()
            await page.route("**/*", _block_heavy)

            await self.save_state()
            return {"success": True, "page": page, "message": f"Logged into {database}"}

        except Exception as e:
            log.info(f"[CARSI] Login error: {e}")
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            return {"success": False, "error": str(e)}

    async def _handle_cas_login(self, page: Page, username: str, password: str):
        """Fill and submit the Shibboleth IdP or CAS login form."""
        is_idp = ("idp.xidian.edu.cn" in page.url.split("?")[0]
                  and "seamlessaccess" not in page.url.split("?")[0])
        is_cas = "authserver/login" in page.url
        log.info(f"[CARSI] Login page type: {'IdP' if is_idp else 'CAS' if is_cas else 'unknown'}")
        log.info(f"[CARSI] Page URL: {page.url[:200]}")
        try:
            snippet = await page.inner_text("body")
            log.info(f"[CARSI] Page text (headless): {snippet[:300]}")
        except Exception:
            pass

        await asyncio.sleep(3 if self.headless else 1.5)

        # ── Find and fill username ──
        user_sel = 'input[name="j_username"]' if is_idp else '#username'
        user_el = page.locator(user_sel).first
        try:
            await user_el.wait_for(state="visible", timeout=10000)
        except Exception:
            user_el = page.locator('#username').first
            await user_el.wait_for(state="visible", timeout=8000)
        await user_el.click()
        await user_el.fill(username)
        log.info("[CARSI] Username filled")

        # ── Find and fill password ──
        pass_sel = 'input[name="j_password"]' if is_idp else '#password'
        pass_el = page.locator(pass_sel).first
        try:
            await pass_el.wait_for(state="visible", timeout=10000)
        except Exception:
            pass_el = page.locator('#password').first
            await pass_el.wait_for(state="visible", timeout=8000)
        await pass_el.click()
        await pass_el.fill(password)
        log.info("[CARSI] Password filled")

        # ── Uncheck "don't remember" / "clear auth" boxes (IdP page) ──
        if is_idp:
            for cb in await page.locator('input[type="checkbox"]').all():
                try:
                    if await cb.is_checked():
                        await cb.uncheck()
                        log.info("[CARSI] Unchecked a box")
                except Exception:
                    pass

        # ── Click submit ──
        btn_selectors = (
            ['button[name="_eventId_proceed"]', 'button:has-text("登陆")', 'button:has-text("登录")',
             'input[type="submit"]', 'button[type="submit"]', 'form button']
            if is_idp else
            ['#login_submit', '.login-btn', 'button:has-text("登录")', 'button[type="submit"]']
        )
        clicked = False
        for sel in btn_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    log.info(f"[CARSI] Clicked: {sel}")
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            log.info("[CARSI] ⚠️ No button found by selector, trying generic JS click...")
            await page.evaluate("""
                const selectors = [
                    'button[name="_eventId_proceed"]',
                    '#login_submit', '.login-btn',
                    'button[type="submit"]', 'input[type="submit"]',
                    'button:has-text("登陆")', 'button:has-text("登录")',
                    'form button', 'form input[type="submit"]'
                ];
                for (const s of selectors) {
                    const el = document.querySelector(s);
                    if (el) { el.click(); break; }
                }
            """)

        log.info("[CARSI] Waiting for redirect...")

    async def _handle_consent_pages(self, page: Page, timeout: int = 60000):
        """Handle Shibboleth IdP consent pages (terms, attribute release, etc.)."""
        deadline = asyncio.get_event_loop().time() + timeout / 1000

        for page_num in range(5):
            await asyncio.sleep(1)

            if "idp.xidian.edu.cn" not in page.url.split("?")[0]:
                log.info("[CARSI] Left IdP — done")
                return

            if asyncio.get_event_loop().time() > deadline:
                log.info("[CARSI] Consent timeout")
                return

            body_text = await page.inner_text("body")
            log.info(f"[CARSI] Consent #{page_num+1}: {body_text[:300]}")

            await page.evaluate("""
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    const label = (cb.labels?.[0]?.textContent || cb.parentElement?.textContent || '').trim();
                    console.log('checkbox:', label, 'checked:', cb.checked, 'visible:', cb.offsetParent !== null);
                    if (!cb.checked) {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change', {bubbles: true}));
                        cb.dispatchEvent(new Event('click', {bubbles: true}));
                    }
                });
            """)
            cbs = await page.locator('input[type="checkbox"]').all()
            for cb in cbs:
                try:
                    label = await cb.evaluate("el => (el.labels?.[0]?.textContent || '').trim()")
                    checked = await cb.is_checked()
                    log.info(f"[CARSI]   checkbox: checked={checked} label='{label[:60]}'")
                except Exception:
                    pass

            radios = await page.locator('input[type="radio"]').all()
            if radios:
                await page.evaluate("""
                    document.querySelectorAll('input[type="radio"]').forEach(r => {
                        const label = (r.labels?.[0]?.textContent || r.parentElement?.textContent || '').trim();
                        if (!r.checked && (label.includes('accept') || label.includes('Always') ||
                            label.includes('不再') || label.includes('继续') || label.includes('确认'))) {
                            r.checked = true;
                            r.dispatchEvent(new Event('change', {bubbles: true}));
                        }
                    });
                    const allRadios = document.querySelectorAll('input[type="radio"]');
                    if (allRadios.length > 0 && ![...allRadios].some(r => r.checked)) {
                        allRadios[allRadios.length - 1].checked = true;
                        allRadios[allRadios.length - 1].dispatchEvent(new Event('change', {bubbles: true}));
                    }
                """)
                log.info("[CARSI] Handled radio buttons")

            clicked = False
            for btn_text in ["提交", "同意", "继续", "确认", "接受", "允许", "下一步",
                             "Accept", "Submit", "Yes", "Continue", "Proceed"]:
                try:
                    btn = page.locator(f'button:has-text("{btn_text}")').first
                    if await btn.count() > 0:
                        await btn.click(timeout=3000)
                        log.info(f"[CARSI] Clicked '{btn_text}'")
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                try:
                    btn = page.locator('input[type="submit"]').first
                    if await btn.count() > 0:
                        await btn.click(timeout=2000)
                        log.info("[CARSI] Clicked input[type=submit]")
                        clicked = True
                except Exception:
                    pass

            if not clicked:
                await page.evaluate("""
                    const texts = ['提交', '同意', '继续', '确认', '接受', '允许', 'Accept', 'Submit'];
                    for (const t of texts) {
                        const btn = [...document.querySelectorAll('button, input[type="submit"]')]
                            .find(b => b.textContent.includes(t) || b.value?.includes(t));
                        if (btn) { btn.click(); break; }
                    }
                """)
                log.info("[CARSI] JS fallback submit")
                clicked = True

            if not clicked:
                log.info("[CARSI] No consent button found")
                return

            await asyncio.sleep(2)

    async def _wait_for_target(self, page: Page, database: str, timeout: int = 30000):
        """Wait for the browser to arrive at the target database."""
        from .registry import get_db as _get_db
        db_config = _get_db(database)
        pattern = db_config.get("target_url_pattern", "**/*") if db_config else "**/*"
        await page.wait_for_url(pattern, timeout=timeout)

    async def _accept_cookies(self, page: Page, database: str):
        """Accept cookie banners that block page content."""
        from .registry import get_db as _get_db
        db_config = _get_db(database)
        selectors = db_config.get("cookie_accept", []) if db_config else []
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    log.info(f"[CARSI] Accepted cookies ({database})")
                    await asyncio.sleep(0.5)
                    break
            except Exception:
                pass

    async def _is_on_target(self, page: Page, database: str) -> bool:
        """Check if the page is already on the target database (not login)."""
        url = page.url
        from .registry import get_db as _get_db
        db_config = _get_db(database)
        if not db_config:
            return False
        home = db_config["home_url"]
        domain = home.split("/")[2]
        return domain in url and "login" not in url.lower() and "wayf" not in url.lower()

    async def search(self, pg: Page, database: str, query: str, **kwargs) -> dict:
        """Search papers — delegates to DB adapter via registry."""
        from .registry import get_adapter as _get_adapter
        try:
            adapter = await _get_adapter(database, pg)
            return await adapter.search(query, **kwargs)
        except (ValueError, NotImplementedError) as e:
            return {"success": False, "error": str(e)}

    async def detail(self, pg: Page, database: str, url: str, **kwargs) -> dict:
        """Extract paper details — delegates to DB adapter via registry."""
        from .registry import get_adapter as _get_adapter
        try:
            adapter = await _get_adapter(database, pg)
            return await adapter.detail(url, **kwargs)
        except (ValueError, NotImplementedError) as e:
            return {"success": False, "error": str(e)}


# ── Convenience function ──
async def login_to_database(
    database: str,
    username: str,
    password: str,
    entity_id: str = XIDIAN_ENTITY_ID,
    headless: bool = False,
) -> dict:
    """One-shot login to an academic database via CARSI."""
    auth = CarsiAuth(headless=headless)
    await auth.start()
    result = await auth.login(database, username, password, entity_id)
    return {**result, "auth": auth}
