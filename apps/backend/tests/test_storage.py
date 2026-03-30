"""Tests for AppPaths and file storage utilities."""
from __future__ import annotations

from pathlib import Path

import pytest

from roxanne_backend.storage import AppPaths


class TestAppPaths:
    def test_root_exists(self):
        paths = AppPaths()
        assert isinstance(paths.root, Path)

    def test_root_is_absolute(self):
        paths = AppPaths()
        assert paths.root.is_absolute()
