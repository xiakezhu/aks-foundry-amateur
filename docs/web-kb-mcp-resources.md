# Resources and relationships

**Not Work IQ.** This document is Azure AI Search / Foundry IQ (Web KB) MCP. Work IQ (Microsoft 365 mailbox/calendar OBO) is [`docs/work-iq-runbook.md`](work-iq-runbook.md). Do not reuse this Search MCP URL, admin key, or `https://search.azure.com/` audience for Work IQ.

Web KB MCP = **Azure AI Search** + a **Foundry GPT** deployment. Foundry does not host the MCP URL. Search does.

## Topology

```text
Subscription  <subscription-id>
└── <resource-group>
    ├── <search-service>        Azure AI Search (free, West Central US)
    │   ├── web-bing-ks          Knowledge source  kind=web  (Bing live search)
    │   └── web-search-kb        Knowledge base    uses web-bing-ks
    │         └── MCP            /knowledgebases/web-search-kb/mcp
    │
    └── <foundry-account>        Foundry / AI Services
        ├── project <foundry-project>
        └── <model-deployment>   Azure OpenAI deployment   ← may be missing
```

## Resources

| Resource | Type | Name | Role | Relates to |
| --- | --- | --- | --- | --- |
| Search service | `Microsoft.Search/searchServices` | `<search-service>` | Hosts the knowledge source, knowledge base, and MCP HTTP server | Child of rg |
| Web knowledge source | Search data-plane object | `<web-ks>` | Live Bing / Web IQ query (no index) | Lives **on** the search service; referenced **by** the knowledge base |
| Knowledge base | Search data-plane object | `<knowledge-base>` | Plans retrieve, calls Bing, calls GPT, exposes MCP | Lives **on** the search service; **uses** the web KS; **calls** Foundry GPT |
| MCP endpoint | URL on the knowledge base | `https://<search-service>.search.windows.net/knowledgebases/<knowledge-base>/mcp?api-version=2026-05-01-preview` | What external agents call | Same object as the knowledge base |
| Search admin key | Credential on Search | Keys blade / `az search admin-key` | Auth for MCP (`api-key` header) | Issued **by** the search service |
| GPT deployment | Foundry model deployment | `<model-deployment>` (intended) | Summarize Bing hits and query planning | Child of Foundry account; **pointed to by** the knowledge base `models[]` |

## Knowledge base → model pointer

```text
resourceUri:   https://<foundry-account>.cognitiveservices.azure.com
deploymentId:  <model-deployment>
modelName:     <model-deployment>
```

If the model deployment is missing, `tools/list` works and `tools/call` returns `DeploymentNotFound`.

## Optional (Foundry agent consuming the same MCP)

Not required for curl / Claude / Agent Framework.

| Resource | Name | Relationship |
| --- | --- | --- |
| Project connection | `<mcp-connection>` | On Foundry project; `RemoteTool` target = MCP URL |
| Project managed identity | project MI | Auth for that connection (`audience: https://search.azure.com/`) |
| Role assignment | **Search Index Data Reader** | Project MI **on** the search service |

## Not on this path

AKS, ACR, UAMI, App Insights, Log Analytics, hosted agents, and the GLM catalog model are from the broader POC. They are not used by this MCP retrieve path.
