"""
PDF collector.

Downloads a PDF from a URL and extracts text using pdfplumber.
Returns a single RawArticle with full text as content_raw.
On any error: logs and returns [].
"""
from __future__ import annotations

import io
import logging

import httpx

from app.modules.intel.collectors.base import BaseCollector, RawArticle

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 60  # PDFs can be large


class PdfCollector(BaseCollector):
    async def collect(self) -> list[RawArticle]:
        url = self.source.get("url", "")
        source_name = self.source.get("name", "")

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                pdf_bytes = response.content
        except Exception as exc:
            logger.error("PdfCollector HTTP error for %s: %s", url, exc)
            return []

        try:
            import pdfplumber

            text_parts: list[str] = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                title = ""
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text() or ""
                    if i == 0 and page_text:
                        # Use first non-empty line as title
                        for line in page_text.splitlines():
                            line = line.strip()
                            if line:
                                title = line[:500]
                                break
                    text_parts.append(page_text)

            full_text = "\n".join(text_parts).strip()
            if not full_text:
                logger.warning("PdfCollector: no text extracted from %s", url)
                return []

            return [
                RawArticle(
                    url=url,
                    title=title or source_name,
                    content_raw=full_text,
                    published_at=None,
                    source_name=source_name,
                )
            ]

        except ImportError:
            logger.error("PdfCollector: pdfplumber not installed")
            return []
        except Exception as exc:
            logger.error("PdfCollector: error extracting PDF from %s: %s", url, exc)
            return []
