param name string
param location string
param tags object
param environmentId string
param identityId string
param registryServer string
param keyVaultUri string
param applicationInsightsConnectionString string
param databaseHost string
param databaseName string
param databaseUser string
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param webContainerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param apiContainerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param allowedHost string
param corsAllowedOrigin string
param customDomainName string = ''
param customDomainCertificateId string = ''
param gatewayBaseUrl string = ''

var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
// containerImage is retained for the standard two-phase CLI override. Dedicated
// image parameters let the final revision use the separate web and API images.
var effectiveWebImage = webContainerImage == placeholderImage && containerImage != placeholderImage
  ? containerImage
  : webContainerImage
var effectiveApiImage = apiContainerImage == placeholderImage && containerImage != placeholderImage
  ? containerImage
  : apiContainerImage
var isPlaceholder = effectiveWebImage == placeholderImage && effectiveApiImage == placeholderImage
var effectivePort = isPlaceholder ? 80 : 8080
var plainApiEnv = [
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
    name: 'PGSSLMODE'
    value: 'require'
  }
  {
    name: 'ALLOWED_HOSTS'
    value: allowedHost
  }
  {
    name: 'CORS_ALLOWED_ORIGINS'
    value: corsAllowedOrigin
  }
  {
    name: 'TRUSTED_PROXY_IPS'
    value: '127.0.0.1'
  }
  {
    name: 'WEB_PROXY_IP'
    value: '127.0.0.1'
  }
  {
    name: 'RAG_LLM_ENABLED'
    value: '1'
  }
  {
    name: 'RAG_LLM_PROVIDER'
    value: 'gemini'
  }
  {
    name: 'RAG_LLM_MODEL'
    value: 'gemini-3.5-flash-lite'
  }
  {
    name: 'RAG_METHOD'
    value: 'keyword'
  }
  {
    name: 'RAG_LLM_TIMEOUT_SECONDS'
    value: '12'
  }
  {
    name: 'RAG_LLM_RATE_LIMIT_RETRIES'
    value: '1'
  }
  {
    name: 'RAG_LLM_PROMPT_VERSION'
    value: 'decision_tree_stage7/1'
  }
  {
    name: 'RAG_LLM_GATEWAY_URL'
    value: gatewayBaseUrl
  }
  {
    name: 'RAG_RUNTIME_APPROVAL_PATH'
    value: '/artifacts/stage7/benchmark_v4/rag_runtime_approval_capstone_v4.signed.json'
  }
  {
    name: 'RAG_HIGH_STAKES_APPROVAL_PATH'
    value: '/artifacts/stage7/benchmark_v4/rag_high_stakes_grounded_capstone_v4.signed.json'
  }
  {
    name: 'RAG_RELEASE_RECEIPT_PATH'
    value: '/artifacts/stage7/effectivity/release_receipt.current.json'
  }
  {
    name: 'RAG_DIRECTORY'
    value: '/vectorstore'
  }
  {
    name: 'MODEL_DIRECTORY'
    value: '/artifacts/approved'
  }
  {
    name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
    value: applicationInsightsConnectionString
  }
]
var baseSecretApiEnv = [
  {
    name: 'DB_PASSWORD'
    secretRef: 'database-password'
  }
  {
    name: 'JWT_SECRET'
    secretRef: 'jwt-secret'
  }
]
var secretApiEnv = concat(baseSecretApiEnv, empty(gatewayBaseUrl)
  ? [
      {
        name: 'GEMINI_API_KEY'
        secretRef: 'gemini-api-key'
      }
    ]
  : [
      {
        name: 'RAG_LLM_GATEWAY_SECRET'
        secretRef: 'gateway-hmac'
      }
    ])

resource containerApp 'Microsoft.App/containerApps@2026-07-01' = {
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
    managedEnvironmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: effectivePort
        allowInsecure: false
        transport: 'auto'
        customDomains: empty(customDomainName) || empty(customDomainCertificateId)
          ? []
          : [
              {
                name: customDomainName
                bindingType: 'SniEnabled'
                certificateId: customDomainCertificateId
              }
            ]
      }
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
        : concat([
            {
              name: 'database-password'
              #disable-next-line no-hardcoded-env-urls
              keyVaultUrl: '${keyVaultUri}secrets/database-password'
              identity: identityId
            }
            {
              name: 'jwt-secret'
              #disable-next-line no-hardcoded-env-urls
              keyVaultUrl: '${keyVaultUri}secrets/jwt-secret'
              identity: identityId
            }
          ], empty(gatewayBaseUrl)
            ? [
                {
                  name: 'gemini-api-key'
                  #disable-next-line no-hardcoded-env-urls
                  keyVaultUrl: '${keyVaultUri}secrets/gemini-api-key'
                  identity: identityId
                }
              ]
            : [
                {
                  name: 'gateway-hmac'
                  #disable-next-line no-hardcoded-env-urls
                  keyVaultUrl: '${keyVaultUri}secrets/gemini-gateway-shared-secret'
                  identity: identityId
                }
              ])
    }
    template: {
      containers: [
        {
          name: 'web'
          image: effectiveWebImage
          command: isPlaceholder
            ? []
            : [
                '/bin/sh'
                '-c'
                'set -eu; sed "s|http://api:8000|http://127.0.0.1:8000|" /etc/nginx/nginx.conf > /tmp/nginx.conf; nginx -c /tmp/nginx.conf -g "daemon off;"'
              ]
          resources: {
            cpu: '0.25'
            memory: '0.5Gi'
          }
          probes: isPlaceholder
            ? []
            : [
                {
                  type: 'Liveness'
                  httpGet: {
                    path: '/healthz'
                    port: 8080
                  }
                  initialDelaySeconds: 5
                  periodSeconds: 10
                }
              ]
        }
        {
          name: 'api'
          image: effectiveApiImage
          resources: {
            cpu: '1'
            memory: '2Gi'
          }
          env: isPlaceholder ? [] : concat(plainApiEnv, secretApiEnv)
          volumeMounts: isPlaceholder
            ? []
            : [
                {
                  volumeName: 'runtime-files'
                  mountPath: '/vectorstore'
                }
                {
                  volumeName: 'runtime-files'
                  mountPath: '/artifacts'
                }
              ]
          probes: isPlaceholder
            ? []
            : [
                {
                  type: 'Liveness'
                  httpGet: {
                    path: '/health/live'
                    port: 8000
                  }
                  initialDelaySeconds: 10
                  periodSeconds: 15
                }
                {
                  type: 'Readiness'
                  httpGet: {
                    path: '/health/ready'
                    port: 8000
                  }
                  initialDelaySeconds: 15
                  periodSeconds: 20
                }
              ]
        }
      ]
      volumes: isPlaceholder
        ? []
        : [
            {
              name: 'runtime-files'
              storageType: 'AzureFile'
              storageName: 'runtime-files'
            }
          ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

output id string = containerApp.id
output fqdn string = containerApp.properties.configuration.ingress.fqdn
