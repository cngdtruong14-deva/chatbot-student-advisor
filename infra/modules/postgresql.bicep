param name string
param location string
param tags object
param administratorLogin string
@secure()
param administratorLoginPassword string

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '17'
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorLoginPassword
    storage: {
      storageSizeGB: 32
    }
  }
}

resource firewallRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2025-08-01' = {
  parent: server
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource extensionAllowList 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-08-01' = {
  parent: server
  name: 'azure.extensions'
  dependsOn: [
    firewallRule
  ]
  properties: {
    value: 'uuid-ossp,pgcrypto,pg_trgm'
    source: 'user-override'
  }
}

resource requireSecureTransport 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-08-01' = {
  parent: server
  name: 'require_secure_transport'
  dependsOn: [
    extensionAllowList
  ]
  properties: {
    value: 'on'
    source: 'user-override'
  }
}

resource appDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-08-01' = {
  parent: server
  name: 'student_advisor'
  dependsOn: [
    requireSecureTransport
  ]
}

output id string = server.id
output fullyQualifiedDomainName string = server.properties.fullyQualifiedDomainName
