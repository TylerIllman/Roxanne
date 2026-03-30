"""Tests for text normalization and chunking logic."""
from __future__ import annotations

import pytest

from roxanne_backend.ingestion.chunker import (
    PageChunk,
    _tokenize,
    chunk_pages,
    chunk_text,
    normalize_text,
)


# ── normalize_text ─────────────────────────────────────────────────


class TestNormalizeText:
    def test_strip_whitespace(self):
        assert normalize_text("  hello  ") == "hello"

    def test_collapse_newlines(self):
        assert normalize_text("a\n\n\n\nb") == "a\n\nb"

    def test_preserve_double_newline(self):
        assert normalize_text("a\n\nb") == "a\n\nb"

    def test_preserve_moderate_spaces(self):
        # Spaces ≤4 should be preserved (equation alignment)
        result = normalize_text("x    y")
        assert "    " in result  # 4 spaces preserved

    def test_collapse_long_spaces(self):
        # 5+ spaces collapsed to 4
        result = normalize_text("x      y")  # 6 spaces
        assert "      " not in result

    def test_crlf_to_lf(self):
        assert normalize_text("a\r\nb") == "a\nb"

    def test_empty(self):
        assert normalize_text("") == ""

    def test_unicode_preserved(self):
        # Greek letters, math symbols should survive normalization
        text = "α + β = γ, ∑∫∂"
        assert normalize_text(text) == text

    def test_superscripts_preserved(self):
        text = "x² + y³ = z"
        assert normalize_text(text) == text


# ── chunk_text ─────────────────────────────────────────────────────


class TestChunkText:
    def test_short_text_single_chunk(self):
        chunks = chunk_text("hello world", max_words=10)
        assert len(chunks) == 1
        assert chunks[0] == "hello world"

    def test_empty_text(self):
        assert chunk_text("") == []

    def test_whitespace_only(self):
        assert chunk_text("   \n\n  ") == []

    def test_splits_at_word_boundary(self):
        words = " ".join(f"word{i}" for i in range(100))
        chunks = chunk_text(words, max_words=30, overlap_words=5)
        assert len(chunks) >= 3
        # Each chunk should have ≤30 words
        for c in chunks:
            assert len(c.split()) <= 30

    def test_overlap(self):
        words = " ".join(f"w{i}" for i in range(50))
        chunks = chunk_text(words, max_words=20, overlap_words=5)
        assert len(chunks) >= 2
        # Last 5 words of chunk 0 should appear at start of chunk 1
        c0_words = chunks[0].split()
        c1_words = chunks[1].split()
        overlap = c0_words[-5:]
        assert c1_words[:5] == overlap

    def test_exact_boundary(self):
        words = " ".join(["word"] * 10)
        chunks = chunk_text(words, max_words=10)
        assert len(chunks) == 1


# ── chunk_pages ────────────────────────────────────────────────────


class TestChunkPages:
    def test_empty_pages(self):
        assert chunk_pages([]) == []

    def test_single_short_page(self):
        pages = ["This is a short page."]
        chunks = chunk_pages(pages)
        assert len(chunks) == 1
        assert chunks[0].page_start == 1
        assert chunks[0].page_end == 1
        assert chunks[0].chunk_index == 0

    def test_page_tracking(self):
        pages = [
            " ".join(["page1"] * 400),
            " ".join(["page2"] * 400),
        ]
        chunks = chunk_pages(pages, max_words=650, overlap_words=90)
        # With 800 total words and 650 max, should get 2 chunks
        assert len(chunks) >= 2
        # First chunk should start on page 1
        assert chunks[0].page_start == 1
        # Last chunk should end on page 2
        assert chunks[-1].page_end == 2

    def test_chunk_index_sequential(self):
        pages = [" ".join(["w"] * 500) for _ in range(3)]
        chunks = chunk_pages(pages, max_words=300)
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_all_empty_pages(self):
        assert chunk_pages(["", "  ", "\n\n"]) == []

    def test_mixed_empty_and_content(self):
        pages = ["", "Hello world", ""]
        chunks = chunk_pages(pages)
        assert len(chunks) == 1
        assert chunks[0].page_start == 2
        assert chunks[0].page_end == 2

    def test_page_chunk_is_pydantic(self):
        chunks = chunk_pages(["Some text here"])
        assert isinstance(chunks[0], PageChunk)
        d = chunks[0].model_dump()
        assert "text" in d
        assert "page_start" in d


# ── _tokenize (math-aware) ───────────────────────────────────────


class TestTokenize:
    def test_plain_words(self):
        tokens = _tokenize("hello world foo")
        assert tokens == ["hello", "world", "foo"]

    def test_inline_latex(self):
        tokens = _tokenize("The formula $x^2 + y^2 = z^2$ is famous")
        assert "$x^2 + y^2 = z^2$" in tokens
        assert "The" in tokens
        assert "famous" in tokens

    def test_display_latex(self):
        tokens = _tokenize("See: $$\\sum_{i=1}^n x_i$$ here")
        assert "$$\\sum_{i=1}^n x_i$$" in tokens

    def test_multiline_display_latex(self):
        text = "Before $$\nx^2 +\ny^2\n$$ after"
        tokens = _tokenize(text)
        # The display math block should be a single token
        math_tokens = [t for t in tokens if "$$" in t]
        assert len(math_tokens) == 1
        assert "x^2" in math_tokens[0]
        assert "y^2" in math_tokens[0]

    def test_latex_environment(self):
        text = r"Result: \begin{equation}E = mc^2\end{equation} QED"
        tokens = _tokenize(text)
        env_tokens = [t for t in tokens if "\\begin" in t]
        assert len(env_tokens) == 1
        assert "E = mc^2" in env_tokens[0]

    def test_unicode_math_symbols(self):
        tokens = _tokenize("where α + β = γ holds")
        # Greek letters should be kept as tokens (possibly merged with neighbors)
        full = " ".join(tokens)
        assert "α" in full
        assert "β" in full
        assert "γ" in full

    def test_unicode_operators(self):
        tokens = _tokenize("∑∫∂∇ are operators")
        full = " ".join(tokens)
        assert "∑" in full or "∫" in full

    def test_superscript_unicode(self):
        tokens = _tokenize("x² + y³ = z")
        full = " ".join(tokens)
        assert "x²" in full
        assert "y³" in full

    def test_empty_string(self):
        assert _tokenize("") == []


# ── Math-aware chunking ──────────────────────────────────────────


class TestMathChunking:
    def test_inline_latex_not_split(self):
        """Inline $...$ math should never be broken across chunks."""
        words = " ".join(f"w{i}" for i in range(40))
        text = f"{words} $x^2 + y^2 = z^2$ {words}"
        chunks = chunk_text(text, max_words=45, overlap_words=5)
        for chunk in chunks:
            # If the chunk contains a $, the full expression must be there
            if "$x^2" in chunk:
                assert "$x^2 + y^2 = z^2$" in chunk

    def test_display_latex_not_split(self):
        """Display $$...$$ math should never be broken across chunks."""
        words = " ".join(f"w{i}" for i in range(40))
        text = f"{words} $$\\int_0^1 f(x)\\,dx$$ {words}"
        chunks = chunk_text(text, max_words=45, overlap_words=5)
        for chunk in chunks:
            if "$$" in chunk:
                assert "$$\\int_0^1 f(x)\\,dx$$" in chunk

    def test_latex_env_not_split(self):
        """\\begin{equation}...\\end{equation} should be a single token."""
        words = " ".join(f"w{i}" for i in range(40))
        text = words + r" \begin{equation}a+b=c\end{equation} " + words
        chunks = chunk_text(text, max_words=45, overlap_words=5)
        for chunk in chunks:
            if "\\begin{equation}" in chunk:
                assert "\\end{equation}" in chunk

    def test_chunk_pages_preserves_math(self):
        """Math in page-aware chunking should also be preserved."""
        page1 = " ".join(f"w{i}" for i in range(400))
        page2 = "$E = mc^2$ " + " ".join(f"v{i}" for i in range(400))
        chunks = chunk_pages([page1, page2], max_words=450, overlap_words=50)
        for chunk in chunks:
            if "$E" in chunk.text:
                assert "$E = mc^2$" in chunk.text

    def test_mixed_math_and_prose(self):
        """Document mixing prose and equations should chunk cleanly."""
        text = (
            "Introduction to calculus. "
            "The derivative is $\\frac{df}{dx}$ and the integral is "
            "$$\\int_a^b f(x)\\,dx = F(b) - F(a)$$ "
            "This is the fundamental theorem."
        )
        chunks = chunk_text(text, max_words=100)
        assert len(chunks) == 1
        assert "$\\frac{df}{dx}$" in chunks[0]
        assert "$$\\int_a^b f(x)\\,dx = F(b) - F(a)$$" in chunks[0]
