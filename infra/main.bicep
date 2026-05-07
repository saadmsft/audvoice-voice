targetScope = 'subscription'

@description('Resource group name')
param rgName string = 'rg-audvoice'

@description('Deployment region (UAE North for residency)')
param location string = 'uaenorth'

@description('Globally unique short name (lowercase, 3-12 chars)')
param namePrefix string = 'audvoice'

@description('Container image (e.g. <acr>.azurecr.io/audvoice:latest)')
param containerImage string = ''

@description('JWT signing secret (≥32 bytes base64). Stored in Key Vault.')
@secure()
param jwtSecret string

@description('Comma-separated apiKey:tenantId pairs for v1 (replace with DB later).')
@secure()
param apiKeysCsv string

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: rgName
  location: location
}

module svc 'services.bicep' = {
  name: 'audvoice-services'
  scope: rg
  params: {
    location: location
    namePrefix: namePrefix
    containerImage: containerImage
    jwtSecret: jwtSecret
    apiKeysCsv: apiKeysCsv
  }
}

output appHostname string = svc.outputs.appHostname
output speechEndpoint string = svc.outputs.speechEndpoint
output openaiEndpoint string = svc.outputs.openaiEndpoint
