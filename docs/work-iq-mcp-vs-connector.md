# Work IQ: official MCP (API) vs connector path

Comparison for this Foundry POC. Locked consume path is **toolbox + OBO**, not agent-code MCP and not `pi-example`.

| Term in this note | Meaning |
|---|---|
| **Official MCP (Work IQ API)** | Remote MCP `https://workiq.svc.cloud.microsoft/mcp` (and the same API family as A2A `/a2a/` and REST). Billed as **Copilot Credits**. In Foundry: project connection + toolbox; hosted agent uses `FoundryToolbox`. |
| **Connector path** | Per-workload Microsoft 365 MCP / Power Platform connectors (Outlook Mail, Calendar, Teams, SharePoint, OneDrive, Word, User, Copilot Chat, and Agent 365 catalog servers). Foundry documents these as **connector-backed** tools. Often **per-user Copilot / connector license**. |

They are easy to confuse because both show up as “Work IQ” and both speak MCP. They are **different products, meters, and tool surfaces**.

This is **not** Azure AI Search / Foundry IQ Web KB MCP (`docs/web-kb-mcp-resources.md`).

Sources (retrieved 2026-08-20): [Work IQ MCP overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/overview), [Work IQ API overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/api-overview), [Connect Foundry agents to Work IQ](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/work-iq), [Work IQ MCP Foundry quickstart](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/quickstart/foundry), [Agent 365 tooling servers](https://learn.microsoft.com/en-us/microsoft-agent-365/tooling-servers-overview), [Manage tools for agents](https://learn.microsoft.com/en-us/microsoft-365/admin/manage/manage-tools-for-agent).

---

## 1. Billing

| | Official MCP (Work IQ API) | Connector path |
|---|---|---|
| Meter | **Copilot Credits** (usage-based / “utility”) | **Connector licensing**. A connector can require a **Microsoft 365 Copilot license per calling user** |
| Copilot seat | **Not** the default gate. A Copilot license does **not** make API calls free | Agent 365 catalog article: Copilot license required to use those Work IQ MCP **servers** |
| 403 meaning | Credits not enabled, or Work IQ API blocked | Missing seat, connector not allowed, or admin blocked the server |
| This POC | **Chosen.** Confirm Credits on. Do **not** attach Outlook Mail / Calendar **connectors** | Out of scope unless product explicitly wants Copilot-seat SKU |

**Gap.** Official MCP is pay-per-call (Credits) with no seat tax on the API itself. Connectors can be “free” for already-licensed Copilot users in Copilot Studio, but they **block** users without a seat. Mixing both in one toolbox can produce mixed 403s that look like auth bugs.

**This tenant:** connection `workiq-mcp` uses catalog API name `workiqmcp` (Logic Apps / APIM eastus). That is still the **Work IQ API MCP** connector used to *broker OAuth*, not the per-workload Mail/Calendar connector SKU. Treat Credits as the meter unless billing admin says otherwise.

---

## 2. Auth

| | Official MCP (Work IQ API) | Connector path |
|---|---|---|
| Subject | **Signed-in user only.** App-only is not supported | User or agentic user; still not “UAMI is the mailbox” |
| Permission | Delegated `WorkIQAgent.Ask` (admin consent). Includes **read and write** for that user | Per-server permissions on the Agent 365 / connector app; admin allow/block in M365 admin center |
| Foundry wiring | BYO Entra app + OAuth2 (or catalog `workiqmcp`) on a **project connection**; toolbox OBO. Hosted **container never holds** `WorkIQAgent.Ask` | Catalog connector connection; Copilot Studio “create connection”; or Foundry “Microsoft 365 Frontier” tools |
| Invoke | User token **A** `aud=https://ai.azure.com` on hosted Responses. Toolbox OBO → token **B** for Work IQ | User signs in to that connector; token stays in the connector runtime |
| UAMI / `pi-example` | Cannot be the Work IQ user | Same |
| Consent UX | First `tools/list` / `tools/call` can return **CONSENT_REQUIRED** (APIM login URL). Browser as the test user | Copilot Studio connection picker; admin-center server allow-list |
| Tenant policy | Path/method Rego-style policy; **mutations off by default** | Admin allow/block entire MCP servers org-wide |

**Gap.** Official MCP centralizes on one permission (`WorkIQAgent.Ask`) plus tenant mutation policy. Connectors split auth per workload (Mail vs Calendar vs Teams) and give IT a kill switch per server. Official MCP has a sharper first-run consent (APIM) and a harder Foundry-hosted OBO setup (BYO app, redirect URI, `ConnectorName`). Connectors are easier in Copilot Studio and worse for a custom hosted container.

Homegrown OBO from token A inside the hosted agent is a **known dead end** ([python#46696](https://github.com/Azure/azure-sdk-for-python/issues/46696), [.NET#59767](https://github.com/Azure/azure-sdk-for-net/issues/59767)). That is why this POC uses toolbox + OBO, not “Pi calls MCP with a mailbox token.”

---

## 3. User experience

| | Official MCP (Work IQ API) | Connector path |
|---|---|---|
| Who the user talks to | Foundry hosted agent `workiq-reader` (DeepSeek + toolbox), not Copilot Chat | Copilot Studio / M365 Copilot / Teams, or a Foundry prompt agent with catalog tools |
| First-time | Entra + APIM consent, then natural language | “Allow this connection” in Studio; may already be consented if they use Copilot |
| Prompt style | Model picks verbs (`fetch /me/messages`) or `ask "…"` | Model picks **Mail send**, **Calendar create**, etc. |
| HITL / approval | Toolbox `require_approval` is **not** enforced. Phase A hides write verbs; Phase B needs **runtime** HITL | Copilot Studio can prompt “Allow” per tool call; admin-center policy |
| Errors | Credits 403, consent URL, empty `tools/list`, wrong audience | “Server blocked”, missing Copilot license, connector offline |
| Operator | Portal/REST: connection `workiq-mcp`, toolbox `work-iq-toolbox` | M365 admin **Agents and Tools**; Studio **Add tool → MCP** |

**Gap.** Official MCP is a **pro-code Foundry** experience: extra hops, extra consent, full control of allow-list. Connector path is **low-code / IT-governed**: faster for makers, worse if the goal is one hosted agent on AKS/`workiq-reader`. For end users, connector UX in Teams is more familiar; Foundry invoke (token A + playground/`az login`) is more “developer demo.”

---

## 4. Features surfaced

| | Official MCP (Work IQ API) | Connector path |
|---|---|---|
| Shape | **10 generic tools** + resource **paths**. New workloads add paths, not tools | **Many named tools** per server (Mail send/reply, Calendar accept, Teams post, …) |
| Verbs | `fetch`, `fetch_blob`, `create_entity`, `update_entity`, `delete_entity`, `do_action`, `call_function`, `ask`, `list_agents`, `get_schema`, `search_paths` | Server-specific (e.g. Work IQ Mail: create/update/delete/reply/search) |
| Discovery | `get_schema` / `search_paths` at runtime | Fixed catalog; IT allow-list |
| Copilot reasoning | First-class `ask` (semantic / Copilot over work data) | Separate Copilot Chat MCP server |
| Writes | Visible verbs; tenant policy blocks by default; easy to hide in Phase A | Visible named actions; blocked if that **server** is disallowed |
| A2A sibling | Same API family: `/a2a/` is “ask Copilot as a peer,” not 10 verbs | N/A |
| Governance surface | Work IQ API policy + Entra consent | M365 admin center + Defender hunting (Agent 365) |
| Hosted Foundry sample | `WorkIQPreviewToolboxTool` is **A2A** (best documented). MCP-in-toolbox is the same Credits API, thinner hosted sample | Chat Playground / prompt agent + catalog MCP, not this repo’s hosted container |

**Gap.** Official MCP is a **small, stable tool list** and a flexible path model — better for one DeepSeek loop and for Phase A write filtering. Connectors are **deterministic, auditable actions** (send this mail) and better when IT must allow Mail but block Teams. You lose `get_schema` / unified `ask` unless you also add Copilot Chat MCP. This POC wants MCP verbs **and** Foundry hosted OBO → official MCP, not Mail-connector MCP.

---

## 5. Latency

No public SLO for either preview surface. Order-of-magnitude only; measure on this tenant after consent.

| Stage | Official MCP (toolbox + OBO) | Connector path |
|---|---|---|
| Hosted cold start | Foundry sandbox 5–60 min idle scale-to-zero (default ~15 min). Dominates first demo | Copilot Studio / prompt agent: usually no container pull |
| Tool list | Toolbox → connection → Work IQ MCP `tools/list` (OBO). Extra hop vs calling `/mcp` yourself | Studio caches catalog tools; first connection slower |
| Read (`fetch`) | OBO + Work IQ + Graph. Budget **seconds**, not ms, after warm start | Graph via that connector; similar Graph latency, fewer Foundry hops |
| `ask` | Work IQ / Copilot synthesis: often **slower** than `fetch` (LLM on the Work IQ side **plus** DeepSeek) | N/A unless Copilot Chat MCP is attached |
| Writes | Same as fetch + policy + HITL pause | User “Allow” click often dominates |
| This POC | `pi-example` invoke already tens of seconds cold. Work IQ **adds** toolbox + OBO + MCP. Budget **5–30 s** per `ask`/`fetch` when warm; first call = consent | Not on the hosted-echo/Pi path |

**Gap.** Official MCP on a **hosted** agent pays sandbox cold start + toolbox + OBO. Connector path in Copilot Studio skips the container but cannot reuse `workiq-reader`. `ask` is the slow, high-value path; `fetch` should be the Phase A latency test. Do not quote milliseconds without a trace from this project.

---

## 6. Gap summary (what to optimize for)

| If you optimize for… | Prefer |
|---|---|
| Usage-based Credits, no Copilot-seat gate | **Official MCP** |
| IT allow/block Mail vs Teams separately | **Connectors** |
| Foundry hosted agent + DeepSeek + `pi-example` isolation | **Official MCP** (toolbox) |
| Copilot Studio / Teams maker UX | **Connectors** |
| 10 verbs + `get_schema` + Phase A hide-writes | **Official MCP** |
| Named “send email” / “create event” tools + Studio HITL | **Connectors** |
| Documented hosted OBO sample | A2A `WorkIQPreviewToolboxTool` (same Credits API; not 10 verbs) |
| Lowest first-byte after cold start | Connectors in Studio, or keep `pi-example` for non-Work-IQ smoke |

**This repo’s lock:** official **MCP** behind **toolbox + OBO**, Credits, `workiq-reader` later, `pi-example` unchanged. Connector Mail/Calendar tools and Agent 365 BYO MCP stay out of scope.

**Open measurement (after APIM consent):** live `tools/list` and `fetch /me/messages` latency; whether `ask` is acceptable for the demo; Credits consumption per call. Until consent completes, only the **mock** dry-run in `hosted-workiq/` is proven.
