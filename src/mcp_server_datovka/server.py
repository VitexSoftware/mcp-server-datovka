"""MCP server exposing the Czech ISDS Data Box system as tools.

Credentials are read once from the environment at startup
(``DATOVKA_URL``, ``DATOVKA_USERNAME``, ``DATOVKA_PASSWORD``) and never
exposed as tool parameters, so an LLM driving this server can act on a
data box without ever seeing or choosing the login credentials.

Write tools (``send_message``, ``send_text_message``, ``mark_message_read``)
are blocked when ``READ_ONLY`` is enabled (default: true).
"""

from __future__ import annotations

import base64
import mimetypes
import os
from ctypes import POINTER, byref
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from datovka import DatovkaClient, DatovkaError, OutgoingDocument
from datovka import _capi
from datovka.client import DEFAULT_URL, _check
from datovka.models import Document, Envelope, Message
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import seznamds
from .pdf import text_to_pdf

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
# Idempotent state change that is easily reversible (read flag).
ASSIGN_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
# Sends a legally binding, irreversible data box message; each call sends again.
SEND_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)

mcp = FastMCP("Datovka")


def is_read_only() -> bool:
    """Return True when write tools must refuse to mutate the data box."""
    return os.getenv("READ_ONLY", "true").lower() in ("true", "1", "yes")


def validate_read_only() -> None:
    """Raise if the server is in read-only mode (write tools must call this first)."""
    if is_read_only():
        raise ValueError("Server is in read-only mode - write operations are not allowed")


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


def _fetch_sent_message(client: DatovkaClient, message_id: str) -> Message:
    """Download a sent message in full, including its documents.

    python3-datovka (<= 0.2.0) binds libdatovka's
    ``isds_get_signed_sent_message`` but has no high-level wrapper for it,
    so call the binding directly and reuse the client's own struct parsing.
    ISDS only offers sent messages in signed (CMS) form; libdatovka unwraps
    the signature and parses envelope and documents for us.

    TODO: this belongs in python3-datovka as a public
    ``DatovkaClient.get_sent_message`` next to ``get_received_message``.
    Once it is upstreamed, switch to it (raising the minimum ``datovka``
    version) and drop this reliance on private internals.
    """
    client._require_login()
    message_ptr = POINTER(_capi.IsdsMessage)()
    code = _capi.lib.isds_get_signed_sent_message(
        client._ctx, message_id.encode("utf-8"), byref(message_ptr)
    )
    try:
        _check(client._ctx, code, "failed to fetch sent message")
        return client._message_from_struct(message_ptr, message_id)
    finally:
        if message_ptr:
            _capi.lib.isds_message_free(byref(message_ptr))


@mcp.tool(
    title="List Received Messages",
    annotations=READ_ONLY_ANNOTATIONS,
)
def list_received_messages(limit: int = 20) -> list[dict[str, Any]]:
    """List summaries of received data box messages, most recent first."""
    try:
        envelopes = _get_client().list_received_messages(limit=limit)
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return [_envelope_to_dict(e) for e in envelopes]


@mcp.tool(
    title="List Sent Messages",
    annotations=READ_ONLY_ANNOTATIONS,
)
def list_sent_messages(limit: int = 20) -> list[dict[str, Any]]:
    """List summaries of sent data box messages, most recent first."""
    try:
        envelopes = _get_client().list_sent_messages(limit=limit)
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return [_envelope_to_dict(e) for e in envelopes]


@mcp.tool(
    title="Get Message",
    annotations=READ_ONLY_ANNOTATIONS,
)
def get_message(message_id: str, include_attachment_content: bool = False) -> dict[str, Any]:
    """Fetch a received message in full: envelope plus its documents.

    For messages from list_sent_messages, use get_sent_message instead.
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


@mcp.tool(
    title="Get Sent Message",
    annotations=READ_ONLY_ANNOTATIONS,
)
def get_sent_message(message_id: str, include_attachment_content: bool = False) -> dict[str, Any]:
    """Fetch a sent message in full: envelope plus its documents.

    Counterpart of get_message for messages listed by list_sent_messages.
    By default, attachment content is omitted (only filename/mime_type/size
    are returned) to avoid flooding the response with large base64 blobs.
    Set include_attachment_content=True to fetch the actual file bytes,
    base64-encoded.
    """
    try:
        message = _fetch_sent_message(_get_client(), message_id)
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return _message_to_dict(message, include_content=include_attachment_content)


@mcp.tool(
    title="Send Message",
    annotations=SEND_ANNOTATIONS,
)
def send_message(
    recipient_box_id: str,
    subject: str,
    attachments: list[dict[str, Any]],
    recipient_org_unit: str | None = None,
    sender_ref_number: str | None = None,
) -> str:
    """Send a new message with file attachments to a data box.

    Blocked when ``READ_ONLY`` is enabled (default).

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
    validate_read_only()
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


@mcp.tool(
    title="Send Text Message",
    annotations=SEND_ANNOTATIONS,
)
def send_text_message(recipient_box_id: str, subject: str, body: str) -> str:
    """Compose plain text as a PDF and send it as a new message.

    Blocked when ``READ_ONLY`` is enabled (default).

    Convenience wrapper around send_message for the common case of writing
    a message from scratch: renders ``body`` (with ``subject`` as a
    heading) to a PDF and sends it as the message's single, main document.
    Use send_message directly instead if you already have file(s) to
    attach, or need more than one document.
    """
    validate_read_only()
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


@mcp.tool(
    title="Find Data Box",
    annotations=READ_ONLY_ANNOTATIONS,
)
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


@mcp.tool(
    title="Mark Message Read",
    annotations=ASSIGN_ANNOTATIONS,
)
def mark_message_read(message_id: str) -> str:
    """Mark a received message as read.

    Blocked when ``READ_ONLY`` is enabled (default).
    """
    validate_read_only()
    try:
        _get_client().mark_as_read(message_id)
    except DatovkaError as exc:
        raise RuntimeError(str(exc)) from exc
    return f"Message {message_id} marked as read."


@mcp.tool(
    title="Ping",
    annotations=READ_ONLY_ANNOTATIONS,
)
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
                    Testing: https://ws1.czebox.cz/  (trailing slash required)
  DATOVKA_USERNAME  ISDS login username (required)
  DATOVKA_PASSWORD  ISDS login password (required)
  READ_ONLY         Block send/mark-read tools when true/1/yes (default: true)

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
