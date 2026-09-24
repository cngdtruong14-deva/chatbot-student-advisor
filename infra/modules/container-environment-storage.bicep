param environmentName string
param storageAccountName string
@secure()
param storageAccountKey string

// This is deliberately deployed by a separate nested deployment after the
// managed environment reaches a terminal state.  East Asia intermittently
// classified a same-template child write as Express before the workload
// profile was fully persisted, even though the environment itself succeeded.
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}

resource runtimeFilesStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: environment
  name: 'runtime-files'
  properties: {
    azureFile: {
      accountName: storageAccountName
      accountKey: storageAccountKey
      shareName: 'runtime-files'
      accessMode: 'ReadWrite'
    }
  }
}

output id string = runtimeFilesStorage.id
