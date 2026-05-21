"""
CDP connection manager for Chrome browser with cookie persistence.

Auto-launches Chrome with CDP debugging if not already running.
Saves/loads cookies so the user only needs to log in once.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from playwright.async_api import async_playwright, Browser

# CDP endpoint
CDP_URL = os.environ.get("CHROME_CDP_URL", "http://127.0.0.1:9222")
# Separate profile for CDP Chrome (avoids conflicts with user's normal Chrome)
_CDP_PROFILE = Path.home() / ".carsi_chrome_profile"

# Logging
LOG_FILE = Path(__file__).parent.parent / "carsi.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("carsi")


def _find_chrome() -> str | None:
    """Find Chrome executable on the system."""
    # Check CHROME_PATH env var first
    env_path = os.environ.get("CHROME_PATH")
    if env_path and Path(env_path).exists():
        return env_path
    # Common Windows paths
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    # Try PATH
    found = shutil.which("chrome") or shutil.which("google-chrome")
    return found


def _is_cdp_available() -> bool:
    """Quick check if CDP port is already listening."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


class CarsiAuth:
    """CDP connection wrapper with auto-launch and cookie save/restore."""

    STATE_FILE = Path(__file__).parent.parent / ".carsi_state.json"

    def __init__(self):
        self.browser: Browser | None = None
        self.context = None
        self._playwright = None
        self._chrome_process: subprocess.Popen | None = None

    async def start(self):
        """
        连接到 Chrome（通过 CDP）。
        如果 Chrome CDP 不可用，自动启动一个新的 Chrome 实例。
        """
        # Step 1: Check if CDP is already available
        if not _is_cdp_available():
            await self._launch_chrome()

        # Step 2: Connect via CDP
        self._playwright = await async_playwright().start()
        for attempt in range(3):
            try:
                self.browser = await self._playwright.chromium.connect_over_cdp(CDP_URL)
                break
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(2)
                else:
                    await self._playwright.stop()
                    self._playwright = None
                    raise RuntimeError(
                        f"无法连接 Chrome CDP ({CDP_URL})。"
                        f"请手动启动 Chrome: chrome --remote-debugging-port=9222"
                    )

        self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
        log.info(f"[CDP] 已连接 Chrome: {CDP_URL}")

        # Step 3: Restore cookies
        await self._restore_cookies()

        return self

    async def _launch_chrome(self):
        """自动启动带 CDP 调试端口的 Chrome。"""
        chrome_path = _find_chrome()
        if not chrome_path:
            raise RuntimeError(
                "找不到 Chrome 浏览器。请安装 Chrome 或设置 CHROME_PATH 环境变量。"
            )

        log.info(f"[CDP] Chrome CDP 不可用，自动启动 Chrome...")
        _CDP_PROFILE.mkdir(parents=True, exist_ok=True)

        # Parse CDP port from URL
        port = CDP_URL.split(":")[-1].rstrip("/")
        cmd = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={_CDP_PROFILE}",
        ]

        try:
            self._chrome_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info(f"[CDP] Chrome 已启动 (PID={self._chrome_process.pid})")
        except Exception as e:
            raise RuntimeError(f"启动 Chrome 失败: {e}")

    async def save_state(self):
        """保存当前浏览器的 cookie 和 localStorage 到文件。"""
        if not self.context:
            return
        try:
            state = await self.context.storage_state()
            self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
            cookie_count = len(state.get("cookies", []))
            log.info(f"[CDP] 已保存 {cookie_count} 个 cookie")
        except Exception as e:
            log.info(f"[CDP] 保存 cookie 失败: {e}")

    async def _restore_cookies(self):
        """从文件加载已保存的 cookie 并注入到浏览器。"""
        if not self.STATE_FILE.exists() or self.STATE_FILE.stat().st_size <= 50:
            return
        try:
            state = json.loads(self.STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.info(f"[CDP] 读取 cookie 文件失败: {e}")
            return

        cookies = state.get("cookies", [])
        if not cookies:
            return

        injected = 0
        for cookie in cookies:
            try:
                cdp_cookie = {
                    "name": cookie["name"],
                    "value": cookie["value"],
                    "domain": cookie.get("domain", ""),
                    "path": cookie.get("path", "/"),
                }
                if cookie.get("secure"):
                    cdp_cookie["secure"] = True
                if cookie.get("httpOnly"):
                    cdp_cookie["httpOnly"] = True
                if cookie.get("sameSite"):
                    cdp_cookie["sameSite"] = cookie["sameSite"]
                if cookie.get("expires", -1) > 0:
                    cdp_cookie["expires"] = cookie["expires"]
                await self.context.add_cookies([cdp_cookie])
                injected += 1
            except Exception:
                pass

        # Restore localStorage
        for origin_data in state.get("origins", []):
            origin = origin_data.get("origin", "")
            ls_items = origin_data.get("localStorage", [])
            if not origin or not ls_items:
                continue
            for item in ls_items:
                try:
                    key = item["name"].replace("'", "\\'")
                    val = item["value"].replace("\\", "\\\\").replace("'", "\\'")
                    for page in self.context.pages:
                        if origin in page.url:
                            await page.evaluate(f"localStorage.setItem('{key}', '{val}')")
                            break
                except Exception:
                    pass

        log.info(f"[CDP] 已恢复 {injected}/{len(cookies)} 个 cookie")

    async def clear_state(self):
        """清除已保存的 cookie 文件。"""
        if self.STATE_FILE.exists():
            self.STATE_FILE.unlink()
            log.info("[CDP] 已清除保存的 cookie 文件")

    async def stop(self):
        """断开 CDP 连接。如果是自动启动的 Chrome，也一并关闭。"""
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self.browser = None
        self.context = None
        # 如果是我们自动启动的 Chrome，关闭它
        if self._chrome_process and self._chrome_process.poll() is None:
            self._chrome_process.terminate()
            log.info("[CDP] 已关闭自动启动的 Chrome")
            self._chrome_process = None
