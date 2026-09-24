param name string
param location string
param tags object
param planId string
param storageAccountName string
param deploymentContainerName string
param identityId string
param identityClientId string
param keyVaultUri string
param geminiModel string
param appInsightsResourceId string

resource storage 'Microsoft.Storage/storageAccounts@2022-09-01' existing = {
  name: storageAccountName
}

var appSettings = {
  AzureWebJobsStorage__credential: 'managedidentity'
  AzureWebJobsStorage__clientId: identityClientId
  AzureWebJobsStorage__blobServiceUri: storage.properties.primaryEndpoints.blob
  FUNCTIONS_EXTENSION_VERSION: '~4'
  GEMINI_MODEL: geminiModel
  GATEWAY_REQUESTS_PER_MINUTE: '30'
  GATEWAY_UPSTREAM_TIMEOUT_SECONDS: '25'
  GEMINI_API_KEY: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/gemini-api-key)'
  GATEWAY_SHARED_SECRET: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/gemini-gateway-shared-secret)'
}

module app 'br/public:avm/res/web/site:0.15.1' = {
  name: 'gateway-flex-consumption'
  params: {
    name: name
    location: location
    kind: 'functionapp,linux'
    tags: union(tags, { 'azd-service-name': 'gemini-gateway' })
    serverFarmResourceId: planId
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: [ identityId ]
    }
    appInsightResourceId: appInsightsResourceId
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deploymentContainerName}'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: identityId
          }
        }
      }
      scaleAndConcurrency: {
        instanceMemoryMB: 512
        maximumInstanceCount: 2
        alwaysReady: [
          {
            name: 'http'
            instanceCount: 1
          }
        ]
      }
      runtime: {
        name: 'python'
        version: '3.13'
      }
    }
    siteConfig: {
      alwaysOn: false
    }
    appSettingsKeyValuePairs: appSettings
  }
}

output systemPrincipalId string = app.outputs.?systemAssignedMIPrincipalId ?? ''
