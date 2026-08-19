# Foundry + AKS control service — build guide

This document records the POC as built: an AKS service that authenticates with workload identity and creates Foundry projects, creates/deletes hosted agents, and invokes them. Recreate it with the portal, Azure CLI, and Kubernetes. Do not assume Bicep is available.

Use your own values for `<subscription-id>`, `<resource-group>`, `<location>`, and resource names. Do not commit subscription IDs, resource group names, identity IDs, or registry credentials.

---

## 1. What the system does

A control service (`foundry-control`) runs in AKS. The pod uses a Kubernetes ServiceAccount federated to a user-assigned managed identity (UAMI). No API keys are stored in the pod.

| Capability | HTTP API | Status |
|---|---|---|
| Health | `GET /health` | Implemented |
| List projects | `GET /projects` | Implemented |
| Create project | `POST /projects` `{"name":"..."}` | Implemented |
| Update / delete project | — | Not in the service (use Azure CLI / portal) |
| List agents | `GET /agents` | Implemented |
| Create **hosted** agent | `POST /agents` `{"name","image"}` | Implemented (on demand) |
| Invoke hosted agent | `POST /agents/{name}/invoke` | Implemented |
| Delete agent | `DELETE /agents/{name}` | Implemented |
| Chat the catalog model (not an agent) | `POST /chat` | Implemented |
| Prompt-agent create | — | Done once via a Job, not a first-class POST body |
| Project get-one / update / delete | — | Not exposed |

Hosted-agent invoke URL (what the service calls):

```
POST https://<foundry-account>.services.ai.azure.com/api/projects/<foundry-project>/agents/<name>/endpoint/protocols/openai/responses?api-version=v1
```

Headers: `Authorization: Bearer <token>` (audience `https://ai.azure.com/.default`), `Foundry-Features: HostedAgents=V1Preview`.

Multi-turn: send `previous_response_id` (previous response `id`) and optionally `agent_session_id`. The sample `hosted-echo` image only echoes the current input; it does not use conversation history.

---

## 2. Architecture

```
Laptop (kubectl / curl + optional HTTP proxy)
        |
        | port-forward :<local-port> -> svc/foundry-control:80
        v
AKS  foundry-control  (ServiceAccount foundry-sa)
        |  workload identity (federated credential)
        v
UAMI  <uami-name>
        |
        +--> Cognitive Services ARM     create/list projects
        +--> Foundry project API        create/list/delete/invoke agents
        +--> Foundry managed compute    POST /chat
        +--> ACR (push images; grant roles on new projects)

Foundry account  <foundry-account>
  project        <foundry-project>
    prompt agent     <prompt-agent-name>
    hosted agent     <hosted-agent-name>    (image: <acr-login-server>/hosted-echo:<tag>)

ACR  <acr-name>
  foundry-control:<tag>
  hosted-echo:<tag>
```

Authentication path: pod label `azure.workload.identity/use: "true"` → SA annotation `azure.workload.identity/client-id` → federated credential on the UAMI (`issuer` = AKS OIDC, `subject` = `system:serviceaccount:default:foundry-sa`).

---

## 3. Constraints learned on this subscription

Record these before repeating the build elsewhere.

- **Azure OpenAI may be blocked** by tenant regulation. Creating `Microsoft.CognitiveServices/accounts` via ARM, or deploying any `gpt-*` / `o*`-series model, can fail with `CannotDeployDueToLocalRegulations`. Create the Foundry account in the **portal**. Do not deploy GPT models if that error appears.
- **Partner-model serverless quota may be 0**. A catalog model can instead be deployed as **managed compute** (`GlobalManagedCompute`). That SKU bills while it exists. Delete it when not testing.
- **ACR Tasks may be denied**. Do not rely on `az acr build`. Build with Docker if the network allows, or with **Kaniko in AKS**.
- **Local Docker Hub / ACR HTTPS may fail** behind a TLS-inspecting proxy. Microsoft Container Registry (`mcr.microsoft.com`) is a reliable base-image source. AKS nodes can usually pull MCR and push to ACR.
- **Look up `AcrPull` by name** in the target subscription. The role definition GUID is not always the well-known public-cloud value. Using the wrong GUID fails with `RoleDefinitionDoesNotExist`.
- **kubectl** to a public AKS API may require a working HTTP/HTTPS proxy. Half-configured TUN (fake DNS without a live proxy) breaks the API server.

```bash
az role definition list --name AcrPull --query "[].name" -o tsv
```

---

## 4. Resources to create

### Portal / CLI (manual)

| Resource | Placeholder | Type | Notes |
|---|---|---|---|
| Resource group | `<resource-group>` | Resource group | `az group create -n <resource-group> -l <location>` |
| Foundry account | `<foundry-account>` | `Microsoft.CognitiveServices/accounts` kind `AIServices` | Portal. `allowProjectManagement: true`, S0, system-assigned identity |
| Foundry project | `<foundry-project>` | `accounts/projects` | Default project, system-assigned identity |
| Catalog model | `<model-deployment-name>` | `accounts/managedComputeDeployments` if serverless is unavailable | Catalog model. **Not** `accounts/deployments` when using managed compute |
| ACR admin user | on `<acr-name>` | Registry setting | Enable only if Kaniko must push with admin credentials; disable afterward |

### Platform (ARM / CLI)

| Resource | Placeholder | Type |
|---|---|---|
| User-assigned identity | `<uami-name>` | `Microsoft.ManagedIdentity/userAssignedIdentities` |
| Federated credential | `fic-foundry-sa` | child of the UAMI |
| Container registry | `<acr-name>` | ACR Basic; ARM-audience tokens **enabled** |
| AKS | `<aks-name>` | Small system pool, OIDC + workload identity |
| Log Analytics | `<law-name>` | Short retention for a POC |
| Application Insights | `<appi-name>` | workspace-based |
| Account capability host | `{account}-capHost` | `capabilityHostKind: Agents` |
| Project capability host | `{project}-capHost` | `capabilityHostKind: Agents` |
| Project connection | `acr` | category `ContainerRegistry`, AAD, ACR resource id |
| Project connection | `appinsights` | category `AppInsights`, connection string |

Read the UAMI client id after create (`az identity show --query clientId`). Do not hard-code it in shared docs.

### Kubernetes (after AKS exists)

| Object | Name | Purpose |
|---|---|---|
| ServiceAccount | `default/foundry-sa` | Workload identity; annotation `azure.workload.identity/client-id` |
| Deployment / Service | `foundry-control` | Control API, ClusterIP port 80 → 8080 |
| Images | `foundry-control:<tag>`, `hosted-echo:<tag>` | Built in-cluster with Kaniko if needed |
| Agents in Foundry | prompt agent + hosted agent | Created by Jobs / `POST /agents` |

---

## 5. Role assignments (recreate without Bicep)

Use role **definition IDs**. Names changed (Azure AI * → Foundry *). Confirm `AcrPull` in the target subscription before assigning.

### 5.1 Role definition IDs

These are Azure **built-in** role IDs (not secrets). Still verify `AcrPull` locally.

| Role | Typical ID |
|---|---|
| Foundry Owner | `c883944f-8b7b-4483-af10-35834be79c4a` |
| Foundry Project Manager | `eadc314b-1a2d-4efa-be10-5d325db5065e` |
| Foundry User | `53ca6127-db72-4b80-b1b0-d745d6d5456d` |
| AcrPull | **look up** with `az role definition list --name AcrPull` |
| AcrPush | `8311e382-0749-4cb8-b61a-304f252e45ec` |
| Container Registry Repository Reader | `b93aa761-3e63-49ed-ac28-beffa264f7ac` |
| Container Registry Repository Writer | `2a1e307c-b015-4ebd-883e-5b7698a07328` |
| Role Based Access Control Administrator | `f58310d9-a9f6-439a-9e8d-f62e7b41a168` |
| Log Analytics Data Reader | `3b03c2da-16b3-4a49-8834-0f8130efdd3b` |
| Log Analytics Reader | `73c42c96-874c-492b-b04d-ab87d138a893` |
| Cognitive Services User | `a97b65f3-24c7-4388-baec-2e87135dc908` |

### 5.2 Assignments on the UAMI (control service)

Scope = resource unless noted. Principal = UAMI object id.

| Role | Scope | Why |
|---|---|---|
| Foundry Owner | Foundry account | Create projects; create/delete/invoke agents (data + control plane) |
| Foundry Project Manager | Foundry account | Hosted-agent deploy; auto Foundry User on new project MIs |
| AcrPush | ACR | Push agent / control images |
| Container Registry Repository Writer | ACR | Same, data-plane push |
| RBAC Administrator | ACR | Grant pull to new project MIs at runtime |
| RBAC Administrator | Log Analytics | Grant log read to new project MIs |
| RBAC Administrator | Application Insights | Same for App Insights |
| Cognitive Services User | Foundry account | Extra data-plane; needed here for managed-compute `/chat` and some invoke paths |

```bash
RG=<resource-group>
UAMI_PID=$(az identity show -g "$RG" -n <uami-name> --query principalId -o tsv)
FOUNDRY=$(az cognitiveservices account show -g "$RG" -n <foundry-account> --query id -o tsv)
ACR=$(az acr show -g "$RG" -n <acr-name> --query id -o tsv)
LAW=$(az monitor log-analytics workspace show -g "$RG" -n <law-name> --query id -o tsv)
APPI=$(az monitor app-insights component show -g "$RG" -a <appi-name> --query id -o tsv)

az role assignment create --assignee-object-id "$UAMI_PID" --assignee-principal-type ServicePrincipal \
  --role c883944f-8b7b-4483-af10-35834be79c4a --scope "$FOUNDRY"
az role assignment create --assignee-object-id "$UAMI_PID" --assignee-principal-type ServicePrincipal \
  --role eadc314b-1a2d-4efa-be10-5d325db5065e --scope "$FOUNDRY"
az role assignment create --assignee-object-id "$UAMI_PID" --assignee-principal-type ServicePrincipal \
  --role 8311e382-0749-4cb8-b61a-304f252e45ec --scope "$ACR"
az role assignment create --assignee-object-id "$UAMI_PID" --assignee-principal-type ServicePrincipal \
  --role 2a1e307c-b015-4ebd-883e-5b7698a07328 --scope "$ACR"
az role assignment create --assignee-object-id "$UAMI_PID" --assignee-principal-type ServicePrincipal \
  --role f58310d9-a9f6-439a-9e8d-f62e7b41a168 --scope "$ACR"
az role assignment create --assignee-object-id "$UAMI_PID" --assignee-principal-type ServicePrincipal \
  --role f58310d9-a9f6-439a-9e8d-f62e7b41a168 --scope "$LAW"
az role assignment create --assignee-object-id "$UAMI_PID" --assignee-principal-type ServicePrincipal \
  --role f58310d9-a9f6-439a-9e8d-f62e7b41a168 --scope "$APPI"
az role assignment create --assignee-object-id "$UAMI_PID" --assignee-principal-type ServicePrincipal \
  --role a97b65f3-24c7-4388-baec-2e87135dc908 --scope "$FOUNDRY"
```

### 5.3 Assignments on the Foundry **project** managed identity

Principal = project system-assigned identity (portal → project → identity, or `az cognitiveservices account project show`).

| Role | Scope | Why |
|---|---|---|
| Foundry User | Foundry account | Project can call models / agent runtime |
| AcrPull | ACR | Hosted agent platform pulls the container |
| Container Registry Repository Reader | ACR | Same, data-plane pull |
| Log Analytics Data Reader | LAW | Evaluations / traces |
| Log Analytics Reader | Application Insights | Read telemetry |

```bash
PROJ_PID=$(az cognitiveservices account project show \
  -g "$RG" --name <foundry-account> --project-name <foundry-project> \
  --query identity.principalId -o tsv)
ACR_PULL=$(az role definition list --name AcrPull --query "[0].name" -o tsv)

az role assignment create --assignee-object-id "$PROJ_PID" --assignee-principal-type ServicePrincipal \
  --role 53ca6127-db72-4b80-b1b0-d745d6d5456d --scope "$FOUNDRY"
az role assignment create --assignee-object-id "$PROJ_PID" --assignee-principal-type ServicePrincipal \
  --role "$ACR_PULL" --scope "$ACR"
az role assignment create --assignee-object-id "$PROJ_PID" --assignee-principal-type ServicePrincipal \
  --role b93aa761-3e63-49ed-ac28-beffa264f7ac --scope "$ACR"
az role assignment create --assignee-object-id "$PROJ_PID" --assignee-principal-type ServicePrincipal \
  --role 3b03c2da-16b3-4a49-8834-0f8130efdd3b --scope "$LAW"
az role assignment create --assignee-object-id "$PROJ_PID" --assignee-principal-type ServicePrincipal \
  --role 73c42c96-874c-492b-b04d-ab87d138a893 --scope "$APPI"
```

Repeat the ACR pull + Foundry User grants for **each new project** the control service creates (or let the service do it; it has RBAC Administrator on ACR).

### 5.4 AKS kubelet → ACR

Without this, `foundry-control` pods get `ImagePullBackOff`.

```bash
KUBELET=$(az aks show -g "$RG" -n <aks-name> \
  --query identityProfile.kubeletidentity.objectId -o tsv)
az role assignment create --assignee-object-id "$KUBELET" --assignee-principal-type ServicePrincipal \
  --role "$ACR_PULL" --scope "$ACR"
```

### 5.5 Human operator (laptop / `az login`)

Needed so a user can call the catalog model and debug outside the pod. Owner on the subscription is **not** enough for Foundry data plane.

| Role | Scope | Assignee |
|---|---|---|
| Foundry User | Foundry account | signed-in user |
| Foundry Owner | Foundry account | signed-in user (optional, broader) |
| Cognitive Services User | Foundry account | signed-in user |

```bash
USER_OID=$(az ad signed-in-user show --query id -o tsv)
az role assignment create --assignee-object-id "$USER_OID" --assignee-principal-type User \
  --role 53ca6127-db72-4b80-b1b0-d745d6d5456d --scope "$FOUNDRY"
az role assignment create --assignee-object-id "$USER_OID" --assignee-principal-type User \
  --role a97b65f3-24c7-4388-baec-2e87135dc908 --scope "$FOUNDRY"
```

---

## 6. Build steps (no Bicep)

### 6.1 Resource group and providers

```bash
az group create -n <resource-group> -l <location>
az provider register --namespace Microsoft.ContainerService --wait
az provider register --namespace Microsoft.ContainerRegistry --wait
az provider register --namespace Microsoft.ManagedIdentity --wait
az provider register --namespace Microsoft.OperationalInsights --wait
az provider register --namespace Microsoft.Insights --wait
az provider register --namespace Microsoft.CognitiveServices --wait
```

### 6.2 Foundry account and project (portal)

1. Create a **Microsoft Foundry / Azure AI services** resource (`kind: AIServices`), not a classic hub (no required Storage/Key Vault).
2. Enable project management. Create the default project.
3. Public network is acceptable for a POC.
4. Deploy a model from the catalog. Use **managed compute** if serverless quota is zero. Expect 15–40 minutes. **This is not** `Microsoft.CognitiveServices/accounts/deployments`.

### 6.3 Identity, ACR, AKS, observability

Create a UAMI, ACR (Basic; set `azureADAuthenticationAsArmPolicy` to `enabled`), AKS with OIDC + workload identity, a Log Analytics workspace, and workspace-based Application Insights. Then create the federated credential:

- Issuer: `az aks show --query oidcIssuerProfile.issuerUrl`
- Subject: `system:serviceaccount:default:foundry-sa`
- Audience: `api://AzureADTokenExchange`

Apply all role assignments in section 5.

Add Agent capability hosts on the account and project, an ACR connection (`category: ContainerRegistry`, `authType: AAD`), and an App Insights connection on the seed project.

Pick an AKS node SKU the subscription allows in that region (some classic SKUs are rejected).

### 6.4 Kubernetes ServiceAccount

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: foundry-sa
  namespace: default
  annotations:
    azure.workload.identity/client-id: "<uami-client-id>"
```

```bash
az aks get-credentials -g <resource-group> -n <aks-name>
kubectl apply -f k8s/sa.yaml
```

Pods that use the identity must also set label `azure.workload.identity/use: "true"`.

### 6.5 Build and push images

If `az acr build` is blocked and the laptop cannot push to ACR, build **inside AKS** (Kaniko):

1. Enable ACR admin temporarily; store credentials in a `kubernetes.io/dockerconfigjson` secret (do not commit passwords).
2. Put `Dockerfile`, `requirements.txt`, and `main.py` in a ConfigMap.
3. Copy ConfigMap files into an `emptyDir` (ConfigMap mounts are not regular files for Kaniko `COPY`).
4. Kaniko destination: `<acr-login-server>/foundry-control:<tag>` and `<acr-login-server>/hosted-echo:<tag>`.
5. Base image: `mcr.microsoft.com/devcontainers/python:3.12` if Docker Hub is unreachable.

Repo layout:

- `app/` — FastAPI control service (`azure-identity`, `azure-mgmt-cognitiveservices`, `azure-ai-projects`, `httpx`)
- `hosted-agent/` — Responses-protocol echo (`azure-ai-agentserver-responses`), listens as the host library expects (port 8088)

### 6.6 Deploy the control service

Apply `k8s/control.yaml`: Deployment + ClusterIP Service. Set env from your environment (do not commit real values):

- `AZURE_SUBSCRIPTION_ID`
- `AZURE_RESOURCE_GROUP`
- `FOUNDRY_ACCOUNT_NAME`
- `FOUNDRY_LOCATION`
- `FOUNDRY_PROJECT_ENDPOINT` = `https://<foundry-account>.services.ai.azure.com/api/projects/<foundry-project>`
- `ACR_LOGIN_SERVER`
- `MODEL_DEPLOYMENT_NAME`

### 6.7 Use the API

```bash
export HTTPS_PROXY=<http-proxy>   # if required
export HTTP_PROXY=$HTTPS_PROXY
export NO_PROXY=localhost,127.0.0.1
kubectl port-forward svc/foundry-control 8081:80
```

```bash
# health
curl -sS http://127.0.0.1:8081/health

# create hosted agent (image pull + provision; wait until active)
curl -sS -X POST http://127.0.0.1:8081/agents \
  -H 'Content-Type: application/json' \
  -d '{"name":"<hosted-agent-name>","image":"<acr-login-server>/hosted-echo:<tag>"}'

# invoke
curl -sS -X POST http://127.0.0.1:8081/agents/<hosted-agent-name>/invoke \
  -H 'Content-Type: application/json' \
  -d '{"input":"hello from control invoke"}'

# continue the same conversation (control image that forwards session fields)
curl -sS -X POST http://127.0.0.1:8081/agents/<hosted-agent-name>/invoke \
  -H 'Content-Type: application/json' \
  -d '{
    "input":"what is my name?",
    "previous_response_id":"<id from previous response>",
    "agent_session_id":"<agent_session_id from previous response>"
  }'

# list / delete
curl -sS http://127.0.0.1:8081/agents
curl -sS -X DELETE http://127.0.0.1:8081/agents/<hosted-agent-name>
```

A prompt agent can be created with `PromptAgentDefinition` and a catalog model name. Invoking it through the Responses agent endpoint may return `DeploymentNotFound` when the model is **managed compute** (not a Foundry-sold model deployment). Use `POST /chat` for that model, or hosted agents for the agent invoke path.

---

## 7. Operational notes

- **Port-forward is not the service.** If curl reports `Connection reset by peer`, restart `kubectl port-forward`. The pod can still be Running.
- **Delete managed-compute GPU deployments** when not testing; they bill continuously.
- **Disable ACR admin** after Kaniko if policy requires it; switch Kaniko to the UAMI / `AcrPush` later.
- New projects created by `POST /projects` need the same project-MI role grants and ACR / App Insights connections before hosted agents will start.
- Do not commit subscription IDs, resource group names, UAMI client IDs, ACR admin passwords, or kubeconfigs.
