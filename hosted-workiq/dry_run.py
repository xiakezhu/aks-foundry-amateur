"""Dry-run Work IQ toolbox MCP consume (Phase A allow-list).

  python dry_run.py --mock     # local fake MCP (no Azure)
  python dry_run.py --live     # TOOLBOX_ENDPOINT or FOUNDRY_PROJECT_ENDPOINT + az login
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from allowlist import PHASE_A_DENY, filter_phase_a_tools
from toolbox_mcp import ToolboxMcpClient, azure_ai_token, toolbox_endpoint_from_env

MOCK_TOOLS = [
    {"name": "fetch", "description": "Read a Work IQ path"},
    {"name": "ask", "description": "Ask Copilot over work data"},
    {"name": "get_schema", "description": "OpenAPI for a path"},
    {"name": "do_action", "description": "Mutating action"},
    {"name": "create_entity", "description": "Create an entity"},
]


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {}
        method = body.get("method")
        rpc_id = body.get("id", 1)
        if method == "tools/list":
            result: Any = {"tools": MOCK_TOOLS}
        elif method == "tools/call":
            params = body.get("params") or {}
            name = params.get("name")
            if name in PHASE_A_DENY:
                result = {"error": "write denied in mock Phase A"}
            else:
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"tool": name, "arguments": params.get("arguments")}
                            ),
                        }
                    ]
                }
        else:
            self.send_response(400)
            self.end_headers()
            return
        payload = json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_mock() -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/mcp"


def run_dry_run(client: ToolboxMcpClient) -> dict[str, Any]:
    listed = client.list_tools()
    names = [str(t.get("name") or "") for t in listed]
    allowed = filter_phase_a_tools(listed)
    allowed_names = [str(t.get("name") or "") for t in allowed]
    denied_visible = [n for n in names if n in PHASE_A_DENY or n.endswith("_do_action")]
    fetch = None
    if any(n == "fetch" or n.endswith("_fetch") for n in allowed_names):
        fetch = client.call_tool("fetch", {"path": "/me/messages"})
    return {
        "listed": names,
        "phase_a_allowed": allowed_names,
        "writes_hidden": not bool(set(allowed_names) & PHASE_A_DENY),
        "writes_present_on_server": denied_visible,
        "fetch": fetch,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run Work IQ toolbox MCP consume")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", help="local fake MCP (default)")
    mode.add_argument("--live", action="store_true", help="real toolbox (az login)")
    args = parser.parse_args(argv)

    server = None
    try:
        if args.live:
            endpoint = toolbox_endpoint_from_env()
            client = ToolboxMcpClient(endpoint, token_provider=azure_ai_token)
            print(f"live toolbox {endpoint}", file=sys.stderr)
        else:
            server, endpoint = start_mock()
            client = ToolboxMcpClient(endpoint, token_provider=None)
            print(f"mock toolbox {endpoint}", file=sys.stderr)
        report = run_dry_run(client)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

    print(json.dumps(report, indent=2, default=str))
    if not report["writes_hidden"]:
        print("FAIL: Phase A allow-list leaked write verbs", file=sys.stderr)
        return 1
    if "fetch" not in report["phase_a_allowed"] and "ask" not in report["phase_a_allowed"]:
        print("FAIL: neither fetch nor ask survived Phase A filter", file=sys.stderr)
        return 1
    print("dry-run pass", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
