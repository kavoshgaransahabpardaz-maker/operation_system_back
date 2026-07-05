"""
HTML page collector.

Downloads an HTML page with httpx.
Uses CSS selectors from source.config ({"title_sel": "h1", "body_sel": "article"}).
Falls back to trafilatura text extraction, then full page text.
Respects robots.txt — if blocked returns [].
Returns a single RawArticle per page.
On any error: logs and returns [].
"""
from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

import httpx

from app.modules.intel.collectors.base import BaseCollector, RawArticle

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30
_ROBOTS_CACHE: dict[str, bool] = {}  # base_url → allowed


class HtmlCollector(BaseCollector):
    async def collect(self) -> list[RawArticle]:
        url = self.source.get("url", "")
        source_name = self.source.get("name", "")
        config: dict = self.source.get("config") or {}

        # Check robots.txt
        if not await _is_allowed(url):
            logger.info("HtmlCollector: robots.txt disallows %s — skipping", url)
            return []

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                html_content = response.text
        except Exception as exc:
            logger.error("HtmlCollector HTTP error for %s: %s", url, exc)
            return []

        title = _extract_with_selector(html_content, config.get("title_sel")) or _extract_title(html_content)
        body = _extract_with_selector(html_content, config.get("body_sel"))

        if not body:
            # Try trafilatura for better extraction
            try:
                import trafilatura
                body = trafilatura.extract(html_content) or ""
            except ImportError:
                pass
            except Exception as exc:
                logger.warning("HtmlCollector trafilatura error: %s", exc)

        if not body:
            # Final fallback: strip all HTML tags
            body = _strip_all_html(html_content)

        body = body.strip()
        title = (title or "").strip() or source_name

        if not body:
            logger.warning("HtmlCollector: no body extracted from %s", url)
            return []

        return [
            RawArticle(
                url=url,
                title=title,
                content_raw=body,
                published_at=None,
                source_name=source_name,
            )
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _is_allowed(url: str) -> bool:
    """Simple robots.txt check.  Returns True if unknown or allowed."""
    try:
        from urllib.parse import urlparse, urljoin
        from urllib.robotparser import RobotFileParser

        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        if base_url in _ROBOTS_CACHE:
            return _ROBOTS_CACHE[base_url]

        robots_url = urljoin(base_url, "/robots.txt")
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(robots_url)
                robots_txt = resp.text if resp.status_code == 200 else ""
        except Exception:
            robots_txt = ""

        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.parse(robots_txt.splitlines())
        allowed = rp.can_fetch("*", url)

        _ROBOTS_CACHE[base_url] = allowed
        return allowed
    except Exception:
        return True  # assume allowed if check fails


def _extract_with_selector(html: str, selector: str | None) -> str | None:
    """
    Very minimal CSS selector extraction supporting tag name, .class, #id.
    For production, lxml+cssselect would be better, but we avoid new deps.
    """
    if not selector:
        return None

    try:
        # Use a simple approach: find all text between matching tags
        # Support: tagname, tagname.class, #id
        if selector.startswith("#"):
            # ID selector
            id_val = selector[1:]
            pattern = rf'<[^>]+id=["\']?{re.escape(id_val)}["\']?[^>]*>(.*?)</[a-z]+>'
        elif "." in selector:
            parts = selector.split(".", 1)
            tag = parts[0] or r"[a-z]+"
            cls = parts[1]
            pattern = rf'<{tag}[^>]+class=["\'][^"\']*{re.escape(cls)}[^"\']*["\'][^>]*>(.*?)</{tag if tag != r"[a-z]+" else "[a-z]+"}>',
        else:
            # Plain tag
            pattern = rf'<{re.escape(selector)}[^>]*>(.*?)</{re.escape(selector)}>'

        if isinstance(pattern, tuple):
            pattern = pattern[0]

        matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
        if matches:
            combined = " ".join(matches)
            return _strip_all_html(combined).strip() or None
    except Exception as exc:
        logger.debug("HtmlCollector selector extraction error: %s", exc)

    return None


def _extract_title(html: str) -> str:
    """Extract <title> tag content."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if match:
        return _strip_all_html(match.group(1)).strip()
    return ""


class _HTMLStripper(HTMLParser):
    """stdlib HTMLParser subclass that strips all tags."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_all_html(html: str) -> str:
    stripper = _HTMLStripper()
    try:
        stripper.feed(html)
        return stripper.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
