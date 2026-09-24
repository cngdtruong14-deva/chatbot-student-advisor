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
param image string

resource importJob 'Microsoft.App/jobs@2026-07-01' = {
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
      registries: [
        {
          server: registryServer
          identity: identityId
        }
      ]
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
          name: 'import-utt-v2'
          image: image
          command: [
            'python'
            '-u'
            '/artifacts/ops/import_utt_v2_runtime.py'
          ]
          resources: {
            cpu: '1'
            memory: '2Gi'
          }
          env: [
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
            {
              name: 'RAG_DIRECTORY'
              value: '/vectorstore'
            }
          ]
          volumeMounts: [
            {
              volumeName: 'runtime-files'
              mountPath: '/vectorstore'
            }
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

output id string = importJob.id
