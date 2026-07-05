"""
Base parser contract and ParsedArticle dataclass.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ParsedArticle:
    title: str
    body: str
    summary: str
    source: str
    url: str
    published_at: datetime | None
    author: str | None
    language: str | None
    image_url: str | None
    word_count: int


class BaseParser(ABC):
    @abstractmethod
    def parse(self, raw_article) -> ParsedArticle:
        """
        Parse a RawArticle into a ParsedArticle.
        raw_article is a RawArticle (collectors.base) or collectors/sources RawArticle.
        Must be pure Python — no network, no LLM.
        """
