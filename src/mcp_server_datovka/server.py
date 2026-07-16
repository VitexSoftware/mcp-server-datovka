"""MCP server exposing the Czech ISDS Data Box system as tools.

Credentials are read once from the environment at startup
(``DATOVKA_URL``, ``DATOVKA_USERNAME``, ``DATOVKA_PASSWORD``) and never
exposed as tool parameters, so an LLM driving this server can act on a
data box without ever seeing or choosing the login credentials.
"""

from __future__ import annotations

import base64
import os
from datetime import datetime
from functools import lru_cache
from typing import Any

from datovka import DatovkaClient, DatovkaError
from datovka.client import DEFAULT_URL
from datovka.models import Document, Envelope, Message
from fastmcp import FastMCP

mcp = FastMCP("Datovka")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _envelope_to_dict(env: Envelope) -> dict[str, Any]:
    return {
        "message_id": env.message_id,
        "sender_box_id": env.sender_box_id,
        "sender_name": env.sender_name,
        "recipient_box_id": env.recipient_box_id,
        "recipient_name": env.recipient_name,
        "subject": env.subject,
        "delivery_time": _iso(env.delivery_time),
        "acceptance_time": _iso(env.acceptance_time),
        "status": env.status,
        "attachment_size_kb": env.attachment_size_kb,
        "message_type": env.message_type,
    }


def _document_to_dict(doc: Document, *, include_content: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "is_main": doc.is_main,
        "size_bytes": len(doc.data),
    }
    if include_content:
        result["content_base64"] = base64.b64encode(doc.data).decode("ascii")
    return result


def _message_to_dict(msg: Message, *, include_content: bool) -> dict[str, Any]:
    return {
        "envelope": _envelope_to_dict(msg.envelope),
        "documents": [_document_to_dict(d, include_content=include_content) for d in msg.documents],
    }


@lru_cache(maxsize=1)
def _get_client() -> DatovkaClient:
    """Create (once) and return the logged-in ISDS session for this process."""
    url = os.environ.get("DATOVKA_URL", DEFAULT_URL)
    username = os.environ.get("DATOVKA_USERNAME")
    password = os.environ.get("DATOVKA_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "DATOVKA_USERNAME and DATOVKA_PASSWORD environment variables are required."
        )
    return DatovkaClient(url, username, password)


@mcp.tool
def list_received_messages(limit: int = 20) -> list[dict[str, Any]]:
    """List summaries of received data box messages, most recent first."""
    try:
        envelopes = _get_client().list_received_messages(limit=limit)
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return [_envelope_to_dict(e) for e in envelopes]


@mcp.tool
def list_sent_messages(limit: int = 20) -> list[dict[str, Any]]:
    """List summaries of sent data box messages, most recent first."""
    try:
        envelopes = _get_client().list_sent_messages(limit=limit)
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return [_envelope_to_dict(e) for e in envelopes]


@mcp.tool
def get_message(message_id: str, include_attachment_content: bool = False) -> dict[str, Any]:
    """Fetch a received message in full: envelope plus its documents.

    By default, attachment content is omitted (only filename/mime_type/size
    are returned) to avoid flooding the response with large base64 blobs.
    Set include_attachment_content=True to fetch the actual file bytes,
    base64-encoded.
    """
    try:
        message = _get_client().get_received_message(message_id)
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return _message_to_dict(message, include_content=include_attachment_content)


@mcp.tool
def mark_message_read(message_id: str) -> str:
    """Mark a received message as read."""
    try:
        _get_client().mark_as_read(message_id)
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return f"Message {message_id} marked as read."


@mcp.tool
def ping() -> str:
    """Verify the data box session is alive and the server is reachable."""
    try:
        _get_client().ping()
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return "ok"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
