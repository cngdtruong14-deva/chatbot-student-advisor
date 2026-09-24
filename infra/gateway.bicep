targetScope = 'resourceGroup'

param location string = 'malaysiawest'
param functionAppName string = 'func-advisor-gateway-5c4702'
param identityName string = 'id-advisor-gateway-5c4702'
param planName string = 'plan-advisor-gateway-5c4702'
param storageAccountName string = 'stadvgtw5c4702'
param keyVaultName string = 'kv-advis-staging-5c4702'
param geminiModel string = 'gemini-3.5-flash-lite'
param appInsightsName string = 'appi-advisor-staging-5c4702'

var deploymentContainerName = 'deploymentpackage'
var tags = {
  environment: 'staging'
  component: 'gemini-egress-gateway'
  'data-boundary': 'no-student-identity'
}

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultName
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

module identity 'br/public:avm/res/managed-identity/user-assigned-identity:0.4.1' = {
  name: 'gateway-identity'
  params: {
    name: identityName
    location: location
    tags: tags
  }
}

module plan 'br/public:avm/res/web/serverfarm:0.1.1' = {
  name: 'gateway-flex-plan'
  params: {
    name: planName
    location: location
    reserved: true
    sku: {
      name: 'FC1'
      tier: 'FlexConsumption'
    }
    tags: tags
  }
}

module storage 'br/public:avm/res/storage/storage-account:0.8.3' = {
  name: 'gateway-storage'
  params: {
    name: storageAccountName
    location: location
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    skuName: 'Standard_LRS'
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
    blobServices: {
      containers: [
        { name: deploymentContainerName }
      ]
    }
    tags: tags
  }
}

module storageRbac './gateway/storage-rbac.bicep' = {
  name: 'gateway-storage-rbac'
  params: {
    storageAccountName: storage.outputs.name
    managedIdentityPrincipalId: identity.outputs.principalId
  }
}

module gateway './gateway/function-app.bicep' = {
  name: 'gateway-function-app'
  dependsOn: [ storageRbac ]
  params: {
    name: functionAppName
    location: location
    planId: plan.outputs.resourceId
    storageAccountName: storage.outputs.name
    deploymentContainerName: deploymentContainerName
    identityId: identity.outputs.resourceId
    identityClientId: identity.outputs.clientId
    geminiModel: geminiModel
    appInsightsResourceId: appInsights.id
    keyVaultUri: keyVault.properties.vaultUri
    tags: tags
  }
}

module gatewaySecretsUser './gateway/key-vault-rbac.bicep' = {
  name: 'gateway-key-vault-rbac'
  params: {
    keyVaultName: keyVaultName
    managedIdentityPrincipalId: gateway.outputs.systemPrincipalId
  }
}

output gatewayHostName string = '${functionAppName}.azurewebsites.net'
output gatewayBaseUrl string = 'https://${functionAppName}.azurewebsites.net/api/v1'
output functionAppName string = functionAppName
output deploymentStorageAccount string = storage.outputs.name
output deploymentContainer string = deploymentContainerName
