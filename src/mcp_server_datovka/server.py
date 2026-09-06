"""MCP server exposing the Czech ISDS Data Box system as tools.

Credentials are read once from the environment at startup
(``DATOVKA_URL``, ``DATOVKA_USERNAME``, ``DATOVKA_PASSWORD``) and never
exposed as tool parameters, so an LLM driving this server can act on a
data box without ever seeing or choosing the login credentials.
"""

from __future__ import annotations

import base64
import mimetypes
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from datovka import DatovkaClient, DatovkaError, OutgoingDocument
from datovka.client import DEFAULT_URL
from datovka.models import Document, Envelope, Message
from fastmcp import FastMCP

from . import seznamds
from .pdf import text_to_pdf

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
def send_message(
    recipient_box_id: str,
    subject: str,
    attachments: list[dict[str, Any]],
    recipient_org_unit: str | None = None,
    sender_ref_number: str | None = None,
) -> str:
    """Send a new message with file attachments to a data box.

    ``attachments`` is a list of dicts, each with keys ``filename``,
    ``mime_type``, ``is_main`` (bool), and exactly one of:

    - ``content_base64``: the file content, base64-encoded. Fine for small
      files, but each character has to pass through the calling LLM's
      context, so this gets impractical (slow, expensive, and risks silent
      corruption) for anything past a few hundred KB.
    - ``file_path``: an absolute path to the file on the machine running
      this server. Preferred for anything but tiny attachments -- the
      server reads the bytes itself, so the content never has to enter the
      conversation. ``filename``/``mime_type`` are optional with
      ``file_path``: they default to the path's basename and a guess from
      its extension (falling back to ``application/octet-stream``).

    Exactly one attachment must have ``is_main=True`` -- this is the ISDS
    API's own requirement, not a limitation of this tool. Total attachment
    size is capped by ISDS at 50 MB. For sending plain text without an
    existing file, use send_text_message instead.
    """
    documents = []
    for a in attachments:
        if "file_path" in a:
            path = Path(a["file_path"]).expanduser()
            if not path.is_file():
                raise RuntimeError(f"file_path not found: {path}")
            data = path.read_bytes()
            filename = a.get("filename") or path.name
            mime_type = a.get("mime_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        elif "content_base64" in a:
            data = base64.b64decode(a["content_base64"])
            filename = a["filename"]
            mime_type = a["mime_type"]
        else:
            raise RuntimeError("Each attachment needs either 'file_path' or 'content_base64'.")
        documents.append(
            OutgoingDocument(
                filename=filename,
                mime_type=mime_type,
                data=data,
                is_main=a.get("is_main", False),
            )
        )
    try:
        _get_client().send_message(
            recipient_box_id,
            subject,
            documents,
            recipient_org_unit=recipient_org_unit,
            sender_ref_number=sender_ref_number,
        )
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return f"Message sent to {recipient_box_id}."


@mcp.tool
def send_text_message(recipient_box_id: str, subject: str, body: str) -> str:
    """Compose plain text as a PDF and send it as a new message.

    Convenience wrapper around send_message for the common case of writing
    a message from scratch: renders ``body`` (with ``subject`` as a
    heading) to a PDF and sends it as the message's single, main document.
    Use send_message directly instead if you already have file(s) to
    attach, or need more than one document.
    """
    pdf_bytes = text_to_pdf(subject, body)
    document = OutgoingDocument(
        filename=f"{subject}.pdf",
        mime_type="application/pdf",
        data=pdf_bytes,
        is_main=True,
    )
    try:
        _get_client().send_message(recipient_box_id, subject, [document])
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return f"Message sent to {recipient_box_id}."


@mcp.tool
def find_data_box(query: str, limit: int = 10) -> dict[str, Any]:
    """Look up a data box ID by name, trade name, or IČO (company ID).

    Searches the offline ``seznamds`` directory first (fast, unlimited
    calls); only falls back to the live, rate-limited ISDS search API if
    ``seznamds`` isn't installed or finds nothing. Check the returned
    ``source`` and ``data_age_days`` fields: results from
    "seznamds-offline" may be stale (the directory is a periodic snapshot,
    not a live query) -- if ``data_age_days`` is large, treat name/address
    matches as provisional and consider that a recently created or renamed
    box may not appear yet.
    """
    age_days = seznamds.data_age_days()
    if age_days is not None:
        local_results = seznamds.search_local(query, limit=limit)
        if local_results:
            return {
                "source": "seznamds-offline",
                "data_age_days": age_days,
                "stale": age_days > seznamds.STALE_AFTER_DAYS,
                "results": local_results,
            }

    try:
        live_results = _get_client().find_box_live(query, limit=limit)
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return {"source": "isds-live", "data_age_days": 0, "stale": False, "results": live_results}


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


_HELP_TEXT = """\
usage: mcp-server-datovka

MCP server exposing the Czech ISDS Data Box system ("Datove schranky") as
tools, speaking the Model Context Protocol over stdio. Intended to be
launched by an MCP client (Claude Code, Claude Desktop, etc.), not run
interactively.

Environment variables:
  DATOVKA_URL       ISDS SOAP endpoint (optional, defaults to production)
  DATOVKA_USERNAME  ISDS login username (required)
  DATOVKA_PASSWORD  ISDS login password (required)

See mcp-server-datovka(1) for the full list of exposed tools.
"""


def main() -> None:
    import sys

    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(_HELP_TEXT, end="")
        return
    mcp.run()


if __name__ == "__main__":
    main()
