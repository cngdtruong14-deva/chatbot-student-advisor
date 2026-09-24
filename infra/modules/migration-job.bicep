param name string
param location string
param tags object
param environmentId string
param identityId string
param registryServer string
param keyVaultUri string
param databaseHost string
param databaseName string
param databaseUser string
param image string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var isPlaceholder = image == placeholderImage

resource migrationJob 'Microsoft.App/jobs@2026-07-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      replicaTimeout: 1800
      replicaRetryLimit: 0
      registries: isPlaceholder
        ? []
        : [
            {
              server: registryServer
              identity: identityId
            }
          ]
      secrets: isPlaceholder
        ? []
        : [
            {
              name: 'database-password'
              #disable-next-line no-hardcoded-env-urls
              keyVaultUrl: '${keyVaultUri}secrets/database-password'
              identity: identityId
            }
          ]
    }
    template: {
      containers: [
        {
          name: 'alembic-migrate'
          image: image
          command: isPlaceholder
            ? []
            : [
                '/bin/sh'
                '-c'
                'cd /app && alembic upgrade head'
              ]
          resources: {
            cpu: '0.5'
            memory: '1Gi'
          }
          env: isPlaceholder
            ? []
            : [
                {
                  name: 'APP_ENV'
                  value: 'production'
                }
                {
                  name: 'DB_HOST'
                  value: databaseHost
                }
                {
                  name: 'DB_NAME'
                  value: databaseName
                }
                {
                  name: 'DB_USER'
                  value: databaseUser
                }
                {
                  name: 'DB_PASSWORD'
                  secretRef: 'database-password'
                }
                {
                  name: 'PGSSLMODE'
                  value: 'require'
                }
              ]
        }
      ]
    }
  }
}

output id string = migrationJob.id
