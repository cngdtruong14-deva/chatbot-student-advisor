param name string
param location string
param tags object
param environmentId string
param identityId string
param keyVaultUri string
param databaseHost string
param databaseUser string

resource restoreJob 'Microsoft.App/jobs@2026-07-01' = {
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
    configuration: {
      triggerType: 'Manual'
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      replicaTimeout: 1800
      replicaRetryLimit: 0
      secrets: [
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
          name: 'postgres-restore-drill'
          image: 'postgres:17-bookworm'
          command: [
            '/bin/sh'
            '-eu'
            '/artifacts/ops/postgres_backup_restore.sh'
          ]
          resources: {
            cpu: '0.5'
            memory: '1Gi'
          }
          env: [
            {
              name: 'DB_HOST'
              value: databaseHost
            }
            {
              name: 'DB_USER'
              value: databaseUser
            }
            {
              name: 'PGPASSWORD'
              secretRef: 'database-password'
            }
            {
              name: 'PGSSLMODE'
              value: 'require'
            }
          ]
          volumeMounts: [
            {
              volumeName: 'runtime-files'
              mountPath: '/artifacts'
            }
          ]
        }
      ]
      volumes: [
        {
          name: 'runtime-files'
          storageType: 'AzureFile'
          storageName: 'runtime-files'
        }
      ]
    }
  }
}

output id string = restoreJob.id
