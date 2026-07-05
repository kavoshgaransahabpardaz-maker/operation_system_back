"""
Base collector contract and RawArticle dataclass.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawArticle:
    url: str
    title: str
    content_raw: str
    published_at: datetime | None = None
    author: str | None = None
    language: str | None = None
    image_url: str | None = None
    source_name: str = ""
    extra: dict = field(default_factory=dict)


class BaseCollector(ABC):
    def __init__(self, source: dict) -> None:
        self.source = source  # IntelSource serialised to dict

    @abstractmethod
    async def collect(self) -> list[RawArticle]:
        """Download raw articles.  Must be idempotent.  Never raises — returns [] on error."""
