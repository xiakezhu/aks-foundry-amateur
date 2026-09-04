# Work IQ on this Foundry POC

Standalone summary of the plan, what was implemented, and what is blocked until a **work/school Microsoft 365 account** exists. No work account is available today.

Related notes (optional): [runbook](work-iq-runbook.md), [invoke Work IQ MCP](work-iq-invoke.md), [MCP vs connector](work-iq-mcp-vs-connector.md), [Search/Web KB is not Work IQ](web-kb-mcp-resources.md).

---

## Goal

Give a **Foundry hosted agent** (`workiq-reader`) Microsoft 365 context (mail, calendar, files, chats) for a **signed-in user**.

Keep **`pi-example`** as the DeepSeek smoke agent. Do not point it at Work IQ.

```text
You (work account)  --token A-->  invoke workiq-reader
                                      |
                                      | FoundryToolbox
                                      v
                                 toolbox work-iq-toolbox
                                      |
                                      | OBO (WorkIQAgent.Ask)
                                      v
                          https://workiq.svc.cloud.microsoft/mcp
                                      |
                                      v
                          that user's Microsoft 365 data
```

The hosted **container never holds** a Work IQ mailbox token. `foundry-control` UAMI is **not** a mailbox user.

---

## Locked choices

| Topic | Decision |
|---|---|
| Consume | Official **toolbox + OBO**. Agent does **not** call Work IQ MCP itself. |
| Protocol | Work IQ **API MCP** `https://workiq.svc.cloud.microsoft/mcp` (10 verbs). **A2A** `/a2a/` is fallback only. |
| Billing | **Copilot Credits** (usage-based). Not per-user Copilot seats. Do not attach Outlook Mail/Calendar **connectors**. |
| Model | DeepSeek as used by `pi-example`. Not GLM. |
| Writes | Phase A = read/`ask` only. Writes later with runtime HITL. Toolbox `require_approval` is **not** HITL. |
| PIM | Not required. Consent is a one-time privileged role (this tenant: Global Admin). |
| Agent 365 BYO MCP | Out of scope. |
| Search / Foundry IQ MCP | Different product. Do not reuse. |

---

## Why a work account is required

Work IQ is **delegated-only** and reads **that user's** Exchange / M365 data.

The Azure login in this POC is a **personal Microsoft account (MSA)** federated into the directory:

```text
<redacted-msa>#EXT#@<redacted-tenant>.onmicrosoft.com
```

That identity:

- Can be Global Admin on **this Azure subscription**
- Is **not** a Microsoft 365 work/school mailbox user
- Cannot complete Logic Apps / APIM consent (Microsoft’s Logic Apps / APIM app in tenant **Microsoft Services**)

Error you hit:

> Selected user account does not exist in tenant 'Microsoft Services' and cannot access the application '82a20610-…'

**Do not** add the MSA as a guest in Microsoft Services. That tenant is Microsoft’s, not yours.

**Do:** use (or create) a **Member work/school account** in *your* Entra tenant that has **Exchange Online / Microsoft 365** mail, then sign in with **that** account when Foundry/Work IQ asks for consent. Switch directory to `<redacted-tenant>.onmicrosoft.com` first.

Until then: tenant objects can exist, but **live mailbox `fetch` cannot succeed**.

---

## Two tokens (do not mix)

| Token | Audience | Who | Used for |
|---|---|---|---|
| **A** | `https://ai.azure.com` | `az login` / Foundry playground | Invoke Foundry / toolbox MCP URL |
| **B** | `api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask` | Toolbox **OBO**, never in the container | Call Work IQ MCP as the user |

Do not OBO token A inside `hosted-workiq` or `pi-example`.

---

## Resources

### Already in the POC (unchanged)

| Resource | Notes |
|---|---|
| Foundry account/project `<foundry-project>` | `<resource-group>` |
| AKS `foundry-control`, UAMI, ACR, App Insights | Control plane |
| Hosted agent `pi-example` / image `hosted-pi-agent` | DeepSeek via `OPENAI_*` |
| Search / Web KB MCP connections | **Not** Work IQ |

### Created for Work IQ (this effort)

| Resource | Name / id | Status |
|---|---|---|
| Work IQ enterprise app (Microsoft) | App ID `fdcc1f02-fc51-4226-8753-f668596af7f7` | Created (`az ad sp create`) |
| BYO Entra app | `foundry-workiq-poc` · app ID `<app-id>` | Created, single-tenant |
| Admin consent | Delegated `WorkIQAgent.Ask` + `offline_access` | Granted tenant-wide on the BYO app |
| Client secret | On `foundry-workiq-poc` | Local scratch only, **not in git** |
| Project connection | `workiq-mcp` → `/mcp/` · ARM `RemoteTool` · `workiqmcp` | **`redirectUrl` is null.** Do not use for Entra whitelist. |
| Project connection | **`workiq-mcp-portal`** → `/mcp/` · portal `RemoteTool` · `custom_MCP` | **Has `redirectUrl`.** Prefer this for the MCP lock. |
| Project connection | **`WorkIQ`** → `/a2a/` · portal `RemoteA2A` · `work_iq_preview` | A2A fallback. Different `redirectUrl`. |
| Extra connection (experiment) | `workiq-mcp-user` (UserEntraToken) | Wrong audience for Work IQ; ignore |
| Toolbox | `work-iq-toolbox` v1 still points at ARM **`workiq-mcp`**. Point a **new version** at **`workiq-mcp-portal`**. | v2 was UserEntraToken experiment |
| Hosted agent `workiq-reader` | — | **Not deployed** |

### Verified connections (2026-08-26)

ARM GET `…/projects/<foundry-project>/connections?api-version=2025-04-01-preview`.

| Field | `workiq-mcp` (ARM) | **`workiq-mcp-portal`** (portal MCP) | `WorkIQ` (portal A2A) |
|---|---|---|---|
| `category` | `RemoteTool` | **`RemoteTool`** | `RemoteA2A` |
| `target` | `https://workiq.svc.cloud.microsoft/mcp` | **same `/mcp/`** | `https://workiq.svc.cloud.microsoft/a2a/` |
| `authType` | `OAuth2` | `OAuth2` | `OAuth2` |
| `group` | `GenericProtocol` | `GenericProtocol` | `AzureAI` |
| `connectorName` | `workiqmcp` | `<connection-id>-workiq-mcp-portal` | `<connection-id>-WorkIQ` |
| `metadata.type` | (ConnectorName only) | **`custom_MCP`** | `work_iq_preview` |
| Auth URLs / `scopes` | **null** | **Filled** (your tenant + `WorkIQAgent.Ask`) | Filled (same scopes) |
| **`redirectUrl`** | **`null`** | **`https://global.consent.azure-apim.net/redirect/<mcp-redirect-guid>`** | `https://global.consent.azure-apim.net/redirect/<a2a-redirect-guid>` |

Portal create is what allocates the APIM **callback**. ARM `workiq-mcp` never got one. **`workiq-mcp-portal` is MCP with a real redirect** — that is the missing piece from 2026-08-25. `WorkIQ` remains A2A (ask-peer), not 10 verbs.

### Entra Web redirect URI (end state)

Copy **`redirectUrl` from the connection the toolbox will use** onto **`foundry-workiq-poc`** → Authentication → **Web**. You can list **both** URIs if you keep A2A and MCP.

**For MCP (`workiq-mcp-portal`), copy the connection’s `redirectUrl`:**

```text
https://global.consent.azure-apim.net/redirect/<mcp-redirect-guid>
```

**For A2A (`WorkIQ`), copy that connection’s `redirectUrl` (different GUID):**

```text
https://global.consent.azure-apim.net/redirect/<a2a-redirect-guid>
```

- Callback after login, not authorize/token URLs, not `logic-apis-….consent.azure-apim.net/login?data=…`.
- Path GUID is **per connection**. Do not put the A2A URI on MCP or reuse after recreate.
- Foundry **shows** it; Entra **must list** it. Both sides.
- Leave Entra empty only for connections whose `redirectUrl` is still null (`workiq-mcp`).

### Repo code

| Path | Role |
|---|---|
| `docs/work-iq-runbook.md` | Phase 0–1 operator steps |
| `docs/work-iq-invoke.md` | Tester invoke: toolbox MCP then hosted agent |
| `docs/work-iq-mcp-vs-connector.md` | Credits vs connector SKU |
| `hosted-workiq/` | Toolbox MCP JSON-RPC client, Phase A allow-list, mock dry-run |
| `k8s/build-hosted-workiq-job.yaml` | Kaniko placeholder (ACR tokens unset) |

---

## Steps (end to end)

### A. Tenant (needs Global Admin — done for SP/app/consent)

1. `az ad sp create --id fdcc1f02-fc51-4226-8753-f668596af7f7` if Work IQ SP is missing. **Done.**
2. BYO app `foundry-workiq-poc`, delegated `WorkIQAgent.Ask`, admin consent, client secret. **Done.**
3. Confirm **Copilot Credits** are enabled (billing admin). **Not verified here.**
4. **Work/school test user** with real mail + Foundry User. **Missing — blocker.**

### B. Foundry connection + toolbox (done, consent incomplete)

1. ARM `workiq-mcp` (`/mcp/`). **`redirectUrl` null.** Keep only as a failed experiment.
2. Portal **`WorkIQ`** (`/a2a/`). Has redirect. A2A fallback.
3. Portal **`workiq-mcp-portal`** (`/mcp/`, `custom_MCP`). **Has redirect.** **Prefer this.** Add its URI on Entra **Web**. Create a **new toolbox version** whose `project_connection_id` is **`workiq-mcp-portal`**, then set it as default (v1 still uses ARM `workiq-mcp`).
4. As a **work account**, `tools/list` then `fetch /me/messages` on that toolbox version. Not an MSA against Microsoft Services.
5. Pass = that user’s mail. Then deploy `workiq-reader` against `TOOLBOX_NAME=work-iq-toolbox`.

Pinned admin-consent URL for **your** app **in your tenant** (not Microsoft Services):

```text
https://login.microsoftonline.com/<tenant-id>/adminconsent?client_id=<app-id>
```

Do **not** use the `logic-apis-<region>.consent.azure-apim.net` URL with a personal Microsoft account.

### C. Local dry-run (done, no Azure mailbox)

```bash
cd hosted-workiq
python3 -m pip install -q httpx
python3 test_toolbox_mcp.py    # 4 tests
python3 dry_run.py --mock      # hides do_action/create_entity; calls fetch
```

Live (after work-account consent):

```bash
export FOUNDRY_PROJECT_ENDPOINT="https://<foundry-account>.services.ai.azure.com/api/projects/<foundry-project>"
export TOOLBOX_NAME=work-iq-toolbox
python3 hosted-workiq/dry_run.py --live
```

### D. Not started (after live `fetch` works)

1. Phase 2a: hosted Agent Framework image that **tool-calls DeepSeek** (trivial local tool). `pi-example` success does not skip this.
2. Wire DeepSeek into `hosted-workiq` + `FoundryToolbox` (or keep the JSON-RPC client if it already lists the toolbox).
3. Kaniko build `hosted-workiq`, `POST /agents` name **`workiq-reader`**, `TOOLBOX_NAME=work-iq-toolbox`, `cpu=2` / `memory=4Gi`. No `OPENAI_API_KEY` as Work IQ auth.
4. Invoke `workiq-reader` with **token A** (`az login` as the **work** user). UAMI invoke must **not** return mail.
5. Phase B: runtime HITL, then mutation policy, then allow-list `do_action` / `create_entity`.

---

## Official MCP vs connectors (short)

| | Work IQ **API MCP** (this plan) | M365 **connectors** (Mail/Calendar MCP servers) |
|---|---|---|
| Billing | Copilot **Credits** | Often **Copilot license per user** |
| Tools | 10 verbs + paths | Many named actions per app |
| Auth | `WorkIQAgent.Ask` + toolbox OBO | Per-server consent; admin allow/block |
| UX | Foundry hosted agent | Copilot Studio / Teams |
| Latency | Hosted cold start + OBO; seconds when warm | No sandbox pull in Studio |

Full table: [work-iq-mcp-vs-connector.md](work-iq-mcp-vs-connector.md).

---

## Current status

| Item | State |
|---|---|
| Plan locked (toolbox + MCP + Credits + `workiq-reader`) | Yes |
| Entra SP + BYO app + admin consent | Yes |
| Foundry `workiq-mcp-portal` (MCP + `redirectUrl`) | **Yes (portal).** Entra Web URI not added yet; toolbox v1 still on ARM `workiq-mcp`. |
| Mock dry-run | Pass |
| Live `tools/list` / mailbox `fetch` | **Blocked: no work/school M365 account** |
| `workiq-reader` deployed | No |
| DeepSeek tool loop in `hosted-workiq` | No |

**Resume when:** a Member work/school user with Exchange mail exists in this tenant, Credits are on, and consent is completed **in this tenant** (not Microsoft Services). Then rerun live `tools/list` and `--live` dry-run.
