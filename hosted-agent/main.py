"""Foundry hosted Pi agent using the Responses protocol."""

import asyncio
import json
import os
import uuid
from pathlib import Path

from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    TextResponse,
)

AGENT_JS = Path(__file__).resolve().parent / "agent.mjs"
NODE_BIN = os.environ.get("NODE_BIN", "node")
AGENT_TIMEOUT_SEC = float(os.environ.get("PI_AGENT_TIMEOUT_SEC", "150"))

app = ResponsesAgentServerHost()


def _attr(obj, *names):
    for name in names:
        value = getattr(obj, name, None)
        if value:
            return value
        if isinstance(obj, dict) and obj.get(name):
            return obj[name]
    return None


def session_id_for(request: CreateResponse, context: ResponseContext) -> str:
    found = _attr(
        request,
        "agent_session_id",
        "session_id",
        "conversation_id",
    ) or _attr(
        context,
        "agent_session_id",
        "session_id",
    ) or os.environ.get("FOUNDRY_AGENT_SESSION_ID")
    return str(found) if found else f"anon-{uuid.uuid4()}"


async def run_pi_agent(prompt: str, session_id: str, cancel: asyncio.Event) -> str:
    env = os.environ.copy()
    if env.get("OPENAI_API_KEY") and not env.get("LLM_API_KEY"):
        env["LLM_API_KEY"] = env["OPENAI_API_KEY"]
    if env.get("LLM_API_KEY") and not env.get("OPENAI_API_KEY"):
        env["OPENAI_API_KEY"] = env["LLM_API_KEY"]

    missing = [
        name
        for name in ("OPENAI_BASE_URL", "OPENAI_MODEL")
        if not env.get(name)
    ]
    if missing or not (env.get("OPENAI_API_KEY") or env.get("LLM_API_KEY")):
        raise RuntimeError(
            "hosted Pi agent needs OPENAI_BASE_URL, OPENAI_MODEL, and OPENAI_API_KEY "
            "(or LLM_API_KEY) in the hosted-agent environment variables"
        )

    proc = await asyncio.create_subprocess_exec(
        NODE_BIN,
        str(AGENT_JS),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    payload = json.dumps({"prompt": prompt, "session_id": session_id}).encode()

    async def _wait():
        return await proc.communicate(payload)

    waiter = asyncio.create_task(_wait())
    cancel_waiter = asyncio.create_task(cancel.wait())
    done, pending = await asyncio.wait(
        {waiter, cancel_waiter},
        timeout=AGENT_TIMEOUT_SEC,
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    if cancel.is_set():
        proc.kill()
        raise RuntimeError("Pi agent cancelled")
    if waiter not in done:
        proc.kill()
        raise TimeoutError(f"Pi agent timed out after {AGENT_TIMEOUT_SEC}s")

    stdout, stderr = waiter.result()
    if stderr:
        print(stderr.decode("utf-8", errors="replace"), flush=True)
    raw = stdout.decode("utf-8", errors="replace").strip()
    if not raw:
        raise RuntimeError("Pi agent produced no output")
    try:
        body = json.loads(raw.splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Pi agent returned non-JSON: {raw[:500]}") from exc
    if proc.returncode not in (0, None) or body.get("error"):
        raise RuntimeError(body.get("error") or f"Pi agent exited {proc.returncode}")
    return str(body.get("text") or "").strip() or "(empty Pi response)"


@app.response_handler
async def handler(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
):
    input_text = (await context.get_input_text()) or ""
    session_id = session_id_for(request, context)
    try:
        text = await run_pi_agent(input_text, session_id, cancellation_signal)
    except Exception as exc:
        text = f"hosted-pi-agent error: {exc}"
    return TextResponse(context, request, text=text)


if __name__ == "__main__":
    import shutil

    print("hosted-pi-agent starting", flush=True)
    print("python", os.sys.executable, flush=True)
    print("node", shutil.which("node"), flush=True)
    print("agent_js", AGENT_JS.exists(), AGENT_JS, flush=True)
    app.run()
