from __future__ import annotations

import re
from typing import List

from pydantic import BaseModel


class PageChunk(BaseModel):
    """A text chunk that knows which page(s) it came from."""

    text: str
    page_start: int  # 1-based
    page_end: int  # 1-based
    chunk_index: int


def normalize_text(value: str) -> str:
    """Normalize extracted PDF text while preserving equation structure.

    - Collapses excessive blank lines (3+ → 2) but keeps double-newlines
    - Collapses runs of spaces/tabs ONLY when > 4 (preserves mild indentation
      and alignment used in equations/tables)
    - Preserves Unicode math symbols, superscripts, subscripts, Greek letters
    """
    value = value.replace("\r\n", "\n")
    value = re.sub(r"\n{3,}", "\n\n", value)
    # Only collapse very long whitespace runs (>4 spaces) — shorter runs may
    # be intentional alignment in equations or tables
    value = re.sub(r"[ \t]{5,}", "    ", value)
    return value.strip()


def chunk_text(text: str, max_words: int = 650, overlap_words: int = 90) -> List[str]:
    """Simple word-window chunking (no page awareness)."""
    clean = normalize_text(text)
    if not clean:
        return []

    words = clean.split()
    if len(words) <= max_words:
        return [clean]

    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + max_words)
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(words):
            break
        start = max(0, end - overlap_words)
    return chunks


def chunk_pages(
    pages: List[str],
    max_words: int = 650,
    overlap_words: int = 90,
) -> List[PageChunk]:
    """Chunk a list of per-page texts, tracking which page(s) each chunk spans.

    Each entry in *pages* is the extracted text of one PDF page (0-indexed list,
    but PageChunk.page_start/page_end are 1-based for display).
    """
    if not pages:
        return []

    # Build a flat word list where each word remembers its page number (1-based).
    word_pages: List[int] = []  # page number for each word
    all_words: List[str] = []
    for page_idx, page_text in enumerate(pages):
        clean = normalize_text(page_text)
        if not clean:
            continue
        words = clean.split()
        all_words.extend(words)
        word_pages.extend([page_idx + 1] * len(words))

    if not all_words:
        return []

    if len(all_words) <= max_words:
        return [
            PageChunk(
                text=" ".join(all_words),
                page_start=word_pages[0],
                page_end=word_pages[-1],
                chunk_index=0,
            )
        ]

    chunks: List[PageChunk] = []
    start = 0
    chunk_idx = 0
    while start < len(all_words):
        end = min(len(all_words), start + max_words)
        text = " ".join(all_words[start:end]).strip()
        if text:
            chunks.append(
                PageChunk(
                    text=text,
                    page_start=word_pages[start],
                    page_end=word_pages[end - 1],
                    chunk_index=chunk_idx,
                )
            )
            chunk_idx += 1
        if end >= len(all_words):
            break
        start = max(0, end - overlap_words)

    return chunks
