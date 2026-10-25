#!/bin/sh
# Provision local, ignored Compose credentials and a private CA for H0/H1.
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$SCRIPT_DIR"
SECRETS_DIR=$SCRIPT_DIR/.secrets
DATA_DIR=$SCRIPT_DIR/data
ENV_FILE=$SCRIPT_DIR/.env.h0

command -v openssl >/dev/null 2>&1 || { echo "openssl is required" >&2; exit 1; }
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
mkdir -m 700 "$SECRETS_DIR"
mkdir -p "$DATA_DIR/h0-router" "$DATA_DIR/h0-worker"
chmod 700 "$DATA_DIR" "$DATA_DIR/h0-router" "$DATA_DIR/h0-worker"
cp "$SCRIPT_DIR/.env.h0.example" "$ENV_FILE"
sed "s/^NEXUS_UID=.*/NEXUS_UID=$UID_VALUE/; s/^NEXUS_GID=.*/NEXUS_GID=$GID_VALUE/" \
  "$ENV_FILE" > "$ENV_FILE.tmp"
mv "$ENV_FILE.tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"

openssl rand -hex 32 > "$SECRETS_DIR/client.token"
openssl rand -hex 32 > "$SECRETS_DIR/enrollment.token"
chmod 600 "$SECRETS_DIR/client.token" "$SECRETS_DIR/enrollment.token"

# The CA private key never enters either container. Cert SANs support internal
# worker-to-router TLS and host clients using https://localhost.
openssl req -x509 -newkey rsa:3072 -nodes -days 3650 \
  -keyout "$SECRETS_DIR/ca.key" -out "$SECRETS_DIR/ca.crt" \
  -subj "/CN=NEXUS Compose H0 private CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"
chmod 600 "$SECRETS_DIR/ca.key" "$SECRETS_DIR/ca.crt"
openssl req -newkey rsa:3072 -nodes -keyout "$SECRETS_DIR/router.key" \
  -out "$SECRETS_DIR/router.csr" -subj "/CN=router"
chmod 600 "$SECRETS_DIR/router.key"
cat > "$SECRETS_DIR/router.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:router,DNS:localhost,IP:127.0.0.1,IP:172.30.240.2
EOF
openssl x509 -req -in "$SECRETS_DIR/router.csr" -CA "$SECRETS_DIR/ca.crt" \
  -CAkey "$SECRETS_DIR/ca.key" -CAcreateserial -out "$SECRETS_DIR/router.crt" \
  -days 90 -sha256 -extfile "$SECRETS_DIR/router.ext"
rm -f "$SECRETS_DIR/router.csr" "$SECRETS_DIR/router.ext" "$SECRETS_DIR/ca.srl"
chmod 600 "$SECRETS_DIR/router.crt"
chown -R "$UID_VALUE:$GID_VALUE" "$SECRETS_DIR" "$DATA_DIR"

echo "Created .env.h0 and private .secrets/ + data/ directories."
echo "Edit ATENHEA_URL and, if needed, the subnet/router address in .env.h0."
echo "If changing NEXUS_ROUTER_IP, reissue router.crt with that IP in its SAN."
echo "Keep .secrets/ca.key offline; securely back up the Router and node data."
