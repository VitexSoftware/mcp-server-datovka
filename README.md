# mcp-server-datovka

![mcp-server-datovka icon](mcp-server-datovka.svg)

An [MCP](https://modelcontextprotocol.io) server exposing the Czech ISDS
Data Box system ("Datové schránky") as tools, built on
[fastmcp](https://gofastmcp.com) and
[python3-datovka](https://github.com/VitexSoftware/python3-libdatovka).

## Tools

| Tool | Description |
|---|---|
| `list_received_messages(limit=20)` | Summaries of received messages, most recent first |
| `list_sent_messages(limit=20)` | Summaries of sent messages, most recent first |
| `get_message(message_id, include_attachment_content=False)` | Full message with documents; attachment bytes are base64-encoded and only included on request |
| `mark_message_read(message_id)` | Mark a received message as read |
| `send_message(recipient_box_id, subject, attachments, ...)` | Send a new message; `attachments` is a list of `{filename, mime_type, content_base64, is_main}` dicts, exactly one of which must be `is_main=True` |
| `send_text_message(recipient_box_id, subject, body)` | Compose plain text as a PDF and send it as the message's main document — no existing file needed |
| `find_data_box(query, limit=10)` | Look up a recipient's data box ID by name, trade name, or IČO. Uses the offline `seznamds` directory first (fast, unlimited), falling back to the live, rate-limited ISDS search API if it's absent or finds nothing. The response includes `source` and `data_age_days` so a stale offline snapshot doesn't get presented as current. |
| `ping()` | Verify the session is alive |

Messages in ISDS are envelope + document attachments, not a body text field
— that's why sending "just text" (`send_text_message`) means rendering it
to a PDF first, using the system's DejaVu Sans font so Czech diacritics
render correctly.

## Configuration

Credentials are read once from the environment at startup and are never
tool parameters, so the LLM driving the server can't see or choose them:

```bash
export DATOVKA_URL="https://ws1.mojedatovaschranka.cz/"  # optional, this is the default; trailing slash required
export DATOVKA_USERNAME="..."
export DATOVKA_PASSWORD="..."
```

Install the optional `seznamds` package for fast, unlimited recipient
lookups via `find_data_box`:

```bash
apt install seznamds
```

Without it, `find_data_box` still works but falls back to the live,
rate-limited ISDS search API for every lookup.

## Running

```bash
mcp-server-datovka
```

Or point an MCP client at it directly:

```bash
python -m mcp_server_datovka.server
```

## Requirements

- `libdatovka8` + `python3-datovka` (or `pip install datovka`)
- `fastmcp`
- `python3-fpdf` (`fpdf2`) + `fonts-dejavu-core`, for `send_text_message`
- `seznamds` (recommended, optional), for fast offline `find_data_box` lookups

## License

LGPL-3.0-or-later.
