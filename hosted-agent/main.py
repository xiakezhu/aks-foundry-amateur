"""Minimal Foundry hosted agent using the Responses protocol."""

import asyncio

from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    TextResponse,
)

app = ResponsesAgentServerHost()


@app.response_handler
async def handler(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
):
    input_text = await context.get_input_text()
    return TextResponse(context, request, text=f"hosted-echo: {input_text}")


if __name__ == "__main__":
    app.run()
