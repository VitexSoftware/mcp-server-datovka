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
        "get_sent_message",
        "save_attachments",
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
    monkeypatch.setenv("READ_ONLY", "false")
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


def test_write_tools_blocked_when_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("READ_ONLY", "true")
    from mcp_server_datovka import server

    with pytest.raises(ValueError, match="read-only"):
        send_message(
            "5drr7us",
            "Test",
            [{"filename": "a.pdf", "mime_type": "application/pdf", "content_base64": "eA==", "is_main": True}],
        )
    with pytest.raises(ValueError, match="read-only"):
        send_text_message("5drr7us", "Test", "body")
    with pytest.raises(ValueError, match="read-only"):
        server.mark_message_read("1")


def test_send_message_file_path_requires_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: "os.PathLike[str]"
) -> None:
    monkeypatch.setenv("READ_ONLY", "false")
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


def test_send_message_missing_file_path_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: "os.PathLike[str]"
) -> None:
    monkeypatch.setenv("READ_ONLY", "false")
    with pytest.raises(RuntimeError, match="file_path not found"):
        send_message(
            "5drr7us",
            "Test",
            [{"file_path": os.path.join(tmp_path, "missing.pdf"), "is_main": True}],
        )


def test_send_message_attachment_without_source_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("READ_ONLY", "false")
    with pytest.raises(RuntimeError, match="file_path.*content_base64"):
        send_message(
            "5drr7us",
            "Test",
            [{"filename": "a.pdf", "mime_type": "application/pdf", "is_main": True}],
        )


def test_send_text_message_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("READ_ONLY", "false")
    monkeypatch.delenv("DATOVKA_USERNAME", raising=False)
    monkeypatch.delenv("DATOVKA_PASSWORD", raising=False)
    from mcp_server_datovka import server

    server._get_client.cache_clear()
    with pytest.raises(RuntimeError, match="DATOVKA_USERNAME"):
        send_text_message("5drr7us", "Test", "Ahoj, toto je zkušební zpráva s háčky a čárkami.")


def test_get_sent_message_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATOVKA_USERNAME", raising=False)
    monkeypatch.delenv("DATOVKA_PASSWORD", raising=False)
    from mcp_server_datovka import server

    server._get_client.cache_clear()
    with pytest.raises(RuntimeError, match="DATOVKA_USERNAME"):
        server.get_sent_message("1")


def test_get_sent_message_uses_signed_sent_download(monkeypatch: pytest.MonkeyPatch) -> None:
    from datovka.models import Document, Envelope, Message

    from mcp_server_datovka import server

    calls: list[str] = []

    def fake_download(ctx, message_id, message_pp):  # noqa: ANN001
        calls.append(message_id.decode("utf-8"))
        return server._capi.IE_SUCCESS

    message = Message(
        envelope=Envelope(
            message_id="42",
            sender_box_id=None,
            sender_name=None,
            recipient_box_id="abc1234",
            recipient_name=None,
            subject="Test",
            delivery_time=None,
            acceptance_time=None,
            status=None,
            attachment_size_kb=None,
            message_type=None,
        ),
        documents=[Document(filename="a.pdf", mime_type="application/pdf", is_main=True, data=b"x")],
    )

    class FakeClient:
        _ctx = None

        def _require_login(self) -> None:
            pass

        def _message_from_struct(self, message_ptr, message_id: str) -> Message:  # noqa: ANN001
            assert message_id == "42"
            return message

    monkeypatch.setattr(server._capi.lib, "isds_get_signed_sent_message", fake_download)
    monkeypatch.setattr(server._capi.lib, "isds_message_free", lambda pp: None)
    monkeypatch.setattr(server, "_get_client", lambda: FakeClient())

    result = server.get_sent_message("42", include_attachment_content=True)

    assert calls == ["42"]
    assert result["envelope"]["message_id"] == "42"
    assert result["documents"][0]["filename"] == "a.pdf"
    assert result["documents"][0]["content_base64"] == "eA=="


def test_every_tool_has_title_and_annotations() -> None:
    for tool in asyncio.run(mcp.list_tools()):
        assert tool.title and tool.title != tool.name, tool.name
        a = tool.annotations
        assert a is not None, tool.name
        for hint in (
            "read_only_hint",
            "destructive_hint",
            "idempotent_hint",
            "open_world_hint",
        ):
            assert getattr(a, hint) is not None, f"{tool.name}: {hint} unset"
        assert not (a.read_only_hint and a.destructive_hint), tool.name
        if tool.name.startswith(("get_", "list_", "find_")):
            assert a.read_only_hint is True, tool.name
        if tool.name.startswith("send_"):
            assert a.destructive_hint is True, tool.name


def test_parse_date_handles_date_and_end_of_day() -> None:
    from mcp_server_datovka.server import _parse_date

    assert _parse_date(None) is None
    start = _parse_date("2024-10-01")
    end = _parse_date("2024-10-01", end_of_day=True)
    assert start is not None and end is not None
    assert end.tv_sec - start.tv_sec == 86399
    with pytest.raises(ValueError):
        _parse_date("not-a-date")


def test_save_attachments_writes_files_and_never_overwrites(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from types import SimpleNamespace

    from mcp_server_datovka import server

    doc = SimpleNamespace(
        filename="../evil/zpráva.pdf", mime_type="application/pdf", is_main=True, data=b"%PDF"
    )
    client = SimpleNamespace(get_received_message=lambda _id: SimpleNamespace(documents=[doc]))
    monkeypatch.setattr(server, "_get_client", lambda: client)

    first = server.save_attachments("42", str(tmp_path))
    second = server.save_attachments("42", str(tmp_path))
    assert first[0]["path"] == str(tmp_path / "42_0_zpráva.pdf")
    assert second[0]["path"] != first[0]["path"]
    assert (tmp_path / "42_0_zpráva.pdf").read_bytes() == b"%PDF"
    with pytest.raises(ValueError):
        server.save_attachments("42", "relative/dir")
