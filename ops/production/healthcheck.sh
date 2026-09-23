#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 /absolute/path/.env.production" >&2
  exit 2
fi
ENV_FILE=$1
COMPOSE_FILE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/production.compose.yaml
test -f "$ENV_FILE"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T web \
  wget -q -O - http://127.0.0.1:8080/health/ready
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).read().decode())"
