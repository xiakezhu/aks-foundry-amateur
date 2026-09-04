# Invoke Work IQ MCP from a Foundry hosted agent

Assume the Work IQ **API MCP** connection is already on a toolbox, and the **Copilot Credits** (Work IQ API) billing plan is enabled for testers. This note is the consume path only. Setup: [runbook](work-iq-runbook.md). Plan: [WORK-IQ.md](WORK-IQ.md). Credits vs connectors: [work-iq-mcp-vs-connector.md](work-iq-mcp-vs-connector.md).

Do **not** commit tenant IDs, subscription IDs, client secrets, app IDs of the BYO Entra app, connection `redirectUrl` GUIDs, or live mailbox payloads.

---

## What you invoke

The hosted agent does **not** open `https://workiq.svc.cloud.microsoft/mcp`. It calls the **toolbox MCP consumer URL**. The toolbox performs OBO (`WorkIQAgent.Ask`) to Work IQ.

```text
tester (work/school account)
  -- token A (aud=https://ai.azure.com) -->
      {project_endpoint}/toolboxes/{toolbox-name}/mcp
          -- OBO, WorkIQAgent.Ask -->
              https://workiq.svc.cloud.microsoft/mcp
                  --> that tester's Microsoft 365 data
```

The hosted **container never holds** a Work IQ mailbox token. The AKS UAMI (`foundry-control`) is **not** a mailbox user.

Placeholders:

```text
{project_endpoint}  = https://<foundry-account>.services.ai.azure.com/api/projects/<foundry-project>
{toolbox-name}      = work-iq-toolbox   (or your toolbox)
{agent-name}        = workiq-reader     (when deployed)
```

Unversioned consumer URL (follows `default_version`):

```text
{project_endpoint}/toolboxes/{toolbox-name}/mcp?api-version=v1
```

Use `.../toolboxes/{toolbox-name}/versions/{version}/mcp?api-version=v1` only to test a non-default version.

---

## Two tokens (do not mix)

| Token | Audience | Who | Used for |
|---|---|---|---|
| **A** | `https://ai.azure.com` | Tester `az login` / Foundry playground | Invoke Foundry, toolbox MCP, hosted Responses |
| **B** | `api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask` | Toolbox **OBO**, never in the container | Call Work IQ MCP as the user |

Do not OBO token A inside `hosted-workiq` or `pi-example`. Do not put token B in agent env vars.

---

## Tester identity

Credits + toolbox are not enough. The caller must be a **Member work/school account** in *this* Entra tenant, with Exchange / Microsoft 365 mail and **Foundry User** on the Foundry project.

A personal Microsoft account (`…#EXT#@….onmicrosoft.com`) can be an Azure subscription admin and still **cannot** complete APIM consent or fetch mailbox data. Do not add that MSA as a guest in tenant **Microsoft Services**.

```bash
az login   # work/school tester, not MSA, not the AKS UAMI
# Switch directory to <tenant>.onmicrosoft.com first.
TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)
```

---

## 1. Prove MCP through the toolbox (no hosted agent required)

### 1.1 `tools/list`

```bash
curl -sS -X POST \
  "{project_endpoint}/toolboxes/{toolbox-name}/mcp?api-version=v1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

**Pass:** JSON-RPC result with Work IQ verbs (`fetch`, `ask`, `get_schema`, …). Names may be prefixed with the toolbox `server_label` (for example `workiq_fetch`). Call the **exact** name from `tools/list`.

Empty list / 403: caller lacks Foundry User, toolbox has no default version, or the toolbox still points at an ARM MCP connection whose `redirectUrl` is null. Prefer a toolbox version whose `project_connection_id` is the **portal** MCP connection (has a real APIM `redirectUrl`).

This proves **agent-to-toolbox** auth. It does **not** by itself prove mailbox OBO.

### 1.2 Consent (first `tools/call`)

The first `tools/call` often returns **CONSENT_REQUIRED** (APIM login URL / AADSTS65001). Open that URL in the browser as the **same tester**, complete consent in **this tenant**, then retry.

Do **not** complete consent as an MSA against Microsoft Services. Do **not** use the `logic-apis-<region>.consent.azure-apim.net` login URL with a personal Microsoft account.

### 1.3 `fetch` (that tester’s mail)

Official MCP argument is `entityUrls` (array of relative Graph-style paths). Confirm against `tools/list`.

```bash
curl -sS -X POST \
  "{project_endpoint}/toolboxes/{toolbox-name}/mcp?api-version=v1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "jsonrpc":"2.0","id":2,"method":"tools/call",
    "params":{
      "name":"fetch",
      "arguments":{
        "entityUrls":["/me/messages?$top=5&$select=id,subject,from,receivedDateTime"]
      }
    }
  }'
```

If `tools/list` shows `workiq_fetch`, use that name.

| Result | Meaning | Next |
|---|---|---|
| Mail for **that** tester | MCP + OBO works | Record pass. Safe to wire the hosted agent. |
| 401/403, empty, or another user’s data | Passthrough failed | **Do not** put a Work IQ token in the hosted agent. |
| HTTP 400 on arguments | Schema mismatch | Use `entityUrls`, not a single `path`, unless `tools/list` says otherwise. |

Repo dry-run (`hosted-workiq/dry_run.py --live`) currently calls `fetch` with `{"path":"/me/messages"}`. If live `fetch` returns 400, use the `entityUrls` curl above.

### 1.4 `ask` (Copilot over work data)

```bash
curl -sS -X POST \
  "{project_endpoint}/toolboxes/{toolbox-name}/mcp?api-version=v1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "jsonrpc":"2.0","id":3,"method":"tools/call",
    "params":{
      "name":"ask",
      "arguments":{"query":"What meetings do I have today?"}
    }
  }'
```

Confirm argument names against `tools/list` (`query` vs `question` vs `message`). `ask` is slower than `fetch` (Work IQ synthesis plus the hosted model).

### 1.5 Local helper

```bash
export FOUNDRY_PROJECT_ENDPOINT="{project_endpoint}"
export TOOLBOX_NAME=work-iq-toolbox
python3 hosted-workiq/dry_run.py --live
```

Requires `az login` as the work tester. Mock mode (`--mock`) does **not** call Azure.

---

## 2. Invoke from a hosted agent

The agent is an MCP **client of the toolbox**, not of Work IQ.

| Env | Value |
|---|---|
| `TOOLBOX_NAME` | `work-iq-toolbox` |
| or `TOOLBOX_ENDPOINT` | unversioned `{project_endpoint}/toolboxes/{toolbox-name}/mcp?api-version=v1` |
| `FOUNDRY_PROJECT_ENDPOINT` | Injected by the hosted runtime after deploy |

Official sample: `FoundryToolbox` (`agent-framework-foundry-hosting`). It authenticates with the **agent identity** (`https://ai.azure.com/.default`) and forwards `x-agent-foundry-call-id`. This repo’s `hosted-workiq/toolbox_mcp.py` only does the agent-identity bearer today; it does **not** forward the call ID, so it is not production user-passthrough.

**Who invokes the agent:** the tester, with token A. The container does **not** receive that token. See [Agent code and token A](#5-agent-code-and-token-a-in-the-container).

```bash
curl -sS -X POST \
  "{project_endpoint}/agents/{agent-name}/endpoint/protocols/openai/responses?api-version=v1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Foundry-Features: HostedAgents=V1Preview" \
  -d '{"input":"What is in my inbox today?"}'
```

Also valid: Foundry playground as that tester, or `azd ai agent invoke "…"`.

**Do not** use `foundry-control` `POST /agents/{name}/invoke` for mailbox proof. That path uses the AKS UAMI. UAMI invoke must **not** return mail. Keep `pi-example` off this toolbox.

Until `workiq-reader` is deployed and the DeepSeek tool loop is wired, prove Work IQ with **section 1** (toolbox JSON-RPC), not natural-language hosted invoke. `hosted-workiq/main.py` currently lists Phase A tools only.

---

## 3. What billing does and does not do

Enabling Copilot Credits for testers unblocks **403 “meter off”**. It does not:

- replace a work/school mailbox
- replace APIM / Entra consent
- let the UAMI act as the user
- change the invoke URL (still toolbox `/mcp`, not Work IQ `/mcp`)

A 403 after Credits are on is usually consent, wrong audience, or mutation policy — not “buy Copilot seats.” Do not attach Outlook Mail/Calendar **connectors**; those are a different SKU.

---

## 4. MCP vs A2A (do not mix)

| Toolbox tool | Target | How you invoke |
|---|---|---|
| `type: mcp` (this plan) | `https://workiq.svc.cloud.microsoft/mcp` | `tools/call` `fetch` / `ask` / … (10 verbs) |
| `type: work_iq_preview` (fallback) | `https://workiq.svc.cloud.microsoft/a2a/` | `{"message":{"parts":[{"type":"text","text":"…"}]}}` |

If the toolbox is `work_iq_preview`, `fetch` will not exist. Keep MCP and A2A in **separate** toolbox versions.

---

## 5. Agent code and token A in the container

The production hosted agent **never obtains the user’s token A**. Foundry’s gateway **drops `Authorization`** (and `Cookie`, `Host`, `x-forwarded-*`) before the request reaches your container. Homegrown OBO from token A inside `hosted-workiq` or `pi-example` is a [known dead end](https://github.com/Azure/azure-sdk-for-python/issues/46696).

### Three identities (do not mix)

| Who | What the code sees | Audience / header | Role |
|---|---|---|---|
| **End user** | Not in the container | Token A presented only on the **invoke** HTTP call to Foundry | Proves who is talking to the agent. Foundry stores that caller context server-side. |
| **Agent identity** | `DefaultAzureCredential` / IMDS in the sandbox | Bearer `https://ai.azure.com/.default` on toolbox MCP | Lets the **container** call the toolbox. This is **not** the user’s mailbox token. |
| **User at Work IQ** | Never in the container | Token B (`WorkIQAgent.Ask`) minted by **toolbox OBO** | Mail/calendar/files for **that** user. |

Glue: protocol **2.0.0** injects `x-agent-foundry-call-id` (opaque). Forward it **unchanged** on outbound toolbox / Storage / A2A calls. Foundry resolves the original user from that ID and runs the connection’s OAuth OBO. Also present: `x-agent-user-id` (partition key for your own per-user state; **do not** send it outbound as auth).

```text
User  -- token A -->  Foundry Responses (playground / SDK / Teams)
                         |
                         | gateway strips Authorization
                         | sets x-agent-foundry-call-id + x-agent-user-id
                         v
                    hosted container
                         |
                         | Bearer: agent MI (ai.azure.com)
                         | Header: x-agent-foundry-call-id  (forwarded)
                         v
                    toolbox /mcp
                         |
                         | OBO using call-id → token B
                         v
                    Work IQ MCP  (that user's M365)
```

Local `az login` + `dry_run.py --live` **is** token A, because your laptop talks to the toolbox **directly**. After deploy, the laptop talks to **the agent**; the container talks to the toolbox as the **agent identity**.

### Integrate in agent code (do not call Work IQ from Pi)

Keep **`pi-example`** as the DeepSeek smoke agent. Do not point it at Work IQ. Wire Work IQ in **`workiq-reader`** (or a copy of the Pi host), as an MCP **client of the toolbox**.

Preferred (Agent Framework hosted Responses):

```python
from azure.identity import DefaultAzureCredential
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient, FoundryToolbox

credential = DefaultAzureCredential()  # hosted MI in prod; az login locally

# Resolves TOOLBOX_ENDPOINT, or FOUNDRY_PROJECT_ENDPOINT + TOOLBOX_NAME.
# Auth: agent identity. Forwards x-agent-foundry-call-id from request context.
toolbox = FoundryToolbox(credential)

client = FoundryChatClient(
    project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
    model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],  # or your DeepSeek deployment
    credential=credential,
)

agent = Agent(
    client=client,
    instructions="Use Work IQ tools for this user's mail, calendar, files, and chats.",
    tools=toolbox,
)
```

`FoundryToolbox` is a wrapper over `MCPStreamableHTTPTool`. Grant the **hosted agent’s managed identity** **Foundry User** (or Agent Consumer) on the project. Do not put `WorkIQAgent.Ask`, client secrets, or mailbox tokens in `environment_variables`.

If you keep a Pi (Node) tool loop: the **Python Responses host** must be the toolbox client. Convert `tools/list` into Pi tools; on `execute`, call toolbox `tools/call` from Python. Do not have `agent.mjs` call `https://workiq.svc.cloud.microsoft/mcp`. Node would still only have the **agent** MI (IMDS), never token A.

DIY MCP (only if you cannot use `FoundryToolbox`) — every toolbox POST:

```python
from azure.ai.agentserver import get_request_context  # protocol 2.0.0
from azure.identity import DefaultAzureCredential

token = DefaultAzureCredential().get_token("https://ai.azure.com/.default").token
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
ctx = get_request_context()
if ctx and ctx.call_id:
    headers["x-agent-foundry-call-id"] = ctx.call_id  # opaque; never parse
```

Missing call-id → toolbox cannot resolve the user → empty mail, 401, or agent-identity data. `hosted-workiq/toolbox_mcp.py` does not set this header yet.

Hosted protocol: use **2.0.0** so `x-agent-foundry-call-id` exists. On 1.0.0 / local `azd ai agent run` the header is absent (your laptop identity is the user).

### How the user presents token A (outside the container)

| Channel | Token A | Mailbox OBO |
|---|---|---|
| Foundry playground | Signed-in work user | Yes, after APIM consent |
| `az login` + Responses curl / `azd ai agent invoke` | That CLI user | Yes, if work/school + Foundry User |
| Teams / M365 (user-invoked) | User token present; platform OBO | Yes |
| `foundry-control` `POST /agents/{name}/invoke` | AKS UAMI | **No** — UAMI is not a mailbox user |
| Timer / autonomous hosted run | None | **No** — Work IQ is delegated-only |

A middle-tier that invokes the agent with **its own** token is the middle-tier, not the employee. `x-ms-user-identity` multiplexes **session** user id; it is **not** the OAuth credential for toolbox `oauth2`. For per-user Work IQ from an app you own, have the **browser user** call the agent Responses endpoint with **their** token A (or use a Microsoft 365 channel). Do not try to stuff token A into `x-client-*` headers; the container must not hold it.

Consent (`CONSENT_REQUIRED`) is handled **while the agent runs**, not at toolbox create. Return the consent URL to the signed-in user, complete it, retry the same call-id path.

---

## 6. Test Work IQ MCP (`oauth2`) — tester vs UAT user

Connection auth is **OAuth identity passthrough**. Admin consent on the BYO app does **not** skip the first-use URL. Consent is **per user × connection × project**: the tester’s completed consent does **not** cover a UAT user.

Shared gates (both roles):

- Member **work/school** account in this Entra tenant (not an MSA / `#EXT#` guest).
- Real Exchange / Microsoft 365 mail.
- **Foundry User** (or Agent Consumer) on the Foundry project.
- Copilot **Credits** (Work IQ API) enabled for that identity — a tester-only billing plan does not cover a UAT user who is off the plan.
- Toolbox default version points at the **portal** MCP connection (`oauth2`, real `redirectUrl`).
- Entra admin consent already granted on `WorkIQAgent.Ask` + `offline_access`.

Do not paste mailbox bodies, consent URLs with codes, or tokens into git or tickets.

### Tester (engineering)

**Goal:** prove toolbox `oauth2` passthrough and (when deployed) hosted invoke as **this** tester.

1. Sign in as the tester work account. Switch directory to `<tenant>.onmicrosoft.com`.

   ```bash
   az login
   TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)
   ```

2. `tools/list` on `{project_endpoint}/toolboxes/{toolbox-name}/mcp?api-version=v1` (section 1.1).  
   **Pass:** Work IQ verbs (`fetch`, `ask`, …).

3. `tools/call` `fetch` `/me/messages` (section 1.3). First call: **CONSENT_REQUIRED** + URL. Open it in the browser as **the same tester**, in this tenant. Retry.  
   **Pass:** **that tester’s** messages. Empty / 401 / another user’s mail = fail. Do not complete the URL as an MSA.

4. Optional: `ask` “What meetings do I have today?” (section 1.4).

5. Optional helper: `python3 hosted-workiq/dry_run.py --live` after the same `az login`.

6. When `{agent-name}` is deployed: Foundry playground or Responses curl as **the same tester** (section 2). First hosted Work IQ tool use may show the consent URL again if this user never bound this connection through the agent path — complete it as the tester, retry.  
   **Pass:** answer grounded in **the tester’s** mailbox.  
   **Fail:** `foundry-control` / UAMI invoke returning mail.

Record: date, toolbox name/version, connection name (`oauth2`), tester UPN (not in git), `tools/list` tool names, fetch pass/fail (no message bodies).

### UAT user (acceptance)

**Goal:** prove the hosted agent represents **that UAT user**, not the tester. Prefer playground, not `az` / curl.

1. Operator: grant the UAT user **Foundry User** (or Agent Consumer) on the project. Confirm Credits apply to them. Confirm they have mail in this tenant.

2. UAT user signs in to the Foundry project **as themselves** (work/school). Open `{agent-name}` in the playground (or the UAT app that calls Responses with **their** token A).

3. Prompt that needs mail, for example: “What is in my inbox today?” / “What meetings do I have today?”

4. First Work IQ tool use: agent returns **CONSENT_REQUIRED** and a URL. UAT user opens it, signs in as **themselves**, finishes, then **sends the prompt again** (same conversation / `previous_response_id` if the client supports it).  
   Tester consent does not count. Do not send the tester the UAT consent URL to “click for them” under the tester account.

5. **Pass:** content from **the UAT user’s** mailbox/calendar only.  
   **Fail:** tester’s mail, empty, 403 meter, or MSA / Microsoft Services login error.

6. Optional isolation: tester runs the same prompt in their own session — must see **tester** mail, not UAT mail.

UAT users should not need `az login` or toolbox JSON-RPC. If the hosted agent is not deployed yet, UAT cannot sign off user-passthrough; only the tester toolbox curl in section 1 is available.

### Isolation checks

| Check | Tester | UAT user |
|---|---|---|
| Identity | Work/school tester | Different work/school UAT account |
| First `oauth2` bind | Consent URL once as tester | Consent URL once as UAT user (separate) |
| `fetch` / “my inbox” | Tester’s mail | UAT user’s mail |
| Other person’s mail | Fail | Fail |
| `foundry-control` UAMI invoke | Must **not** return mail | Must **not** return mail |
| MSA / `#EXT#` | Fail | Fail |

### Order

**Tester**

1. Work-account `az login` (Foundry User + real mail + Credits).
2. `tools/list` on the toolbox consumer URL with token A.
3. Complete APIM consent as that same tester.
4. `tools/call` `fetch` `/me/messages` — pass = **that tester’s** mail.
5. Then invoke `{agent-name}` as the same tester (playground or Responses). Never UAMI.

**UAT user**

1. Operator grants Foundry User + Credits.
2. UAT user opens playground as themselves.
3. Prompt that needs M365; complete **their** consent URL; retry.
4. Pass = **that UAT user’s** mail, and a second user still sees only their own.
