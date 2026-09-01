#!/bin/sh
set -eu

tls_runtime_dir=/run/postgresql/gate-c-tls
install -d -o postgres -g postgres -m 0700 "$tls_runtime_dir"
install -o postgres -g postgres -m 0644 /run/gate-c-tls/ca.crt "$tls_runtime_dir/ca.crt"
install -o postgres -g postgres -m 0644 /run/gate-c-tls/server.crt "$tls_runtime_dir/server.crt"
install -o postgres -g postgres -m 0600 /run/gate-c-tls/server.key "$tls_runtime_dir/server.key"

exec /usr/local/bin/docker-entrypoint.sh "$@"
