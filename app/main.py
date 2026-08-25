"""AKS control service: create Foundry projects and hosted agents via Entra (workload identity)."""

import os
import time
from typing import Optional

import httpx
from azure.identity import DefaultAzureCredential
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    ContainerConfiguration,
    HostedAgentDefinition,
    ProtocolVersionRecord,
)
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

SUBSCRIPTION_ID = os.environ["AZURE_SUBSCRIPTION_ID"]
RESOURCE_GROUP = os.environ["AZURE_RESOURCE_GROUP"]
FOUNDRY_ACCOUNT = os.environ["FOUNDRY_ACCOUNT_NAME"]
FOUNDRY_LOCATION = os.environ.get("FOUNDRY_LOCATION", "eastus")
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
ACR_LOGIN_SERVER = os.environ.get("ACR_LOGIN_SERVER", "")
MODEL_NAME = os.environ.get("MODEL_DEPLOYMENT_NAME", "zai-org--glm-47-flash")

credential = DefaultAzureCredential()
arm = CognitiveServicesManagementClient(
    credential,
    SUBSCRIPTION_ID,
    api_version="2025-04-01-preview",
)
app = FastAPI(title="foundry-control", version="0.1.0")


def project_client(endpoint: Optional[str] = None) -> AIProjectClient:
    return AIProjectClient(endpoint=endpoint or PROJECT_ENDPOINT, credential=credential)


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=64)


class CreateAgentRequest(BaseModel):
    name: str
    image: Optional[str] = None
    project_endpoint: Optional[str] = None
    cpu: str = "1"
    memory: str = "2Gi"
    protocol: str = "responses"
    wait: bool = True
    environment_variables: Optional[dict[str, str]] = None


class ChatRequest(BaseModel):
    message: str
    model: str = MODEL_NAME


class InvokeAgentRequest(BaseModel):
    input: str
    previous_response_id: Optional[str] = None
    agent_session_id: Optional[str] = None


@app.get("/health")
def health():
    return {
        "ok": True,
        "account": FOUNDRY_ACCOUNT,
        "projectEndpoint": PROJECT_ENDPOINT,
        "model": MODEL_NAME,
        "acr": ACR_LOGIN_SERVER,
    }


@app.get("/projects")
def list_projects():
    items = arm.projects.list(RESOURCE_GROUP, FOUNDRY_ACCOUNT)
    return {
        "projects": [
            {
                "name": p.name.split("/")[-1],
                "provisioningState": getattr(p.properties, "provisioning_state", None),
            }
            for p in items
        ]
    }


@app.post("/projects")
def create_project(body: CreateProjectRequest):
    try:
        poller = arm.projects.begin_create(
            RESOURCE_GROUP,
            FOUNDRY_ACCOUNT,
            body.name,
            {
                "location": FOUNDRY_LOCATION,
                "identity": {"type": "SystemAssigned"},
                "properties": {},
            },
        )
        result = poller.result()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "name": body.name,
        "id": result.id,
        "endpoint": f"https://{FOUNDRY_ACCOUNT}.services.ai.azure.com/api/projects/{body.name}",
        "note": "Grant the new project MI AcrPull on ACR and add ACR/App Insights connections before deploying hosted agents.",
    }


@app.post("/chat")
def chat(body: ChatRequest):
    token = credential.get_token("https://cognitiveservices.azure.com/.default").token
    url = f"https://{FOUNDRY_ACCOUNT}.services.ai.azure.com/managed-deployments/{body.model}/v1/chat/completions"
    payload = {
        "model": body.model,
        "messages": [{"role": "user", "content": body.message}],
        "max_tokens": 256,
    }
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=120.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


@app.get("/agents")
def list_agents(project_endpoint: Optional[str] = None):
    client = project_client(project_endpoint)
    return {"agents": [{"name": a.name} for a in client.agents.list()]}


@app.get("/agents/{name}")
def get_agent(name: str, project_endpoint: Optional[str] = None):
    client = project_client(project_endpoint)
    try:
        agent = client.agents.get(agent_name=name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"name": getattr(agent, "name", name), "agent": str(agent)}


@app.post("/agents")
def create_agent(body: CreateAgentRequest):
    image = body.image or (f"{ACR_LOGIN_SERVER}/hosted-pi-agent:v1" if ACR_LOGIN_SERVER else None)
    if not image:
        raise HTTPException(status_code=400, detail="image is required (or set ACR_LOGIN_SERVER)")
    client = project_client(body.project_endpoint)
    try:
        version = client.agents.create_version(
            agent_name=body.name,
            definition=HostedAgentDefinition(
                cpu=body.cpu,
                memory=body.memory,
                container_configuration=ContainerConfiguration(image=image),
                protocol_versions=[
                    ProtocolVersionRecord(protocol=body.protocol, version="1.0.0"),
                ],
                environment_variables=body.environment_variables,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ver = str(getattr(version, "version", "1"))
    status = getattr(version, "status", None)
    if body.wait:
        for _ in range(60):
            current = client.agents.get_version(agent_name=body.name, agent_version=ver)
            status = getattr(current, "status", None)
            status_s = str(status).lower() if status is not None else ""
            if "active" in status_s:
                version = current
                break
            if "fail" in status_s:
                raise HTTPException(status_code=500, detail=f"hosted agent failed: {current}")
            time.sleep(10)
    return {
        "kind": "hosted",
        "name": body.name,
        "image": image,
        "version": getattr(version, "version", ver),
        "status": str(getattr(version, "status", status)),
    }


@app.post("/agents/{name}/invoke")
def invoke_agent(name: str, body: InvokeAgentRequest, project_endpoint: Optional[str] = None):
    token = credential.get_token("https://ai.azure.com/.default").token
    base = (project_endpoint or PROJECT_ENDPOINT).rstrip("/")
    url = f"{base}/agents/{name}/endpoint/protocols/openai/responses?api-version=v1"
    payload = {"input": body.input}
    if body.previous_response_id:
        payload["previous_response_id"] = body.previous_response_id
    if body.agent_session_id:
        payload["agent_session_id"] = body.agent_session_id
    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Foundry-Features": "HostedAgents=V1Preview",
            },
            json=payload,
            timeout=180.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


@app.delete("/agents/{name}")
def delete_agent(name: str, project_endpoint: Optional[str] = None):
    client = project_client(project_endpoint)
    try:
        client.agents.delete(agent_name=name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": name}
