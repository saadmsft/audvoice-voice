@description('Resource location (must be uaenorth for residency)')
param location string

@description('Short prefix for resource names')
param namePrefix string

@description('Container image reference; if empty, deploys a placeholder image')
param containerImage string

@secure()
param jwtSecret string

@secure()
param apiKeysCsv string

var suffix = uniqueString(resourceGroup().id)
var saneName = toLower(namePrefix)

// ─── AI Services (Speech + OpenAI on the same multi-service resource) ─────
resource ai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: '${saneName}-ai-${suffix}'
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: '${saneName}-ai-${suffix}'
    publicNetworkAccess: 'Enabled'
  }
}

// ─── Azure OpenAI deployment: gpt-4.1 GlobalStandard ──────────────────────
// NOTE: UAE North does not currently offer regional Standard for gpt-4.1.
// GlobalStandard routes inference globally — token data may leave UAE.
// Speech (STT/TTS) remains UAE-resident on this same AIServices resource.
resource openaiDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: ai
  name: 'gpt-4.1'
  sku: { name: 'GlobalStandard', capacity: 10 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4.1', version: '2025-04-14' }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
}

// ─── Azure AI Search (for VoiceRAG) ───────────────────────────────────────
resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: '${saneName}-search-${suffix}'
  location: location
  sku: { name: 'basic' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    semanticSearch: 'free'
    publicNetworkAccess: 'enabled'
  }
}

// ─── Redis ────────────────────────────────────────────────────────────────
resource redis 'Microsoft.Cache/Redis@2024-04-01-preview' = {
  name: '${saneName}-redis-${suffix}'
  location: location
  properties: {
    sku: { name: 'Basic', family: 'C', capacity: 0 }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
  }
}

// ─── Key Vault ────────────────────────────────────────────────────────────
resource kv 'Microsoft.KeyVault/vaults@2024-04-01-preview' = {
  name: '${saneName}-kv-${suffix}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

resource kvJwt 'Microsoft.KeyVault/vaults/secrets@2024-04-01-preview' = {
  parent: kv
  name: 'jwt-secret'
  properties: { value: jwtSecret }
}

resource kvApiKeys 'Microsoft.KeyVault/vaults/secrets@2024-04-01-preview' = {
  parent: kv
  name: 'api-keys-csv'
  properties: { value: apiKeysCsv }
}

// ─── App Insights ─────────────────────────────────────────────────────────
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${saneName}-law-${suffix}'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: '${saneName}-appi-${suffix}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

// ─── App Service: Linux container, WebSockets ON, Premium v3 ──────────────
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${saneName}-plan-${suffix}'
  location: location
  sku: { name: 'P1v3', tier: 'PremiumV3' }
  properties: { reserved: true } // Linux
}

var image = empty(containerImage) ? 'mcr.microsoft.com/appsvc/staticsite:latest' : containerImage

resource site 'Microsoft.Web/sites@2023-12-01' = {
  name: '${saneName}-app-${suffix}'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'DOCKER|${image}'
      webSocketsEnabled: true
      http20Enabled: true
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'WEBSITES_PORT', value: '8080' }
        { name: 'AZURE_SPEECH_KEY', value: ai.listKeys().key1 }
        { name: 'AZURE_SPEECH_REGION', value: location }
        { name: 'AZURE_OPENAI_ENDPOINT', value: ai.properties.endpoint }
        { name: 'AZURE_OPENAI_API_KEY', value: ai.listKeys().key1 }
        { name: 'AZURE_OPENAI_API_VERSION', value: '2024-10-21' }
        { name: 'AZURE_OPENAI_DEPLOYMENT', value: openaiDeployment.name }
        { name: 'AZURE_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
        { name: 'AZURE_SEARCH_KEY', value: listAdminKeys(search.id, '2024-06-01-preview').primaryKey }
        {
          name: 'REDIS_URL'
          value: 'rediss://:${listKeys(redis.id, '2024-04-01-preview').primaryKey}@${redis.properties.hostName}:6380'
        }
        { name: 'AUDVOICE_JWT_SECRET', value: '@Microsoft.KeyVault(VaultName=${kv.name};SecretName=jwt-secret)' }
        { name: 'AUDVOICE_API_KEYS', value: '@Microsoft.KeyVault(VaultName=${kv.name};SecretName=api-keys-csv)' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
        { name: 'DOCKER_ENABLE_CI', value: 'true' }
      ]
    }
  }
}

// Grant App Service identity Key Vault Secrets User
resource kvRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, site.id, 'kv-secrets-user')
  properties: {
    principalId: site.identity.principalId
    principalType: 'ServicePrincipal'
    // Key Vault Secrets User
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
  }
}

output appHostname string = site.properties.defaultHostName
output speechEndpoint string = ai.properties.endpoint
output openaiEndpoint string = ai.properties.endpoint
