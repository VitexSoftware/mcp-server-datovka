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


def test_send_message_file_path_requires_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: "os.PathLike[str]"
) -> None:
    monkeypatch.delenv("DATOVKA_USERNAME", raising=False)
    monkeypatch.delenv("DATOVKA_PASSWORD", raising=False)
    from mcp_server_datovka import server

    server._get_client.cache_clear()
    pdf_path = os.path.join(tmp_path, "doc.pdf")
    with open(pdf_path, "wb") as f:
        f.write(b"%PDF-1.4 fake content")

    with pytest.raises(RuntimeError, match="DATOVKA_USERNAME"):
        send_message(
            "5drr7us",
            "Test",
            [{"file_path": pdf_path, "is_main": True}],
        )


def test_send_message_file_path_infers_filename_and_mime_type(tmp_path: "os.PathLike[str]") -> None:
    from mcp_server_datovka.server import OutgoingDocument

    pdf_path = os.path.join(tmp_path, "evidencni_list.pdf")
    with open(pdf_path, "wb") as f:
        f.write(b"%PDF-1.4 fake content")

    attachments = [{"file_path": pdf_path, "is_main": True}]
    # Mirror send_message's own attachment-building loop without touching the network.
    a = attachments[0]
    from pathlib import Path
    import mimetypes

    path = Path(a["file_path"]).expanduser()
    filename = a.get("filename") or path.name
    mime_type = a.get("mime_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    doc = OutgoingDocument(filename=filename, mime_type=mime_type, data=path.read_bytes(), is_main=True)
    assert doc.filename == "evidencni_list.pdf"
    assert doc.mime_type == "application/pdf"
    assert doc.data == b"%PDF-1.4 fake content"


def test_send_message_missing_file_path_raises(tmp_path: "os.PathLike[str]") -> None:
    with pytest.raises(RuntimeError, match="file_path not found"):
        send_message(
            "5drr7us",
            "Test",
            [{"file_path": os.path.join(tmp_path, "missing.pdf"), "is_main": True}],
        )


def test_send_message_attachment_without_source_raises() -> None:
    with pytest.raises(RuntimeError, match="file_path.*content_base64"):
        send_message(
            "5drr7us",
            "Test",
            [{"filename": "a.pdf", "mime_type": "application/pdf", "is_main": True}],
        )


def test_send_text_message_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATOVKA_USERNAME", raising=False)
    monkeypatch.delenv("DATOVKA_PASSWORD", raising=False)
    from mcp_server_datovka import server

    server._get_client.cache_clear()
    with pytest.raises(RuntimeError, match="DATOVKA_USERNAME"):
        send_text_message("5drr7us", "Test", "Ahoj, toto je zkušební zpráva s háčky a čárkami.")
