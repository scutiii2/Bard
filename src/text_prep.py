"""Turn chat Markdown into plain speakable text."""

from __future__ import annotations

import re

from src.errors import TextRejected

_FENCE = re.compile(r"```.*?```", re.S)
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_INLINE_CODE = re.compile(r"`([^`]*)`")
_BLOCK = re.compile(r"(?m)^\s{0,3}(?:#{1,6}|>|[-*+]|\d+\.)\s+")
_EMPHASIS = re.compile(r"\*{1,3}|~~|(?<!\w)_+|_+(?!\w)")
_SPACE = re.compile(r"\s+")


def prepare(text: str, max_chars: int) -> str:
    cleaned = _FENCE.sub(" ", text)
    cleaned = _LINK.sub(r"\1", cleaned)
    cleaned = _INLINE_CODE.sub(r"\1", cleaned)
    cleaned = _BLOCK.sub("", cleaned)
    cleaned = _EMPHASIS.sub("", cleaned)
    cleaned = _SPACE.sub(" ", cleaned).strip()
    if not cleaned:
        raise TextRejected("There is no speakable text.")
    if len(cleaned) > max_chars:
        raise TextRejected(f"The text is {len(cleaned)} characters; the limit is {max_chars}.")
    return cleaned
