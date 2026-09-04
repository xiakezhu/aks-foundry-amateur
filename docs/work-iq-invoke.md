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

Official sample: `FoundryToolbox` (`agent-framework-foundry-hosting`) with scope `https://ai.azure.com/.default`, forwarding the per-request call ID. This repo’s `hosted-workiq` uses `ToolboxMcpClient` the same way.

**Who invokes the agent:** the tester, with token A.

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

## Order for testers

1. Work-account `az login` (Foundry User + real mail).
2. `tools/list` on the toolbox consumer URL with token A.
3. Complete APIM consent as that same user in this tenant.
4. `tools/call` `fetch` `/me/messages` — pass = **that** user’s mail.
5. Only then invoke `{agent-name}` with the same token A (playground or Responses). Never UAMI.
