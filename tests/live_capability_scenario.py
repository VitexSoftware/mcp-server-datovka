#!/usr/bin/env python3
"""Live capability scenario for the Czech ISDS Data Box MCP server.

Exercises every MCP tool against a real data box and reports whether each
capability returns usable data (or correctly refuses writes under READ_ONLY).

Usage:
  DATOVKA_USERNAME=... DATOVKA_PASSWORD=... \\
    python tests/live_capability_scenario.py

  # Prefer the public testing sandbox when you have test-box credentials:
  DATOVKA_URL=https://ws1.czebox.cz/ DATOVKA_USERNAME=... DATOVKA_PASSWORD=... \\
    python tests/live_capability_scenario.py

  python tests/live_capability_scenario.py \\
    --url https://ws1.mojedatovaschranka.cz/ \\
    --username dz83h6 --password '...'

Exit code is 0 only when every non-skipped check passes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
for path in (str(PROJECT_ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)


@dataclass
class CheckResult:
    name: str
    kind: str  # tool | meta | guard
    ok: bool
    detail: str = ""
    sample: Any = None
    skipped: bool = False


@dataclass
class ScenarioReport:
    url: str
    username: str
    results: List[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.ok and not r.skipped)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.ok and not r.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.skipped)


def _parse_payload(data: Any) -> Any:
    if isinstance(data, str):
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data
    return data


def _is_error_payload(data: Any) -> Optional[str]:
    data = _parse_payload(data)
    if isinstance(data, str):
        low = data.lower()
        if "error" in low or "traceback" in low or "exception" in low:
            return data[:300]
        return None
    if not isinstance(data, dict):
        return None
    if data.get("error") is True or data.get("success") is False:
        return str(data.get("message") or data.get("reason") or data)[:300]
    return None


def _has_usable_data(data: Any) -> tuple[bool, str]:
    data = _parse_payload(data)
    err = _is_error_payload(data)
    if err:
        return False, err
    if data is None:
        return False, "null response"
    if isinstance(data, str):
        return (bool(data.strip()), "empty string" if not data.strip() else "ok string")
    if isinstance(data, list):
        return True, f"list len={len(data)}"
    if isinstance(data, dict):
        if data:
            return True, f"keys={list(data.keys())[:8]}"
        return False, "empty object"
    return True, f"type={type(data).__name__}"


def _run_check(
    report: ScenarioReport,
    name: str,
    kind: str,
    fn: Callable[[], Any],
    *,
    require_data: bool = True,
    skip_reason: Optional[str] = None,
) -> Optional[Any]:
    if skip_reason:
        report.add(CheckResult(name=name, kind=kind, ok=True, detail=skip_reason, skipped=True))
        return None
    try:
        raw = fn()
        ok, detail = _has_usable_data(raw) if require_data else (True, "invoked")
        sample = _parse_payload(raw)
        try:
            preview = json.dumps(sample, ensure_ascii=False, default=str)
        except TypeError:
            preview = str(sample)
        report.add(
            CheckResult(
                name=name,
                kind=kind,
                ok=ok,
                detail=detail,
                sample=preview[:800],
            )
        )
        return raw
    except Exception as exc:  # noqa: BLE001 — scenario must keep going
        report.add(
            CheckResult(
                name=name,
                kind=kind,
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                sample=traceback.format_exc()[-600:],
            )
        )
        return None


def run_scenario(
    url: str,
    username: str,
    password: str,
    *,
    read_only: bool = True,
    find_query: str = "spojenet",
) -> ScenarioReport:
    os.environ["DATOVKA_URL"] = url
    os.environ["DATOVKA_USERNAME"] = username
    os.environ["DATOVKA_PASSWORD"] = password
    os.environ["READ_ONLY"] = "true" if read_only else "false"

    import importlib

    import mcp_server_datovka.server as server

    server._get_client.cache_clear()
    server = importlib.reload(server)
    server._get_client.cache_clear()

    report = ScenarioReport(url=url, username=username)
    tools = asyncio.run(server.mcp.list_tools())
    tool_names = {t.name for t in tools}

    expected = {
        "list_received_messages",
        "list_sent_messages",
        "get_message",
        "mark_message_read",
        "send_message",
        "send_text_message",
        "find_data_box",
        "ping",
    }
    report.add(
        CheckResult(
            name="tool_catalog",
            kind="meta",
            ok=tool_names == expected,
            detail=f"registered={sorted(tool_names)}",
        )
    )
    report.add(
        CheckResult(
            name="read_only_flag",
            kind="meta",
            ok=server.is_read_only() is read_only,
            detail=f"is_read_only()={server.is_read_only()} expected={read_only}",
        )
    )

    # ---- session / lists ----
    _run_check(report, "ping", "tool", server.ping)

    recv = _run_check(
        report,
        "list_received_messages",
        "tool",
        lambda: server.list_received_messages(limit=5),
    )
    message_id = None
    if isinstance(recv, list) and recv and isinstance(recv[0], dict):
        message_id = recv[0].get("message_id")

    _run_check(
        report,
        "list_sent_messages",
        "tool",
        lambda: server.list_sent_messages(limit=5),
    )

    # ---- message detail ----
    _run_check(
        report,
        "get_message",
        "tool",
        lambda: server.get_message(str(message_id), include_attachment_content=False),
        skip_reason=None if message_id else "no received message id",
    )
    msg_with_content = _run_check(
        report,
        "get_message:with_content",
        "tool",
        lambda: server.get_message(str(message_id), include_attachment_content=True),
        skip_reason=None if message_id else "no received message id",
    )
    if msg_with_content is not None and isinstance(msg_with_content, dict):
        docs = msg_with_content.get("documents") or []
        has_b64 = any(
            isinstance(d, dict) and d.get("content_base64") for d in docs if isinstance(d, dict)
        )
        # Empty attachment list is rare but acceptable; otherwise require base64.
        ok = (not docs) or has_b64
        report.add(
            CheckResult(
                name="get_message:content_base64_present",
                kind="meta",
                ok=ok,
                detail=f"documents={len(docs)} has_content_base64={has_b64}",
            )
        )

    # ---- directory lookup ----
    found = _run_check(
        report,
        "find_data_box",
        "tool",
        lambda: server.find_data_box(find_query, limit=5),
    )
    if isinstance(found, dict):
        source = found.get("source")
        results = found.get("results")
        ok = source in ("seznamds-offline", "isds-live") and isinstance(results, list)
        report.add(
            CheckResult(
                name="find_data_box:shape",
                kind="meta",
                ok=ok,
                detail=f"source={source} results={len(results) if isinstance(results, list) else type(results).__name__}",
            )
        )
        if isinstance(results, list) and not results:
            report.add(
                CheckResult(
                    name="find_data_box:nonempty",
                    kind="meta",
                    ok=False,
                    detail=f"query={find_query!r} returned zero results from {source}",
                )
            )
        elif isinstance(results, list):
            report.add(
                CheckResult(
                    name="find_data_box:nonempty",
                    kind="meta",
                    ok=True,
                    detail=f"query={find_query!r} n={len(results)} via {source}",
                )
            )

    # ---- READ_ONLY guards on mutating tools ----
    if read_only:
        sample_writes: list[tuple[str, Callable[[], Any]]] = [
            (
                "send_message",
                lambda: server.send_message(
                    "aaaaaaa",
                    "MCP live capability must not send",
                    [
                        {
                            "filename": "x.pdf",
                            "mime_type": "application/pdf",
                            "content_base64": "eA==",
                            "is_main": True,
                        }
                    ],
                ),
            ),
            (
                "send_text_message",
                lambda: server.send_text_message(
                    "aaaaaaa",
                    "MCP live capability must not send",
                    "This must be blocked by READ_ONLY.",
                ),
            ),
            (
                "mark_message_read",
                lambda: server.mark_message_read(str(message_id or "0")),
            ),
        ]
        for name, fn in sample_writes:
            try:
                raw = fn()
                payload = _parse_payload(raw)
                refused = isinstance(payload, dict) and "read-only" in str(payload).lower()
                report.add(
                    CheckResult(
                        name=f"readonly_guard:{name}",
                        kind="guard",
                        ok=refused,
                        detail="write returned without raising" if not refused else "refused in payload",
                        sample=str(payload)[:300],
                    )
                )
            except ValueError as exc:
                ok = "read-only" in str(exc).lower()
                report.add(
                    CheckResult(
                        name=f"readonly_guard:{name}",
                        kind="guard",
                        ok=ok,
                        detail=str(exc),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                report.add(
                    CheckResult(
                        name=f"readonly_guard:{name}",
                        kind="guard",
                        ok=False,
                        detail=f"unexpected {type(exc).__name__}: {exc}",
                    )
                )

        for tname in ("send_message", "send_text_message", "mark_message_read"):
            report.add(
                CheckResult(
                    name=f"catalog:{tname}",
                    kind="meta",
                    ok=tname in tool_names,
                    detail="write tool registered (guard-sampled separately)",
                )
            )

    return report


def main() -> int:
    from datovka.client import DEFAULT_URL

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("DATOVKA_URL", DEFAULT_URL))
    parser.add_argument("--username", default=os.getenv("DATOVKA_USERNAME"))
    parser.add_argument("--password", default=os.getenv("DATOVKA_PASSWORD"))
    parser.add_argument(
        "--find-query",
        default=os.getenv("DATOVKA_FIND_QUERY", "spojenet"),
        help="Query for find_data_box (default: spojenet)",
    )
    parser.add_argument("--json-out", help="Write full report JSON here")
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="Set READ_ONLY=false (guards skipped; do not use on production)",
    )
    args = parser.parse_args()

    missing = [
        n
        for n, v in [
            ("--username/DATOVKA_USERNAME", args.username),
            ("--password/DATOVKA_PASSWORD", args.password),
        ]
        if not v
    ]
    if missing:
        print(f"Missing required config: {', '.join(missing)}", file=sys.stderr)
        return 2

    report = run_scenario(
        args.url,
        args.username,
        args.password,
        read_only=not args.allow_writes,
        find_query=args.find_query,
    )

    print(f"Datovka MCP live scenario: {report.url} as {report.username}")
    print(f"passed={report.passed} failed={report.failed} skipped={report.skipped}")
    print()
    for r in report.results:
        if r.skipped:
            flag = "SKIP"
        elif r.ok:
            flag = "PASS"
        else:
            flag = "FAIL"
        print(f"  {flag:4} [{r.kind}] {r.name}: {r.detail}")

    if args.json_out:
        out = {
            "url": report.url,
            "username": report.username,
            "passed": report.passed,
            "failed": report.failed,
            "skipped": report.skipped,
            "results": [r.__dict__ for r in report.results],
        }
        Path(args.json_out).write_text(
            json.dumps(out, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"\nWrote {args.json_out}")

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
