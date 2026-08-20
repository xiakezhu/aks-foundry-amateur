"""Foundry hosted agent that consumes work-iq-toolbox via MCP (official OBO path).

Does not call https://workiq.svc.cloud.microsoft/mcp itself. Does not store
WorkIQAgent.Ask. Model tool-calling (DeepSeek) is not wired in this slice;
a dry-run prompt returns Phase A tool names from the toolbox.
"""

from __future__ import annotations

import asyncio
import json
import os

from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    TextResponse,
)

from allowlist import filter_phase_a_tools
from toolbox_mcp import ToolboxMcpClient, azure_ai_token, toolbox_endpoint_from_env

app = ResponsesAgentServerHost()


def build_client() -> ToolboxMcpClient:
    endpoint = os.environ.get("WORKIQ_DRY_RUN_ENDPOINT") or toolbox_endpoint_from_env()
    provider = None if os.environ.get("WORKIQ_DRY_RUN_ENDPOINT") else azure_ai_token
    return ToolboxMcpClient(endpoint, token_provider=provider)


def dry_run_report() -> dict:
    client = build_client()
    listed = client.list_tools()
    allowed = filter_phase_a_tools(listed)
    return {
        "toolbox": os.environ.get("TOOLBOX_NAME", "work-iq-toolbox"),
        "listed": [t.get("name") for t in listed],
        "phase_a": [t.get("name") for t in allowed],
    }


@app.response_handler
async def handler(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
):
    input_text = ((await context.get_input_text()) or "").strip()
    try:
        report = await asyncio.to_thread(dry_run_report)
        text = json.dumps(report, indent=2)
        if input_text and input_text not in ("__workiq_dry_run__", "list tools", "list the tools you can use"):
            text = (
                "hosted-workiq dry-run (DeepSeek tool loop not wired yet).\n"
                f"user: {input_text}\n{text}"
            )
    except Exception as exc:
        text = f"hosted-workiq error: {exc}"
    return TextResponse(context, request, text=text)


if __name__ == "__main__":
    print("hosted-workiq starting", flush=True)
    app.run()
