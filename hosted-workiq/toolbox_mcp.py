"""JSON-RPC MCP client for a Foundry toolbox (or a local mock).

This is the consume side of official toolbox + OBO: POST tools/list and
tools/call to the toolbox MCP URL with a Foundry token (audience
https://ai.azure.com). It does not open Work IQ /mcp itself and does not
send WorkIQAgent.Ask.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Optional
import httpx

TokenProvider = Callable[[], str]


def toolbox_endpoint_from_env() -> str:
    explicit = os.environ.get("TOOLBOX_ENDPOINT", "").strip()
    if explicit:
        return explicit
    project = (
        os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
        or os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
        or ""
    ).rstrip("/")
    name = os.environ.get("TOOLBOX_NAME", "work-iq-toolbox").strip()
    if not project:
        raise RuntimeError(
            "Set TOOLBOX_ENDPOINT or FOUNDRY_PROJECT_ENDPOINT (and optional TOOLBOX_NAME)"
        )
    return f"{project}/toolboxes/{name}/mcp?api-version=v1"


def azure_ai_token() -> str:
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential().get_token("https://ai.azure.com/.default").token


class ToolboxMcpClient:
    def __init__(
        self,
        endpoint: str,
        token_provider: Optional[TokenProvider] = None,
        timeout: float = 60.0,
    ):
        self.endpoint = endpoint
        self.token_provider = token_provider
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token_provider:
            headers["Authorization"] = f"Bearer {self.token_provider()}"
        return headers

    def _parse_body(self, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise RuntimeError("empty MCP response")
        if text.startswith("data:"):
            data_lines = []
            for line in text.splitlines():
                if line.startswith("data:"):
                    data_lines.append(line[5:].strip())
            text = "\n".join(data_lines).strip() or text
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise RuntimeError(f"MCP response is not an object: {type(payload)}")
        if payload.get("error"):
            raise RuntimeError(f"MCP error: {payload['error']}")
        return payload

    def request(self, method: str, params: Optional[dict[str, Any]] = None, rpc_id: int = 1) -> Any:
        body = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
            "params": params or {},
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.endpoint, headers=self._headers(), json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"MCP HTTP {response.status_code}: {response.text[:800]}")
        payload = self._parse_body(response.text)
        return payload.get("result")

    def list_tools(self) -> list[dict]:
        result = self.request("tools/list")
        if result is None:
            return []
        if isinstance(result, dict):
            tools = result.get("tools") or result.get("result") or []
        else:
            tools = result
        if not isinstance(tools, list):
            raise RuntimeError(f"tools/list did not return a list: {type(tools)}")
        return [t for t in tools if isinstance(t, dict)]

    def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> Any:
        return self.request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
