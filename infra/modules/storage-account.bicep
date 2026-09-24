param name string
param location string
param tags object

resource storage 'Microsoft.Storage/storageAccounts@2026-06-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
  }
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2026-06-01' = {
  parent: storage
  name: 'default'
}

resource runtimeFiles 'Microsoft.Storage/storageAccounts/fileServices/shares@2026-06-01' = {
  parent: fileService
  name: 'runtime-files'
  properties: {
    shareQuota: 100
    enabledProtocols: 'SMB'
  }
}

output id string = storage.id
