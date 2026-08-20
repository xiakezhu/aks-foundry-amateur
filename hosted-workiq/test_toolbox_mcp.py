"""Local tests for Phase A allow-list and mock toolbox MCP (no Azure)."""

from __future__ import annotations

import json
import unittest

from allowlist import filter_phase_a_tools, is_phase_a_allowed
from dry_run import run_dry_run, start_mock
from toolbox_mcp import ToolboxMcpClient


class AllowlistTests(unittest.TestCase):
    def test_allows_read_verbs(self):
        for name in ("fetch", "ask", "get_schema", "workiq_fetch"):
            self.assertTrue(is_phase_a_allowed(name), name)

    def test_denies_writes(self):
        for name in ("do_action", "create_entity", "workiq_do_action"):
            self.assertFalse(is_phase_a_allowed(name), name)

    def test_filter_drops_writes(self):
        tools = [
            {"name": "fetch"},
            {"name": "do_action"},
            {"name": "create_entity"},
            {"name": "ask"},
        ]
        kept = filter_phase_a_tools(tools)
        self.assertEqual([t["name"] for t in kept], ["fetch", "ask"])


class MockMcpTests(unittest.TestCase):
    def test_dry_run_hides_writes_and_calls_fetch(self):
        server, endpoint = start_mock()
        try:
            client = ToolboxMcpClient(endpoint)
            report = run_dry_run(client)
        finally:
            server.shutdown()
            server.server_close()
        self.assertIn("fetch", report["phase_a_allowed"])
        self.assertIn("ask", report["phase_a_allowed"])
        self.assertTrue(report["writes_hidden"])
        self.assertIn("do_action", report["writes_present_on_server"])
        self.assertIsNotNone(report["fetch"])
        payload = report["fetch"]
        if isinstance(payload, dict) and "content" in payload:
            text = payload["content"][0]["text"]
            body = json.loads(text)
            self.assertEqual(body["tool"], "fetch")
            self.assertEqual(body["arguments"]["path"], "/me/messages")


if __name__ == "__main__":
    unittest.main()
