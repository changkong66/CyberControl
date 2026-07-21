#!/usr/bin/env bash
set -euo pipefail

KCADM=/opt/keycloak/bin/kcadm.sh
SERVER_URL="${KEYCLOAK_ADMIN_SERVER_URL:-http://localhost:8080}"
CONFIG_PATH=/tmp/kcadm.config

"$KCADM" config credentials \
  --config "$CONFIG_PATH" \
  --server "$SERVER_URL" \
  --realm master \
  --user "$KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME" \
  --password "$KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD"

"$KCADM" update users/profile \
  --config "$CONFIG_PATH" \
  -r cybercontrol \
  -f /config/user-profile.json
