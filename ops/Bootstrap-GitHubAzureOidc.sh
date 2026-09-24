#!/usr/bin/env bash
set -Eeuo pipefail

# Run once from an authenticated Azure Cloud Shell. This creates a deployment-only
# workload identity for GitHub Actions. It creates no password or client secret.

SUBSCRIPTION_ID="4e31f399-0291-49d5-b4bb-4a389a6be537"
RESOURCE_GROUP="rg-advisor-staging-5c4702"
IDENTITY_NAME="id-advisor-github-deploy-5c4702"
ACR_NAME="cradvisorstaging5c4702"
CONTAINER_APP="ca-advisor-staging-5c4702"
GITHUB_REPOSITORY="cngdtruong14-deva/chatbot-student-advisor"
FEDERATED_CREDENTIAL="github-main"
# This repository uses GitHub's immutable-ID OIDC subject customization. The
# numeric owner/repository IDs prevent a renamed or re-created repository from
# inheriting this Azure trust relationship. Override only when GitHub reports a
# different verified subject claim in the azure/login log.
GITHUB_OIDC_SUBJECT="${GITHUB_OIDC_SUBJECT:-repo:cngdtruong14-deva@245412666/chatbot-student-advisor@1382853620:ref:refs/heads/main}"

az account set --subscription "$SUBSCRIPTION_ID"
TENANT_ID="$(az account show --query tenantId -o tsv)"

if ! az identity show --resource-group "$RESOURCE_GROUP" --name "$IDENTITY_NAME" >/dev/null 2>&1; then
  az identity create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$IDENTITY_NAME" \
    --location eastasia \
    --output none
fi

CLIENT_ID="$(az identity show --resource-group "$RESOURCE_GROUP" --name "$IDENTITY_NAME" --query clientId -o tsv)"
PRINCIPAL_ID="$(az identity show --resource-group "$RESOURCE_GROUP" --name "$IDENTITY_NAME" --query principalId -o tsv)"

if ! az identity federated-credential show \
  --resource-group "$RESOURCE_GROUP" \
  --identity-name "$IDENTITY_NAME" \
  --name "$FEDERATED_CREDENTIAL" >/dev/null 2>&1; then
  az identity federated-credential create \
    --resource-group "$RESOURCE_GROUP" \
    --identity-name "$IDENTITY_NAME" \
    --name "$FEDERATED_CREDENTIAL" \
    --issuer "https://token.actions.githubusercontent.com" \
    --subject "$GITHUB_OIDC_SUBJECT" \
    --audiences "api://AzureADTokenExchange" \
    --output none
else
  az identity federated-credential update \
    --resource-group "$RESOURCE_GROUP" \
    --identity-name "$IDENTITY_NAME" \
    --name "$FEDERATED_CREDENTIAL" \
    --issuer "https://token.actions.githubusercontent.com" \
    --subject "$GITHUB_OIDC_SUBJECT" \
    --audiences "api://AzureADTokenExchange" \
    --output none
fi

ACR_ID="$(az acr show --resource-group "$RESOURCE_GROUP" --name "$ACR_NAME" --query id -o tsv)"
APP_ID="$(az containerapp show --resource-group "$RESOURCE_GROUP" --name "$CONTAINER_APP" --query id -o tsv)"

ensure_role() {
  local role="$1"
  local scope="$2"
  local count
  count="$(az role assignment list \
    --assignee-object-id "$PRINCIPAL_ID" \
    --scope "$scope" \
    --query "[?roleDefinitionName=='${role}'] | length(@)" \
    -o tsv)"
  if [ "$count" = "0" ]; then
    az role assignment create \
      --assignee-object-id "$PRINCIPAL_ID" \
      --assignee-principal-type ServicePrincipal \
      --role "$role" \
      --scope "$scope" \
      --output none
  fi
}

ensure_role "AcrPush" "$ACR_ID"
ensure_role "Reader" "$ACR_ID"
ensure_role "Container Apps Contributor" "$APP_ID"

cat <<EOF
OIDC_BOOTSTRAP_PASS

Create these GitHub repository Actions variables:
AZURE_CLIENT_ID=$CLIENT_ID
AZURE_TENANT_ID=$TENANT_ID
AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID

No client secret was created.
Federated subject: $GITHUB_OIDC_SUBJECT
EOF
