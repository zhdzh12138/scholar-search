"""
Base class for database adapters.
"""

from playwright.async_api import Page


class BaseAdapter:
    name: str = "base"
    home_url: str = ""

    def __init__(self, page: Page):
        self.page = page

    async def search(self, query: str, **kwargs) -> dict:
        raise NotImplementedError

    async def detail(self, url: str, **kwargs) -> dict:
        raise NotImplementedError

    async def _navigate(self, url: str, timeout: int = 30000):
        await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
