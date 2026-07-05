"""
Parser factory — returns correct parser for a given source name.

Falls back to GenericParser when no specific parser is registered.
Future: add BBCParser, ReutersParser, HMRCParser etc. here.
"""
from __future__ import annotations

from app.modules.intel.parsers.base import BaseParser


def get_parser(source_name: str) -> BaseParser:
    """
    Return the parser for the given source name.

    Currently all sources use GenericParser.
    To add a source-specific parser:
        if source_name == "BBC News":
            from app.modules.intel.parsers.bbc_parser import BBCParser
            return BBCParser()
    """
    from app.modules.intel.parsers.generic_parser import GenericParser
    return GenericParser()
