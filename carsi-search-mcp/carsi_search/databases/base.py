"""
Base class for database adapters.
"""

import asyncio
from playwright.async_api import Page


_BLOCKED_TYPES = {"image", "media", "font"}
_BLOCKED_PATTERNS = (
    "google-analytics", "googletagmanager", "hotjar", "newrelic",
    "doubleclick.net", "facebook.net", "twitter.com", "linkedin.com",
    "bat.bing.com", "ads.", "pixel.", "tracking.",
    "qualtrics.com", "onetrust.com", "cookielaw.org",
    "osano.com", "hum.works", "cadmore.media",
    "scholar.google.com", "adobedtm.com",
    "zi-scripts.com", "usabilla.com", "datas3ntinel.com",
)

def _should_block(request_type: str, request_url: str) -> bool:
    if request_type in _BLOCKED_TYPES:
        return True
    lower = request_url.lower()
    return any(p in lower for p in _BLOCKED_PATTERNS)


class BaseAdapter:
    name: str = "base"
    home_url: str = ""

    def __init__(self, page: Page):
        self.page = page
        self._route_active = False

    async def search(self, query: str, **kwargs) -> dict:
        raise NotImplementedError

    async def detail(self, url: str, **kwargs) -> dict:
        raise NotImplementedError

    async def _enable_fast_route(self):
        await self.page.unroute("**/*")
        async def _handler(route):
            req = route.request
            if _should_block(req.resource_type, req.url):
                await route.abort()
            else:
                await route.continue_()
        await self.page.route("**/*", _handler)
        self._route_active = True

    async def _disable_fast_route(self):
        await self.page.unroute("**/*")
        self._route_active = False

    async def _navigate(self, url: str, timeout: int = 30000):
        await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
