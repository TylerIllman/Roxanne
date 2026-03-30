from __future__ import annotations

import re
from typing import List, Tuple

from pydantic import BaseModel


class PageChunk(BaseModel):
    """A text chunk that knows which page(s) it came from."""

    text: str
    page_start: int  # 1-based
    page_end: int  # 1-based
    chunk_index: int


# ── Math-aware tokenisation ──────────────────────────────────────

# Patterns that detect math blocks we must keep as single tokens.
# Ordered so greedy patterns come first.
_MATH_BLOCK_PATTERNS = [
    # LaTeX display math: $$...$$  (possibly multi-line)
    re.compile(r"\$\$.*?\$\$", re.DOTALL),
    # LaTeX environments: \begin{equation}...\end{equation} etc.
    re.compile(r"\\begin\{[a-zA-Z*]+\}.*?\\end\{[a-zA-Z*]+\}", re.DOTALL),
    # LaTeX inline math: $...$  (single line, at least 1 char inside)
    re.compile(r"\$[^\$\n]+?\$"),
    # Unicode math expressions: sequences with math symbols, super/subscripts,
    # Greek letters, integrals, summations, etc.  We match "word-like" runs that
    # contain at least one math-ish character.
    re.compile(
        r"[^\s]*["
        r"\u0370-\u03FF"          # Greek letters
        r"\u2200-\u22FF"          # Mathematical operators
        r"\u2070-\u209F"          # Superscripts / subscripts
        r"\u00B2\u00B3\u00B9"     # ²³¹
        r"\u2260-\u226F"          # ≠ ≤ ≥ etc.
        r"\u222B\u222C\u222D"     # ∫ ∬ ∭
        r"\u2211\u220F\u2210"     # ∑ ∏ ∐
        r"\u221A\u221B\u221C"     # √ ∛ ∜
        r"\u2202\u2207"           # ∂ ∇
        r"\u221E"                 # ∞
        r"][^\s]*"
    ),
]

# Combined pattern: match any math block OR a whitespace-delimited word.
_TOKEN_RE = re.compile(
    r"("
    + "|".join(p.pattern for p in _MATH_BLOCK_PATTERNS)
    + r"|\S+"  # fallback: plain word
    + r")",
    re.DOTALL,
)


def _tokenize(text: str) -> List[str]:
    """Split text into tokens, keeping math expressions as single tokens.

    Regular words are split on whitespace.  Math blocks ($...$, $$...$$,
    \\begin{...}...\\end{...}, and Unicode math runs) are kept intact so
    they are never broken across chunk boundaries.
    """
    return _TOKEN_RE.findall(text)


# ── Normalisation ────────────────────────────────────────────────

def normalize_text(value: str) -> str:
    """Normalize extracted PDF text while preserving equation structure.

    - Collapses excessive blank lines (3+ -> 2) but keeps double-newlines
    - Collapses runs of spaces/tabs ONLY when > 4 (preserves mild indentation
      and alignment used in equations/tables)
    - Preserves Unicode math symbols, superscripts, subscripts, Greek letters
    - Preserves LaTeX math delimiters ($, $$, \\begin, \\end)
    """
    value = value.replace("\r\n", "\n")
    value = re.sub(r"\n{3,}", "\n\n", value)
    # Only collapse very long whitespace runs (>4 spaces) — shorter runs may
    # be intentional alignment in equations or tables
    value = re.sub(r"[ \t]{5,}", "    ", value)
    return value.strip()


# ── Chunking ─────────────────────────────────────────────────────

def chunk_text(text: str, max_words: int = 650, overlap_words: int = 90) -> List[str]:
    """Math-aware word-window chunking (no page awareness).

    Math blocks ($...$, $$...$$, \\begin{...}...\\end{...}) are treated as
    single tokens so they are never split across chunks.
    """
    clean = normalize_text(text)
    if not clean:
        return []

    tokens = _tokenize(clean)
    if len(tokens) <= max_words:
        return [" ".join(tokens)]

    chunks: List[str] = []
    start = 0
    while start < len(tokens):
        end = min(len(tokens), start + max_words)
        chunk = " ".join(tokens[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(tokens):
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

    Math blocks are kept as single tokens so equations are never split.
    """
    if not pages:
        return []

    # Build a flat token list where each token remembers its page number (1-based).
    token_pages: List[int] = []
    all_tokens: List[str] = []
    for page_idx, page_text in enumerate(pages):
        clean = normalize_text(page_text)
        if not clean:
            continue
        tokens = _tokenize(clean)
        all_tokens.extend(tokens)
        token_pages.extend([page_idx + 1] * len(tokens))

    if not all_tokens:
        return []

    if len(all_tokens) <= max_words:
        return [
            PageChunk(
                text=" ".join(all_tokens),
                page_start=token_pages[0],
                page_end=token_pages[-1],
                chunk_index=0,
            )
        ]

    chunks: List[PageChunk] = []
    start = 0
    chunk_idx = 0
    while start < len(all_tokens):
        end = min(len(all_tokens), start + max_words)
        text = " ".join(all_tokens[start:end]).strip()
        if text:
            chunks.append(
                PageChunk(
                    text=text,
                    page_start=token_pages[start],
                    page_end=token_pages[end - 1],
                    chunk_index=chunk_idx,
                )
            )
            chunk_idx += 1
        if end >= len(all_tokens):
            break
        start = max(0, end - overlap_words)

    return chunks
