// POC platform: AKS (workload identity) + ACR, wired to an existing Foundry
// account/project (created in the portal).
// AKS service can then create more projects and create/delete hosted agents.
// Does not create the Kubernetes ServiceAccount or the application.

param location string = resourceGroup().location

@description('AKS cluster name')
param aksName string = 'aks-foundry-poc'

@description('ACR name. Must be globally unique, 5-50 alphanumeric.')
param acrName string = 'acrfoundrypoc${uniqueString(resourceGroup().id)}'

@description('User-assigned identity used by the AKS Foundry control service')
param uamiName string = 'uami-foundry-poc'

@description('Kubernetes namespace of the control-service ServiceAccount')
param k8sNamespace string = 'default'

@description('Kubernetes ServiceAccount name federated to the UAMI')
param k8sServiceAccount string = 'foundry-sa'

@description('AKS system node VM size. Must be allowed in the subscription/region.')
param aksNodeVmSize string = 'Standard_D2s_v7'

@description('Existing Foundry account name (created in the portal).')
param foundryAccountName string = 'foundry-account'

@description('Existing default Foundry project name.')
param foundryProjectName string = 'foundry-project'

@description('Catalog model deployment name (managed compute). Deployed from the Foundry portal.')
param modelName string = 'zai-org--glm-47-flash'

// Built-in role definition IDs (stable across the Foundry role rename)
var roleFoundryOwner = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'c883944f-8b7b-4483-af10-35834be79c4a')
var roleFoundryProjectManager = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'eadc314b-1a2d-4efa-be10-5d325db5065e')
var roleFoundryUser = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
var roleAcrPull = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
var roleAcrPush = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8311e382-0749-4cb8-b61a-304f252e45ec')
var roleAcrRepoReader = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b93aa761-3e63-49ed-ac28-beffa264f7ac')
var roleAcrRepoWriter = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a1e307c-b015-4ebd-883e-5b7698a07328')
var roleRbacAdmin = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'f58310d9-a9f6-439a-9e8d-f62e7b41a168')
var roleLogAnalyticsDataReader = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3b03c2da-16b3-4a49-8834-0f8130efdd3b')
var roleLogAnalyticsReader = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '73c42c96-874c-492b-b04d-ab87d138a893')

var lawName = 'law-foundry-${uniqueString(resourceGroup().id)}'
var appInsightsName = 'appi-foundry-${uniqueString(resourceGroup().id)}'
var foundryEndpoint = 'https://${foundryAccountName}.services.ai.azure.com'
var foundryProjectEndpoint = '${foundryEndpoint}/api/projects/${foundryProjectName}'

// ---------------------------------------------------------------------------
// Identity + compute
// ---------------------------------------------------------------------------

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: uamiName
  location: location
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    // Hosted agents present an ARM-audience Entra token when pulling images.
    policies: {
      azureADAuthenticationAsArmPolicy: {
        status: 'enabled'
      }
    }
  }
}

resource aks 'Microsoft.ContainerService/managedClusters@2024-01-01' = {
  name: aksName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    dnsPrefix: aksName
    agentPoolProfiles: [
      {
        name: 'system'
        count: 1
        vmSize: aksNodeVmSize
        mode: 'System'
        osType: 'Linux'
      }
    ]
    oidcIssuerProfile: { enabled: true }
    securityProfile: { workloadIdentity: { enabled: true } }
  }
}

resource fic 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  name: 'fic-${k8sServiceAccount}'
  parent: uami
  properties: {
    issuer: aks.properties.oidcIssuerProfile.issuerURL
    subject: 'system:serviceaccount:${k8sNamespace}:${k8sServiceAccount}'
    audiences: [ 'api://AzureADTokenExchange' ]
  }
}

// ---------------------------------------------------------------------------
// Observability (hosted-agent telemetry + evaluations)
// ---------------------------------------------------------------------------

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

// ---------------------------------------------------------------------------
// Existing Foundry (created in the portal). Do not recreate — this
// subscription rejected ARM create of CognitiveServices/accounts.
// ---------------------------------------------------------------------------

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundry
  name: foundryProjectName
}

resource accountCapabilityHost 'Microsoft.CognitiveServices/accounts/capabilityHosts@2025-04-01-preview' = {
  parent: foundry
  name: '${foundry.name}-capHost'
  properties: {
    capabilityHostKind: 'Agents'
  }
}

resource projectCapabilityHost 'Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-04-01-preview' = {
  parent: foundryProject
  name: '${foundryProjectName}-capHost'
  properties: {
    // Required at runtime; omitted from current Bicep type metadata (BCP037).
    #disable-next-line BCP037
    capabilityHostKind: 'Agents'
  }
  dependsOn: [
    accountCapabilityHost
  ]
}

resource acrConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundryProject
  name: 'acr'
  properties: {
    category: 'ContainerRegistry'
    target: acr.properties.loginServer
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: acr.id
    }
  }
}

resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundryProject
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: appInsights.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: appInsights.properties.ConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appInsights.id
    }
  }
}

// ---------------------------------------------------------------------------
// RBAC — UAMI (AKS control service)
// Contributor on the RG is intentionally not assigned: it cannot call
// Foundry data-plane APIs (create/delete hosted agents).
// ---------------------------------------------------------------------------

resource uamiFoundryOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, uami.id, 'FoundryOwner')
  scope: foundry
  properties: {
    roleDefinitionId: roleFoundryOwner
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource uamiFoundryProjectManager 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, uami.id, 'FoundryProjectManager')
  scope: foundry
  properties: {
    roleDefinitionId: roleFoundryProjectManager
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource uamiAcrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, uami.id, 'AcrPush')
  scope: acr
  properties: {
    roleDefinitionId: roleAcrPush
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource uamiAcrRepoWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, uami.id, 'AcrRepoWriter')
  scope: acr
  properties: {
    roleDefinitionId: roleAcrRepoWriter
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Lets the service grant ACR pull / log read to MIs of projects it creates at runtime.
resource uamiRbacAdminAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, uami.id, 'RbacAdmin')
  scope: acr
  properties: {
    roleDefinitionId: roleRbacAdmin
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource uamiRbacAdminLaw 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(law.id, uami.id, 'RbacAdmin')
  scope: law
  properties: {
    roleDefinitionId: roleRbacAdmin
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource uamiRbacAdminAppInsights 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appInsights.id, uami.id, 'RbacAdmin')
  scope: appInsights
  properties: {
    roleDefinitionId: roleRbacAdmin
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// RBAC — seed project managed identity
// ---------------------------------------------------------------------------

resource projectFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, foundryProject.id, 'FoundryUser')
  scope: foundry
  properties: {
    roleDefinitionId: roleFoundryUser
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, foundryProject.id, 'AcrPull')
  scope: acr
  properties: {
    roleDefinitionId: roleAcrPull
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectAcrRepoReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, foundryProject.id, 'AcrRepoReader')
  scope: acr
  properties: {
    roleDefinitionId: roleAcrRepoReader
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectLawDataReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(law.id, foundryProject.id, 'LawDataReader')
  scope: law
  properties: {
    roleDefinitionId: roleLogAnalyticsDataReader
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectAppInsightsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appInsights.id, foundryProject.id, 'LawReader')
  scope: appInsights
  properties: {
    roleDefinitionId: roleLogAnalyticsReader
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// RBAC — AKS kubelet (node-level image pull for the control service)
// ---------------------------------------------------------------------------

resource aksKubeletAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, aks.id, 'AcrPull')
  scope: acr
  properties: {
    roleDefinitionId: roleAcrPull
    principalId: aks.properties.identityProfile.kubeletidentity.objectId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Outputs for the AKS control service
// After deploy, create the federated ServiceAccount:
//   apiVersion: v1
//   kind: ServiceAccount
//   metadata:
//     name: <k8sServiceAccount>
//     namespace: <k8sNamespace>
//     annotations:
//       azure.workload.identity/client-id: <uamiClientId>
// Pods must also set label azure.workload.identity/use: "true".
// ---------------------------------------------------------------------------

output uamiClientId string = uami.properties.clientId
output acrNameOut string = acr.name
output acrLoginServer string = acr.properties.loginServer
output aksNameOut string = aks.name
output k8sNamespaceOut string = k8sNamespace
output k8sServiceAccountOut string = k8sServiceAccount
output foundryAccountNameOut string = foundry.name
output foundryEndpoint string = foundryEndpoint
output foundryProjectNameOut string = foundryProject.name
output foundryProjectEndpoint string = foundryProjectEndpoint
output modelDeploymentName string = modelName
output subscriptionId string = subscription().subscriptionId
output resourceGroupName string = resourceGroup().name
