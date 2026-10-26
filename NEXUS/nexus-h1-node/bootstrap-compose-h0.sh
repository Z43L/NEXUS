#!/bin/sh
# Provision local, ignored Compose credentials and a private CA for H0/H1.
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$SCRIPT_DIR"
SECRETS_DIR=$SCRIPT_DIR/.secrets
DATA_DIR=$SCRIPT_DIR/data
ENV_FILE=$SCRIPT_DIR/.env.h0
LOCK_DIR=$SCRIPT_DIR/.bootstrap-h0.lock
CA_KEY_OUT=${NEXUS_H0_CA_KEY_OUT:-}

case "$CA_KEY_OUT" in
  /*) ;;
  *) echo "Set NEXUS_H0_CA_KEY_OUT to an absolute path on protected offline media (CI may use runner temp)." >&2; exit 1 ;;
esac
[ -d "$(dirname -- "$CA_KEY_OUT")" ] || { echo "CA key destination directory must already exist." >&2; exit 1; }
CA_KEY_OUT_DIR=$(CDPATH= cd -- "$(dirname -- "$CA_KEY_OUT")" && pwd -P)
CA_KEY_OUT=$CA_KEY_OUT_DIR/$(basename -- "$CA_KEY_OUT")
[ ! -e "$CA_KEY_OUT" ] && [ ! -L "$CA_KEY_OUT" ] || { echo "Refusing to overwrite CA key destination: $CA_KEY_OUT" >&2; exit 1; }
case "$CA_KEY_OUT_DIR/" in
  "$SCRIPT_DIR/"*) echo "CA private key destination must be outside the online project directory." >&2; exit 1 ;;
esac

command -v openssl >/dev/null 2>&1 || { echo "openssl is required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }
UID_VALUE=$(id -u)
GID_VALUE=$(id -g)
if [ "$(uname -s)" = Linux ] && [ "$UID_VALUE" -eq 0 ]; then
  echo "Run this script as the unprivileged deployment user, not root." >&2
  exit 1
fi
if [ -e "$SECRETS_DIR" ] || [ -e "$ENV_FILE" ]; then
  echo "Refusing to overwrite existing .secrets/ or .env.h0; back them up first." >&2
  exit 1
fi
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another H0 bootstrap is running (or .bootstrap-h0.lock needs manual cleanup)." >&2
  exit 1
fi
STAGE_DIR=
ENV_STAGE=$SCRIPT_DIR/.env.h0.tmp.$$
PUBLISHED_SECRETS=0
PUBLISHED_ENV=0
PUBLISHED_CA_KEY=0
cleanup() {
  status=$?
  trap - 0
  if [ -n "$STAGE_DIR" ]; then rm -rf "$STAGE_DIR"; fi
  rm -rf "$LOCK_DIR"
  rm -f "$ENV_STAGE"
  if [ "$status" -ne 0 ]; then
    if [ "$PUBLISHED_SECRETS" -eq 1 ]; then rm -rf "$SECRETS_DIR"; fi
    if [ "$PUBLISHED_ENV" -eq 1 ]; then rm -f "$ENV_FILE"; fi
    if [ "$PUBLISHED_CA_KEY" -eq 1 ]; then rm -f "$CA_KEY_OUT"; fi
  fi
  exit "$status"
}
trap cleanup 0
trap 'exit 1' HUP INT TERM
STAGE_DIR=$(mktemp -d "$SCRIPT_DIR/.secrets.tmp.XXXXXX")
chmod 700 "$STAGE_DIR"
mkdir -p "$DATA_DIR/h0-router" "$DATA_DIR/h0-worker" "$DATA_DIR/h0-valkey"
chmod 700 "$DATA_DIR" "$DATA_DIR/h0-router" "$DATA_DIR/h0-worker" "$DATA_DIR/h0-valkey"
cp "$SCRIPT_DIR/.env.h0.example" "$ENV_STAGE"
sed "s/^NEXUS_UID=.*/NEXUS_UID=$UID_VALUE/; s/^NEXUS_GID=.*/NEXUS_GID=$GID_VALUE/" \
  "$ENV_STAGE" > "$ENV_STAGE.rendered"
mv "$ENV_STAGE.rendered" "$ENV_STAGE"
chmod 600 "$ENV_STAGE"

openssl rand -hex 32 > "$STAGE_DIR/client.token"
openssl rand -hex 32 > "$STAGE_DIR/enrollment.token"
openssl rand -hex 32 > "$STAGE_DIR/api.token"
openssl rand -hex 32 > "$STAGE_DIR/atenea_api.key"
openssl rand -hex 32 > "$STAGE_DIR/valkey.password"
chmod 600 "$STAGE_DIR/client.token" "$STAGE_DIR/enrollment.token" "$STAGE_DIR/api.token" "$STAGE_DIR/atenea_api.key" "$STAGE_DIR/valkey.password"
python3 - "$STAGE_DIR/valkey.password" "$STAGE_DIR/valkey.conf" "$STAGE_DIR/redis.url" "$STAGE_DIR/api_users.json" <<'PY'
import json
import os
import sys

password_path, config_path, url_path, users_path = sys.argv[1:]
password = open(password_path, encoding="utf-8").read().strip()
for path, content in (
    (config_path, f"""port 6379
bind 0.0.0.0
protected-mode yes
requirepass {password}
appendonly yes
appendfsync everysec
maxmemory-policy noeviction
dir /data
"""),
    (url_path, f"redis://:{password}@valkey:6379/0\n"),
    (users_path, json.dumps({"version": 1, "users": []}, indent=2, sort_keys=True) + "\n"),
):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(content)
PY
python3 - "$STAGE_DIR/api.token" "$STAGE_DIR/api_clients.json" <<'PY'
import hashlib
import json
import os
import sys

token_path, registry_path = sys.argv[1:]
token = open(token_path, encoding="utf-8").read().strip()
registry = {
    "version": 1,
    "clients": [{
        "client_id": "local-ui",
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "scopes": ["auth:session", "inference", "jobs:read", "models:read"],
        "rate_limit_per_minute": 60,
    }],
}
fd = os.open(registry_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as output:
    json.dump(registry, output, indent=2, sort_keys=True)
    output.write("\n")
PY
chmod 600 "$STAGE_DIR/api_clients.json"

# The CA private key never enters either container. Cert SANs support internal
# worker-to-router TLS and host clients using https://localhost.
openssl req -x509 -newkey rsa:3072 -nodes -days 3650 \
  -keyout "$STAGE_DIR/ca.key" -out "$STAGE_DIR/ca.crt" \
  -subj "/CN=NEXUS Compose H0 private CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash" \
  -addext "authorityKeyIdentifier=keyid:always"
chmod 600 "$STAGE_DIR/ca.key" "$STAGE_DIR/ca.crt"
openssl req -newkey rsa:3072 -nodes -keyout "$STAGE_DIR/router.key" \
  -out "$STAGE_DIR/router.csr" -subj "/CN=router"
chmod 600 "$STAGE_DIR/router.key"
cat > "$STAGE_DIR/router.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:router,DNS:localhost,IP:127.0.0.1
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
openssl x509 -req -in "$STAGE_DIR/router.csr" -CA "$STAGE_DIR/ca.crt" \
  -CAkey "$STAGE_DIR/ca.key" -CAcreateserial -out "$STAGE_DIR/router.crt" \
  -days 90 -sha256 -extfile "$STAGE_DIR/router.ext"
rm -f "$STAGE_DIR/router.csr" "$STAGE_DIR/router.ext" "$STAGE_DIR/ca.srl"
chmod 600 "$STAGE_DIR/router.crt"
openssl verify -x509_strict -CAfile "$STAGE_DIR/ca.crt" "$STAGE_DIR/router.crt" >/dev/null
chown -R "$UID_VALUE:$GID_VALUE" "$STAGE_DIR" "$DATA_DIR"

# Publish only complete files. The lock makes the existence check and final
# moves exclusive for concurrent invocations of this script.
if [ -e "$SECRETS_DIR" ] || [ -e "$ENV_FILE" ]; then
  echo "Bootstrap outputs appeared while provisioning; refusing to overwrite." >&2
  exit 1
fi
python3 - "$STAGE_DIR/ca.key" "$CA_KEY_OUT" <<'PY'
import os
import shutil
import sys

source, destination = sys.argv[1:]
fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    with os.fdopen(fd, "wb") as output, open(source, "rb") as key:
        shutil.copyfileobj(key, output)
except BaseException:
    try:
        os.unlink(destination)
    except FileNotFoundError:
        pass
    raise
PY
PUBLISHED_CA_KEY=1
chmod 600 "$CA_KEY_OUT"
rm -f "$STAGE_DIR/ca.key"
mv "$ENV_STAGE" "$ENV_FILE"
PUBLISHED_ENV=1
mv "$STAGE_DIR" "$SECRETS_DIR"
PUBLISHED_SECRETS=1

echo "Created .env.h0 and private .secrets/ + data/ directories."
echo "Edit .env.h0 and set ATENHEA_URL to the Atenhea engine endpoint."
echo "The API client token is in .secrets/api.token; the Router token stays server-side."
echo "The Atenhea service credential is in .secrets/atenea_api.key; provision it on the engine host over a protected channel."
echo "Compose assigns a private bridge address automatically; Router TLS uses the internal DNS name router."
echo "CA private key written outside the project at: $CA_KEY_OUT"
echo "Remove the online copy from CI/test temp after checks; back up offline media securely."
