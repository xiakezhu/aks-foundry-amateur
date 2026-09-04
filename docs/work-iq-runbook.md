# Work IQ (toolbox + OBO) — Phase 0 and Phase 1

Full standalone summary (including the work-account blocker): [`docs/WORK-IQ.md`](WORK-IQ.md). After the toolbox exists and Credits are on, testers and UAT users invoke Work IQ through the toolbox MCP URL: [`docs/work-iq-invoke.md`](work-iq-invoke.md) ([tester vs UAT](work-iq-invoke.md#6-test-work-iq-mcp-oauth2--tester-vs-uat-user)).

Operator runbook. Merging this file does **not** provision Work IQ. Do not commit tenant IDs, client secrets, subscription IDs, or connection JSON with real resource IDs.

**Locked design**

- Keep **`pi-example`**. Add **`workiq-reader`** later (not this phase).
- Consume: hosted agent → `FoundryToolbox` → toolbox MCP. Agent code does **not** call Work IQ itself.
- Work IQ protocol: **MCP** `https://workiq.svc.cloud.microsoft/mcp` (not A2A). A2A is fallback only.
- Billing: **Copilot Credits** (Work IQ API). Do not attach connector Mail/Calendar tools (those can need Copilot seats).
- Invoke `workiq-reader` as a **signed-in user** (token audience `https://ai.azure.com`). The AKS UAMI is not a mailbox user.
- PIM is **not** required. Consent is a one-time privileged-role operation.

This is **not** Foundry IQ / Azure AI Search MCP (`docs/web-kb-mcp-resources.md`). Official MCP (Credits) vs connector (Copilot-seat) comparison: [`docs/work-iq-mcp-vs-connector.md`](work-iq-mcp-vs-connector.md).

---

## Roles

| Job | Who |
|---|---|
| Enable Copilot Credits | Billing / M365 admin |
| Work IQ SP + admin consent | Standing Global Admin, Privileged Role Administrator, or Cloud Application Administrator |
| Foundry connection + toolbox | Foundry Project Manager on the project |
| Prove `tools/list` / `fetch` as user | Test user with Foundry User + real M365 mail |

---

## Phase 0 — Tenant gates

Fill the table. Do not start Phase 1 until every required row is pass or explicitly waived.

| # | Gate | How | Result (pass / fail / date) |
|---|---|---|---|
| 0.1 | Work IQ service principal exists | Search Entra **Enterprise applications** for Work IQ, or `az ad sp show --id fdcc1f02-fc51-4226-8753-f668596af7f7`. If missing: `az ad sp create --id fdcc1f02-fc51-4226-8753-f668596af7f7` (201 or already-exists). | |
| 0.2 | Copilot Credits enabled | M365 admin: usage-based Copilot Credits for Work IQ API. A later 403 is “meter off”, not “buy Copilot seats”. | |
| 0.3 | BYO single-tenant Entra app | App registration, accounts in this org only. Copy application (client) ID and directory (tenant) ID. | |
| 0.4 | Delegated `WorkIQAgent.Ask` + admin consent | App → API permissions → APIs my organization uses → **Work IQ** (`fdcc1f02-…`) → delegated **WorkIQAgent.Ask** → **Grant admin consent**. If Work IQ is not in the picker, 0.1 failed. | |
| 0.5 | Client secret | Certificates & secrets → New. Store in Key Vault or a password manager. **Not git.** Shown once. | |
| 0.6 | Test user | Same Entra tenant as the Foundry project. Real mail/calendar. **Foundry User** on the Foundry account/project. | |
| 0.7 | Data-boundary | Work IQ may process data outside the Azure compliance boundary. Compliance sign-off or stop. | |
| 0.8 | Phase A write-deny | Mutation policy stays **off**. After Phase 1, as the test user: a write (`do_action /me/sendMail` or ask “send an email…”) must **not** send. Record the error. | |

**OAuth scopes** (two strings, never one comma-concatenated token):

- `api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask`
- `offline_access`

Portal UIs may show them comma-separated. CLI `--scopes` is **space**-separated.

Exit: this table filled. Phase 0 is human work, not CI.

---

## Phase 1 — Connection `workiq-mcp` + toolbox `work-iq-toolbox`

Laptop + portal / Azure CLI. `azd` is optional. Prefer portal for the OAuth connection (Foundry emits a redirect URI).

Placeholders: `<foundry-account>`, `<foundry-project>`, `<tenant-id>`.

Project endpoint:

```text
https://<foundry-account>.services.ai.azure.com/api/projects/<foundry-project>
```

Caller token for Foundry APIs:

```bash
az login
TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)
```

The operator needs **Foundry Project Manager** to create the connection.

### 1.1 Portal: connect Work IQ MCP

1. Open the Foundry project → **Tools** (or **Connect a tool**).
2. Catalog: **Work IQ MCP** (not Outlook Mail / Calendar connectors, not Web KB / Search MCP).
3. Target (confirm, do not use the old `agent365.svc` URL unless the catalog still requires it):

   ```text
   https://workiq.svc.cloud.microsoft/mcp
   ```

4. OAuth:

   | Field | Value |
   |---|---|
   | Client ID | BYO app (0.3) |
   | Client secret | 0.5 |
   | Authorization URL | `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/authorize` |
   | Token URL / Refresh URL | `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token` |
   | Scopes | `WorkIQAgent.Ask` and `offline_access` |

5. Save. Copy the **OAuth redirect URI** Foundry shows.
6. Entra app → Authentication → Add a platform → **Web** → paste that URI.
7. Name the connection **`workiq-mcp`** if the UI lets you. Record the connection name and the full ARM-style `project_connection_id` (project → Connections).

Connection fields cannot be edited after create. Wrong values → delete and recreate.

### 1.2 Create toolbox `work-iq-toolbox`

Do **not** use `WorkIQPreviewToolboxTool` / A2A as the default. Point the toolbox at the MCP connection.

Replace `<project-connection-id>` with the full id from 1.1 (looks like `/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>/connections/workiq-mcp`).

```bash
curl -sS -X POST \
  "https://<foundry-account>.services.ai.azure.com/api/projects/<foundry-project>/toolboxes/work-iq-toolbox/versions?api-version=v1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "description": "Work IQ API MCP (OBO). Phase A read/ask only.",
    "tools": [
      {
        "type": "mcp",
        "server_label": "workiq",
        "server_url": "https://workiq.svc.cloud.microsoft/mcp",
        "require_approval": "never",
        "project_connection_id": "<project-connection-id>"
      }
    ]
  }'
```

`require_approval: never` is **not** HITL. The toolbox MCP endpoint does not block writes. Phase A write safety is tenant mutation policy + later agent allow-list.

Promote this version to **default** if the UI/API has `default_version`. Hosted agents will use the unversioned consumer URL:

```text
https://<foundry-account>.services.ai.azure.com/api/projects/<foundry-project>/toolboxes/work-iq-toolbox/mcp?api-version=v1
```

Optional Python (same payload; `azure-ai-projects>=2.3.0` as in `app/requirements.txt`):

```python
import os
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPToolboxTool

endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
conn_id = os.environ["WORKIQ_MCP_CONNECTION_ID"]

with DefaultAzureCredential() as cred, AIProjectClient(endpoint=endpoint, credential=cred) as project:
    toolbox = project.toolboxes.create_version(
        name="work-iq-toolbox",
        description="Work IQ API MCP (OBO). Phase A read/ask only.",
        tools=[
            MCPToolboxTool(
                server_label="workiq",
                server_url="https://workiq.svc.cloud.microsoft/mcp",
                require_approval="never",
                project_connection_id=conn_id,
            )
        ],
    )
    print(toolbox.name, getattr(toolbox, "version", None))
```

If `MCPToolboxTool` rejects `require_approval` or `server_url`, use the REST body above. Do not invent a homegrown MCP client in `hosted-pi-agent`.

### 1.3 Prove toolbox `tools/list` (user token, not UAMI)

```bash
az login
TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)

curl -sS -X POST \
  "https://<foundry-account>.services.ai.azure.com/api/projects/<foundry-project>/toolboxes/work-iq-toolbox/mcp?api-version=v1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

**Pass:** JSON-RPC result with Work IQ tools. Expect MCP verbs such as `fetch`, `ask`, `get_schema` (names may vary slightly).

Empty list / 403: Foundry User on the caller; connection name; toolbox has a default version.

This proves **agent-to-toolbox** auth. It does **not** by itself prove user mailbox OBO. Full tester curl (including official `entityUrls` and hosted-agent invoke): [`work-iq-invoke.md`](work-iq-invoke.md).

### 1.4 Prove user passthrough (`fetch` as the signed-in user)

Still with **token A** (`https://ai.azure.com`), call `tools/call` for `fetch` on `/me/messages` (adjust tool/argument names to match `tools/list`; official MCP uses `entityUrls`).

First call may return a **consent URL** (AADSTS65001). Complete it in the browser as the test user, then retry.

| Result | Meaning | Next |
|---|---|---|
| Mail for **that** user | MCP + OBO works | Record pass. Phase 1 done. |
| 401/403, empty, or another user’s data | Passthrough failed | **Do not** put a Work IQ token in a hosted agent. Fallback: A2A connection + `WorkIQPreviewToolboxTool` (below). |
| Write verbs in `tools/list` (`do_action`, `create_entity`, …) | Expected on unified MCP | Keep tenant mutation policy **off**. Do not send those tools to a model until Phase B HITL. Record 0.8 write-deny. |

### 1.5 Fallback only — A2A

Use only if 1.4 fails. Create connection `workiq-a2a`, target `https://workiq.svc.cloud.microsoft/a2a/`, same OAuth app. Toolbox tool type `work_iq_preview` / `WorkIQPreviewToolboxTool`. Then `ask` “what meetings do I have today?” as the user. Do not mix A2A and MCP in the same default toolbox version.

---

## Objects created in these phases

| Object | Name | Created in |
|---|---|---|
| Work IQ SP | `fdcc1f02-fc51-4226-8753-f668596af7f7` | 0.1 if missing |
| Entra app + secret + consent | org-chosen | 0.3–0.5 |
| Project connection | `workiq-mcp` | 1.1 |
| Toolbox | `work-iq-toolbox` | 1.2 |
| Hosted agent `workiq-reader` | — | **Not this phase** |
| `pi-example` | — | Unchanged |

---

## Local dry-run (no Azure)

From the repo root:

```bash
python3 -m pip install -q httpx
cd hosted-workiq
python3 test_toolbox_mcp.py
python3 dry_run.py --mock
```

This does **not** call Work IQ. It checks Phase A filtering (`do_action` / `create_entity` hidden; `fetch` / `ask` kept) against a fake MCP server.

Live toolbox (after Phase 1, on a laptop with `az login` and Foundry User):

```bash
export FOUNDRY_PROJECT_ENDPOINT="https://<foundry-account>.services.ai.azure.com/api/projects/<foundry-project>"
export TOOLBOX_NAME=work-iq-toolbox
python3 dry_run.py --live
```

`workiq-reader` is still not deployed. `hosted-workiq/main.py` is a Responses host that returns the same dry-run JSON (DeepSeek tool loop not wired).

---

## Explicitly later (not Phase 0/1)

- Hosted image `hosted-workiq` and agent `workiq-reader`
- DeepSeek Agent Framework tool-calling proof (Phase 2a)
- User-token invoke of `workiq-reader`
- Write actions / HITL
- Changing `pi-example` to call the toolbox
- Agent 365 BYO MCP, Search MCP, GLM as the Work IQ model

---

## Rollback

1. Delete toolbox `work-iq-toolbox` (or its versions).
2. Delete connection `workiq-mcp`.
3. Rotate/delete the Entra client secret; optionally revoke admin consent.
4. Leave `pi-example`, ACR Pi image, and `foundry-control` in place.
