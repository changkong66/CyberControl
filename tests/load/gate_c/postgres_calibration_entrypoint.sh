#!/bin/sh
set -eu

mkdir -p "$PGDATA"
install -o postgres -g postgres -m 0644 /run/gate-c-tls/ca.crt "$PGDATA/ca.crt"
install -o postgres -g postgres -m 0644 /run/gate-c-tls/server.crt "$PGDATA/server.crt"
install -o postgres -g postgres -m 0600 /run/gate-c-tls/server.key "$PGDATA/server.key"

exec /usr/local/bin/docker-entrypoint.sh "$@"
