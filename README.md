# mcp-server-datovka

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
| `ping()` | Verify the session is alive |

## Configuration

Credentials are read once from the environment at startup and are never
tool parameters, so the LLM driving the server can't see or choose them:

```bash
export DATOVKA_URL="https://ws1.mojedatovaschranka.cz"  # optional, this is the default
export DATOVKA_USERNAME="..."
export DATOVKA_PASSWORD="..."
```

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

## License

LGPL-3.0-or-later.
