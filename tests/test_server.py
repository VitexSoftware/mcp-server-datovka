"""Structural tests that don't require a real ISDS session."""

from __future__ import annotations

import asyncio
import os

import pytest

from mcp_server_datovka.server import mcp, ping, send_message, send_text_message


def test_tools_are_registered() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "list_received_messages",
        "list_sent_messages",
        "get_message",
        "mark_message_read",
        "send_message",
        "send_text_message",
        "find_data_box",
        "ping",
    }


def test_tool_call_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATOVKA_USERNAME", raising=False)
    monkeypatch.delenv("DATOVKA_PASSWORD", raising=False)
    from mcp_server_datovka import server

    server._get_client.cache_clear()
    with pytest.raises(RuntimeError, match="DATOVKA_USERNAME"):
        ping()


def test_send_message_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATOVKA_USERNAME", raising=False)
    monkeypatch.delenv("DATOVKA_PASSWORD", raising=False)
    from mcp_server_datovka import server

    server._get_client.cache_clear()
    with pytest.raises(RuntimeError, match="DATOVKA_USERNAME"):
        send_message(
            "5drr7us",
            "Test",
            [{"filename": "a.pdf", "mime_type": "application/pdf", "content_base64": "eA==", "is_main": True}],
        )


def test_send_text_message_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATOVKA_USERNAME", raising=False)
    monkeypatch.delenv("DATOVKA_PASSWORD", raising=False)
    from mcp_server_datovka import server

    server._get_client.cache_clear()
    with pytest.raises(RuntimeError, match="DATOVKA_USERNAME"):
        send_text_message("5drr7us", "Test", "Ahoj, toto je zkušební zpráva s háčky a čárkami.")
