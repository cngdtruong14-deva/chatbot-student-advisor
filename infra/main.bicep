targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param environmentName string

@minLength(1)
param location string

param sessionId string
param deployedBy string
param createdAt string
param deployerObjectId string

@secure()
param postgresAdministratorPassword string

@secure()
param jwtSecret string

param postgresAdministratorLogin string = 'advisoradmin'
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param webContainerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param apiContainerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param migrationJobImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param allowedHost string = ''
param corsAllowedOrigin string = ''
param customDomainName string = ''
param customDomainCertificateId string = ''
param gatewayBaseUrl string = ''

var tags = {
  'app-onboard-skill': 'true'
  'app-onboard-session-id': sessionId
  'created-at': createdAt
  environment: environmentName
  'deployed-by': deployedBy
}

resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: 'rg-advisor-staging-5c4702'
  location: location
  tags: tags
}

module logAnalytics './modules/log-analytics.bicep' = {
  name: 'log-analytics'
  scope: rg
  dependsOn: [
    rg
  ]
  params: {
    name: 'log-advisor-staging-5c4702'
    location: location
    tags: tags
  }
}

module applicationInsights './modules/application-insights.bicep' = {
  name: 'application-insights'
  scope: rg
  params: {
    name: 'appi-advisor-staging-5c4702'
    location: location
    tags: tags
    workspaceResourceId: logAnalytics.outputs.workspaceId
  }
}

module keyVault './modules/key-vault.bicep' = {
  name: 'key-vault'
  scope: rg
  dependsOn: [
    rg
  ]
  params: {
    name: 'kv-advis-staging-5c4702'
    location: location
    tags: tags
    databasePassword: postgresAdministratorPassword
    jwtSecret: jwtSecret
  }
}

module managedIdentity './modules/managed-identity.bicep' = {
  name: 'managed-identity'
  scope: rg
  dependsOn: [
    rg
  ]
  params: {
    name: 'id-advisor-staging-5c4702'
    location: location
    tags: tags
  }
}

module containerRegistry './modules/container-registry.bicep' = {
  name: 'container-registry'
  scope: rg
  dependsOn: [
    rg
  ]
  params: {
    name: 'cradvisorstaging5c4702'
    location: location
    tags: tags
  }
}

module postgresql './modules/postgresql.bicep' = {
  name: 'postgresql'
  scope: rg
  dependsOn: [
    rg
  ]
  params: {
    name: 'psql-advisor-staging-5c4702'
    location: location
    tags: tags
    administratorLogin: postgresAdministratorLogin
    administratorLoginPassword: postgresAdministratorPassword
  }
}

module storageAccount './modules/storage-account.bicep' = {
  name: 'storage-account'
  scope: rg
  dependsOn: [
    rg
  ]
  params: {
    name: 'stadvisorstaging5c4702'
    location: location
    tags: tags
  }
}

module virtualNetwork './modules/virtual-network.bicep' = {
  name: 'virtual-network'
  scope: rg
  dependsOn: [
    rg
  ]
  params: {
    name: 'vnet-advisor-staging-5c4702'
    location: location
    tags: tags
  }
}

resource logAnalyticsForEnvironment 'Microsoft.OperationalInsights/workspaces@2026-03-01' existing = {
  scope: rg
  name: 'log-advisor-staging-5c4702'
  dependsOn: [
    logAnalytics
  ]
}

resource storageForFiles 'Microsoft.Storage/storageAccounts@2026-06-01' existing = {
  scope: rg
  name: 'stadvisorstaging5c4702'
  dependsOn: [
    storageAccount
  ]
}

module containerEnvironment './modules/container-environment.bicep' = {
  name: 'container-environment'
  scope: rg
  dependsOn: [
    storageAccount
    virtualNetwork
  ]
  params: {
    name: 'cae-advisor-staging-5c470205'
    location: location
    tags: tags
    workspaceCustomerId: logAnalytics.outputs.workspaceCustomerId
    workspaceSharedKey: logAnalyticsForEnvironment.listKeys().primarySharedKey
    infrastructureSubnetId: virtualNetwork.outputs.infrastructureSubnetId
  }
}

// Keep the Azure Files child deployment independent from environment creation.
// Azure evaluates this only after the managed environment deployment completes.
module containerEnvironmentStorage './modules/container-environment-storage.bicep' = {
  name: 'container-environment-storage'
  scope: rg
  dependsOn: [
    containerEnvironment
    storageAccount
  ]
  params: {
    environmentName: 'cae-advisor-staging-5c470205'
    storageAccountName: 'stadvisorstaging5c4702'
    storageAccountKey: storageForFiles.listKeys().keys[0].value
  }
}

module containerApp './modules/container-app.bicep' = {
  name: 'container-app'
  scope: rg
  dependsOn: [
    containerEnvironmentStorage
  ]
  params: {
    name: 'ca-advisor-staging-5c4702'
    location: location
    tags: tags
    environmentId: containerEnvironment.outputs.id
    identityId: managedIdentity.outputs.id
    registryServer: containerRegistry.outputs.loginServer
    keyVaultUri: keyVault.outputs.vaultUri
    applicationInsightsConnectionString: applicationInsights.outputs.connectionString
    databaseHost: postgresql.outputs.fullyQualifiedDomainName
    databaseName: 'student_advisor'
    databaseUser: postgresAdministratorLogin
    containerImage: containerImage
    webContainerImage: webContainerImage
    apiContainerImage: apiContainerImage
    allowedHost: allowedHost
    corsAllowedOrigin: corsAllowedOrigin
    customDomainName: customDomainName
    customDomainCertificateId: customDomainCertificateId
    gatewayBaseUrl: gatewayBaseUrl
  }
}

module migrationJob './modules/migration-job.bicep' = {
  name: 'migration-job'
  scope: rg
  params: {
    name: 'caj-advisor-stg-5c4702-migrate'
    location: location
    tags: tags
    environmentId: containerEnvironment.outputs.id
    identityId: managedIdentity.outputs.id
    registryServer: containerRegistry.outputs.loginServer
    keyVaultUri: keyVault.outputs.vaultUri
    databaseHost: postgresql.outputs.fullyQualifiedDomainName
    databaseName: 'student_advisor'
    databaseUser: postgresAdministratorLogin
    image: migrationJobImage == 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
      ? apiContainerImage
      : migrationJobImage
  }
}

module roleAssignments './modules/role-assignments.bicep' = {
  name: 'role-assignments'
  scope: rg
  params: {
    keyVaultResourceId: keyVault.outputs.id
    containerRegistryResourceId: containerRegistry.outputs.id
    storageAccountResourceId: storageAccount.outputs.id
    appPrincipalId: managedIdentity.outputs.principalId
    deployerObjectId: deployerObjectId
  }
}
