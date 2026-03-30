"""Tests for conversation persistence."""
from __future__ import annotations

import pytest

from roxanne_backend.conversations import ConversationStore
from roxanne_backend.storage import AppPaths


@pytest.fixture
def conv_store(app_paths: AppPaths) -> ConversationStore:
    return ConversationStore(app_paths.root)


class TestConversationStore:
    def test_create(self, conv_store: ConversationStore):
        result = conv_store.create("Test Chat")
        assert "id" in result
        assert result["title"] == "Test Chat"
        assert result["messages"] == []

    def test_list_empty(self, conv_store: ConversationStore):
        result = conv_store.list_all()
        assert result == []

    def test_list_after_create(self, conv_store: ConversationStore):
        conv_store.create("Chat 1")
        conv_store.create("Chat 2")
        result = conv_store.list_all()
        assert len(result) == 2

    def test_get_conversation(self, conv_store: ConversationStore):
        created = conv_store.create("My Chat")
        fetched = conv_store.get(created["id"])
        assert fetched is not None
        assert fetched["title"] == "My Chat"

    def test_get_nonexistent(self, conv_store: ConversationStore):
        result = conv_store.get("nonexistent-id")
        assert result is None

    def test_append_message(self, conv_store: ConversationStore):
        created = conv_store.create("Test")
        conv_store.append_message(created["id"], "user", "Hello!")
        conv_store.append_message(created["id"], "assistant", "Hi there!")
        fetched = conv_store.get(created["id"])
        assert len(fetched["messages"]) == 2
        assert fetched["messages"][0]["role"] == "user"
        assert fetched["messages"][1]["content"] == "Hi there!"

    def test_update_title(self, conv_store: ConversationStore):
        created = conv_store.create("Old Title")
        conv_store.update_title(created["id"], "New Title")
        fetched = conv_store.get(created["id"])
        assert fetched["title"] == "New Title"

    def test_delete(self, conv_store: ConversationStore):
        created = conv_store.create("To Delete")
        conv_store.delete(created["id"])
        assert conv_store.get(created["id"]) is None
        assert len(conv_store.list_all()) == 0

    def test_delete_nonexistent(self, conv_store: ConversationStore):
        # Should not raise
        conv_store.delete("ghost-id")

    def test_list_order_newest_first(self, conv_store: ConversationStore):
        conv_store.create("First")
        conv_store.create("Second")
        conv_store.create("Third")
        result = conv_store.list_all()
        # Most recent should be first
        assert result[0]["title"] == "Third"
