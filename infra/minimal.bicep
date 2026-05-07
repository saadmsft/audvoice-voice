@description('Location (uaenorth for residency)')
param location string = 'uaenorth'

@description('AI Services account name (must be unique)')
param aiName string = 'audvoice-ai-${uniqueString(resourceGroup().id)}'

resource ai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: aiName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: aiName
    publicNetworkAccess: 'Enabled'
  }
}

// Speech is regional (uaenorth). gpt-4.1 must be GlobalStandard in UAE North.
resource gpt 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: ai
  name: 'gpt-4.1'
  sku: { name: 'GlobalStandard', capacity: 10 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4.1', version: '2025-04-14' }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
}

output aiName string = ai.name
output endpoint string = ai.properties.endpoint
output speechRegion string = location
