param name string
param location string
param tags object
param workspaceCustomerId string
@secure()
param workspaceSharedKey string
param infrastructureSubnetId string

// Use the documented GA API for a workload-profiles environment. The later
// Express API in East Asia silently selected the Express variant, which cannot
// host an Azure Files storage definition.
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    // Azure Files mounts are unavailable in the East Asia Express environment.
    // Supplying a delegated custom VNet selects the standard workload-profiles
    // environment. Keep only Consumption because this Azure for Students
    // subscription has a zero-core ceiling for every D4 profile declaration.
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    vnetConfiguration: {
      infrastructureSubnetId: infrastructureSubnetId
      internal: false
    }
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspaceCustomerId
        sharedKey: workspaceSharedKey
      }
    }
  }
}

output id string = environment.id
