#!/bin/sh
# Renew the Compose Router server certificate under the existing private CA.
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SECRETS_DIR=${NEXUS_H0_SECRETS_DIR:-$ROOT_DIR/.secrets}
ENV_FILE=${NEXUS_H0_ENV_FILE:-$ROOT_DIR/.env.h0}
COMPOSE_FILE=${NEXUS_H0_COMPOSE_FILE:-$ROOT_DIR/compose.h0.yml}
CA_KEY_FILE=${NEXUS_H0_CA_KEY_FILE:-}

for tool in openssl python3 docker; do
  command -v "$tool" >/dev/null 2>&1 || { echo "$tool is required" >&2; exit 1; }
done
[ -d "$SECRETS_DIR" ] || { echo "Secrets directory not found: $SECRETS_DIR" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "Compose environment file not found: $ENV_FILE" >&2; exit 1; }
[ -f "$CA_KEY_FILE" ] && [ -f "$SECRETS_DIR/ca.crt" ] || {
  echo "Set NEXUS_H0_CA_KEY_FILE to the offline CA key; CA certificate missing in $SECRETS_DIR" >&2; exit 1;
}
python3 - "$CA_KEY_FILE" "$ROOT_DIR" <<'PY'
import os
import stat
import sys

key_path, project_dir = map(os.path.realpath, sys.argv[1:])
if os.path.commonpath((key_path, project_dir)) == project_dir:
    raise SystemExit("CA key must be stored outside the online project directory")
if stat.S_IMODE(os.stat(key_path).st_mode) != 0o600:
    raise SystemExit("CA key file permissions must be 0600")
PY
[ -f "$SECRETS_DIR/router.key" ] && [ -f "$SECRETS_DIR/router.crt" ] || {
  echo "Current Router key/certificate not found in $SECRETS_DIR" >&2; exit 1;
}

# Do not issue a replacement if the signer is already expired or its key does
# not match its certificate. Preserve at least one day of CA validity.
openssl x509 -in "$SECRETS_DIR/ca.crt" -noout -checkend 86400 >/dev/null || {
  echo "Private CA is expired or expires within 24 hours; perform a CA rotation instead" >&2
  exit 1
}
CA_KEY_FINGERPRINT=$(openssl pkey -in "$CA_KEY_FILE" -pubout -outform DER | openssl dgst -sha256)
CA_CERT_FINGERPRINT=$(openssl x509 -in "$SECRETS_DIR/ca.crt" -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256)
[ "$CA_KEY_FINGERPRINT" = "$CA_CERT_FINGERPRINT" ] || {
  echo "Private CA key does not match its certificate" >&2; exit 1;
}

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet

WORK_DIR=$(mktemp -d "$SECRETS_DIR/.router-cert-rotation.XXXXXX")
BACKUP_DIR=
MUTATING=0
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$status" -ne 0 ] && [ "$MUTATING" -eq 1 ]; then
    echo "Rotation failed after install began; restoring the previous Router certificate pair." >&2
    cp "$BACKUP_DIR/router.key" "$WORK_DIR/restore.key" &&
      cp "$BACKUP_DIR/router.crt" "$WORK_DIR/restore.crt" &&
      chmod 600 "$WORK_DIR/restore.key" "$WORK_DIR/restore.crt" &&
      mv "$WORK_DIR/restore.key" "$SECRETS_DIR/router.key" &&
      mv "$WORK_DIR/restore.crt" "$SECRETS_DIR/router.crt" || {
      echo "AUTOMATIC RESTORE FAILED; restore both files from $BACKUP_DIR before restarting Router." >&2
      }
    if [ -f "$SECRETS_DIR/router.key" ] && [ -f "$SECRETS_DIR/router.crt" ]; then
      docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
        up --detach --force-recreate router &&
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
        up --detach --wait --wait-timeout 300 web ||
        echo "Router recovery restart/health check failed; inspect Compose before serving traffic." >&2
    fi
  fi
  rm -rf "$WORK_DIR"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
openssl req -new -newkey rsa:3072 -nodes \
  -keyout "$WORK_DIR/router.key" -out "$WORK_DIR/router.csr" \
  -subj "/CN=router"
cat > "$WORK_DIR/router.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:router,DNS:localhost,IP:127.0.0.1
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
openssl x509 -req -in "$WORK_DIR/router.csr" \
  -CA "$SECRETS_DIR/ca.crt" -CAkey "$CA_KEY_FILE" \
  -set_serial "0x$(openssl rand -hex 16)" \
  -out "$WORK_DIR/router.crt" -days 90 -sha256 \
  -extfile "$WORK_DIR/router.ext"
openssl verify -CAfile "$SECRETS_DIR/ca.crt" "$WORK_DIR/router.crt" >/dev/null
openssl verify -x509_strict -CAfile "$SECRETS_DIR/ca.crt" "$WORK_DIR/router.crt" >/dev/null || {
  echo "Current private CA cannot issue a Router certificate accepted by strict TLS clients; re-bootstrap/rotate the CA." >&2
  exit 1
}
openssl x509 -in "$WORK_DIR/router.crt" -noout -checkhost router >/dev/null
openssl x509 -in "$WORK_DIR/router.crt" -noout -checkhost localhost >/dev/null
openssl x509 -in "$WORK_DIR/router.crt" -noout -checkip 127.0.0.1 >/dev/null
openssl x509 -in "$WORK_DIR/router.crt" -noout -checkend 7689600 >/dev/null || {
  echo "New Router certificate does not cover the intended 90-day validity" >&2; exit 1;
}
chmod 600 "$WORK_DIR/router.key" "$WORK_DIR/router.crt"

# Compose file-backed secrets are read at container creation, so recreate the
# Router after atomically replacing each staged file. The worker reconnects
# using the unchanged CA; the dependency chain is then health-checked end to end.
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR=$(mktemp -d "$SECRETS_DIR/router-cert-backup-$STAMP.XXXXXX")
cp "$SECRETS_DIR/router.key" "$BACKUP_DIR/router.key"
cp "$SECRETS_DIR/router.crt" "$BACKUP_DIR/router.crt"
chmod 600 "$BACKUP_DIR/router.key" "$BACKUP_DIR/router.crt"
MUTATING=1
mv "$WORK_DIR/router.key" "$SECRETS_DIR/router.key.new"
mv "$WORK_DIR/router.crt" "$SECRETS_DIR/router.crt.new"
mv "$SECRETS_DIR/router.key.new" "$SECRETS_DIR/router.key"
mv "$SECRETS_DIR/router.crt.new" "$SECRETS_DIR/router.crt"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
  up --detach --force-recreate router
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
  up --detach --wait --wait-timeout 300 web
MUTATING=0

echo "Router certificate renewed; Compose dependency chain is healthy."
echo "Previous certificate and key backup: $BACKUP_DIR"
echo "Protect or securely remove the backup after the recovery window."
