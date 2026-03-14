import logging
import os
from typing import TYPE_CHECKING

from agent_engine.tools_base import BaseTool, register_tool

try:
    from browser_use import Agent as BrowserUseAgent
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

if TYPE_CHECKING:
    from agent_engine.agent import Agent

logger = logging.getLogger(__name__)


def _build_browser_config(args: dict) -> dict:
    """Build browser launch/context config from tool args."""
    config = {}

    proxy_url = args.get("proxy_url", "") or os.getenv("BROWSER_PROXY_URL", "")
    if proxy_url:
        config["proxy"] = {"server": proxy_url}

    user_agent = args.get("user_agent", "") or os.getenv("BROWSER_USER_AGENT", "")
    if user_agent:
        config["user_agent"] = user_agent

    custom_headers = args.get("custom_headers")
    if custom_headers and isinstance(custom_headers, dict):
        config["extra_http_headers"] = custom_headers

    return config


@register_tool
class BrowserAgentTool(BaseTool):
    """Run browser automation tasks using browser-use."""

    name = "browser_agent"
    description = (
        "Automate the browser to perform a task. "
        "Args: task (the instruction for the browser), "
        "proxy_url (optional, e.g. 'http://proxy:8080'), "
        "user_agent (optional, custom User-Agent string), "
        "custom_headers (optional, dict of extra HTTP headers). "
        "Returns the result of the browser action."
    )

    async def execute(self) -> str:
        if not BROWSER_USE_AVAILABLE:
            return "Error: browser-use package is not installed. Run: pip install browser-use"

        task = self.args.get("task", "")
        if not task:
            return "Error: No task provided."

        try:
            from langchain_openai import ChatOpenAI

            llm_model = os.getenv("BROWSER_MODEL", "gpt-4o-mini")
            llm = ChatOpenAI(model=llm_model)

            browser_config = _build_browser_config(self.args)

            # TODO: browser-use may not support all config options natively.
            # Check browser-use docs for proxy/header support in its Agent API.
            agent_kwargs = {"task": task, "llm": llm}

            browser_agent = BrowserUseAgent(**agent_kwargs)
            result = await browser_agent.run()
            return str(result)
        except ImportError as e:
            return f"Missing dependency: {str(e)}. Install with pip."
        except Exception as e:
            logger.error(f"Browser agent error: {e}", exc_info=True)
            return f"Browser automation failed: {str(e)}"


@register_tool
class BrowserScreenshotTool(BaseTool):
    """Take a screenshot of a webpage."""

    name = "browser_screenshot"
    description = (
        "Navigate to a URL and take a screenshot. "
        "Args: url (the page to screenshot), "
        "output_path (optional, default '/workspace/screenshot.png'), "
        "full_page (optional, bool, default false), "
        "proxy_url (optional), user_agent (optional)."
    )

    async def execute(self) -> str:
        if not PLAYWRIGHT_AVAILABLE:
            return "Error: playwright is not installed. Run: pip install playwright && playwright install"

        url = self.args.get("url", "")
        if not url:
            return "Error: No URL provided."

        output_path = self.args.get("output_path", "/workspace/screenshot.png")
        full_page = self.args.get("full_page", False)
        config = _build_browser_config(self.args)

        try:
            async with async_playwright() as p:
                launch_args = {}
                if "proxy" in config:
                    launch_args["proxy"] = config["proxy"]

                browser = await p.chromium.launch(**launch_args)

                context_args = {}
                if "user_agent" in config:
                    context_args["user_agent"] = config["user_agent"]
                if "extra_http_headers" in config:
                    context_args["extra_http_headers"] = config["extra_http_headers"]

                context = await browser.new_context(**context_args)
                page = await context.new_page()

                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.screenshot(path=output_path, full_page=bool(full_page))
                await browser.close()

            return f"Screenshot saved to {output_path}"
        except Exception as e:
            logger.error(f"Screenshot error: {e}", exc_info=True)
            return f"Screenshot failed: {str(e)}"


@register_tool
class BrowserDownloadTool(BaseTool):
    """Download a file from a URL via the browser (handles JS-triggered downloads)."""

    name = "browser_download"
    description = (
        "Download a file from a URL using a real browser (useful for JS-gated downloads). "
        "Args: url (the page/download URL), "
        "output_dir (optional, default '/workspace'), "
        "proxy_url (optional), user_agent (optional)."
    )

    async def execute(self) -> str:
        if not PLAYWRIGHT_AVAILABLE:
            return "Error: playwright is not installed. Run: pip install playwright && playwright install"

        url = self.args.get("url", "")
        if not url:
            return "Error: No URL provided."

        output_dir = self.args.get("output_dir", "/workspace")
        config = _build_browser_config(self.args)

        try:
            async with async_playwright() as p:
                launch_args = {"downloads_path": output_dir}
                if "proxy" in config:
                    launch_args["proxy"] = config["proxy"]

                browser = await p.chromium.launch(**launch_args)

                context_args = {"accept_downloads": True}
                if "user_agent" in config:
                    context_args["user_agent"] = config["user_agent"]

                context = await browser.new_context(**context_args)
                page = await context.new_page()

                async with page.expect_download(timeout=60000) as download_info:
                    await page.goto(url)

                download = await download_info.value
                filename = download.suggested_filename
                save_path = os.path.join(output_dir, filename)
                await download.save_as(save_path)
                await browser.close()

            return f"Downloaded: {save_path}"
        except Exception as e:
            logger.error(f"Browser download error: {e}", exc_info=True)
            return f"Browser download failed: {str(e)}"
