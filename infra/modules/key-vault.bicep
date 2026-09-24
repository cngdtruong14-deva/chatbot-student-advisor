param name string
param location string
param tags object
@secure()
param databasePassword string
@secure()
param jwtSecret string

resource vault 'Microsoft.KeyVault/vaults@2026-05-15' = {
  name: name
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

resource databasePasswordSecret 'Microsoft.KeyVault/vaults/secrets@2026-05-15' = {
  parent: vault
  name: 'database-password'
  properties: {
    value: databasePassword
  }
}

resource jwtSecretResource 'Microsoft.KeyVault/vaults/secrets@2026-05-15' = {
  parent: vault
  name: 'jwt-secret'
  properties: {
    value: jwtSecret
  }
}

output id string = vault.id
output vaultUri string = vault.properties.vaultUri
