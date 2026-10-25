#!/bin/sh
# Start local H0 chat: real Atenhea by default, or the deterministic mock.
set -eu
# Keep newly created files private, including SQLite and log files.
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
ATENHEA_DIR=${ATENHEA_DIR:-"$REPO_ROOT/atenhea"}
ROUTER_PORT=${NEXUS_H0_ROUTER_PORT:-18080}
UI_PORT=${NEXUS_H0_UI_PORT:-18081}
MOCK_PORT=${NEXUS_H0_MOCK_PORT:-11437}
ENGINE_MODE=${NEXUS_H0_ENGINE:-real}
STARTUP_TIMEOUT=${NEXUS_H0_STARTUP_TIMEOUT:-300}
if [ -n "${NEXUS_H0_DATA_DIR:-}" ]; then
  DATA_DIR=$NEXUS_H0_DATA_DIR
elif [ "$(uname -s)" = Darwin ]; then
  DATA_DIR=${HOME:?HOME must be set}/Library/Application\ Support/NEXUS/H0
else
  DATA_DIR=${XDG_STATE_HOME:-"${HOME:?HOME must be set}/.local/state"}/nexus-h0
fi
PY=${NEXUS_PYTHON:-"$SCRIPT_DIR/.venv/bin/python"}
ROUTER_URL=http://127.0.0.1:$ROUTER_PORT
UI_URL=http://127.0.0.1:$UI_PORT
ENGINE_URL=http://127.0.0.1:11436
MOCK_URL=http://127.0.0.1:$MOCK_PORT
ROUTER_PID=
WORKER_PID=
UI_PID=
MOCK_PID=
CLEANING_UP=0

check_port() {
  case "$2" in
    ''|*[!0-9]*) echo "$1 must be a port number." >&2; exit 2 ;;
  esac
  if [ "$2" -lt 1 ] || [ "$2" -gt 65535 ]; then
    echo "$1 must be between 1 and 65535." >&2
    exit 2
  fi
}
check_port NEXUS_H0_ROUTER_PORT "$ROUTER_PORT"
check_port NEXUS_H0_UI_PORT "$UI_PORT"
check_port NEXUS_H0_MOCK_PORT "$MOCK_PORT"
if [ "$ROUTER_PORT" = "$UI_PORT" ] || [ "$ROUTER_PORT" = "$MOCK_PORT" ] || \
  [ "$UI_PORT" = "$MOCK_PORT" ]; then
  echo "Router, UI and mock ports must be distinct." >&2
  exit 2
fi

case "$ENGINE_MODE" in
  real|mock) ;;
  *) echo "NEXUS_H0_ENGINE must be 'real' or 'mock'." >&2; exit 2 ;;
esac
case "$STARTUP_TIMEOUT" in
  ''|*[!0-9]*) echo "NEXUS_H0_STARTUP_TIMEOUT must be a positive number of seconds." >&2; exit 2 ;;
esac
[ "$STARTUP_TIMEOUT" -gt 0 ] || {
  echo "NEXUS_H0_STARTUP_TIMEOUT must be greater than zero." >&2
  exit 2
}

cd "$SCRIPT_DIR"
command -v curl >/dev/null 2>&1 || {
  echo "curl is required for local H0 readiness checks." >&2
  exit 1
}
CUSTOM_DATA_DIR=${NEXUS_H0_DATA_DIR:+1}
mkdir -p "$DATA_DIR"
if [ -z "$CUSTOM_DATA_DIR" ]; then
  chmod 700 "$DATA_DIR"
else
  echo "Using custom data directory: $DATA_DIR (ensure it is private; launcher will not change its permissions)." >&2
fi
LOG_DIR=$DATA_DIR/logs
mkdir -p "$LOG_DIR"
if [ -z "$CUSTOM_DATA_DIR" ]; then chmod 700 "$LOG_DIR"; fi
if [ -n "${NEXUS_PYTHON:-}" ]; then
  "$PY" -c 'import cryptography; assert cryptography.__version__ == "50.0.2"' 2>/dev/null || {
    echo "NEXUS_PYTHON must provide cryptography==50.0.2." >&2
    exit 1
  }
else
  if [ ! -x "$PY" ]; then
    python3 -m venv .venv
  fi
  "$PY" -c 'import cryptography; assert cryptography.__version__ == "50.0.2"' 2>/dev/null || \
    .venv/bin/pip install --quiet -r "$SCRIPT_DIR/requirements-h0.txt"
fi

models_ready() {
  "$PY" -c 'import json,sys
try:
    data=json.loads(sys.argv[1]).get("data")
except (ValueError, AttributeError):
    sys.exit(1)
sys.exit(0 if isinstance(data,list) and any(isinstance(x,dict) and isinstance(x.get("id"),str) and x["id"].strip() for x in data) else 1)' "$1" >/dev/null 2>&1
}

job_running() {
  for job_pid in $(jobs -pr); do
    [ "$job_pid" = "$1" ] && return 0
  done
  return 1
}

stop_child() {
  child_pid=$1
  [ -n "$child_pid" ] || return 0
  kill "$child_pid" 2>/dev/null || true
  wait "$child_pid" 2>/dev/null || true
}

cleanup() {
  [ "$CLEANING_UP" -eq 0 ] || return 0
  CLEANING_UP=1
  trap - EXIT INT TERM
  stop_child "$UI_PID"
  stop_child "$WORKER_PID"
  stop_child "$ROUTER_PID"
  stop_child "$MOCK_PID"
}
trap cleanup EXIT INT TERM

# Fail early on occupied ports instead of waiting for child processes to time
# out during readiness. Any HTTP response means something owns the port.
router_http_code=$(curl -sS -o /dev/null -w '%{http_code}' -m 1 \
  "$ROUTER_URL/health" 2>/dev/null || true)
if [ "$router_http_code" != 000 ]; then
  echo "A service already answers at $ROUTER_URL (HTTP $router_http_code); stop it or choose another NEXUS_H0_ROUTER_PORT." >&2
  exit 1
fi
ui_http_code=$(curl -sS -o /dev/null -w '%{http_code}' -m 1 \
  "$UI_URL/" 2>/dev/null || true)
if [ "$ui_http_code" != 000 ]; then
  echo "A service already answers at $UI_URL (HTTP $ui_http_code); stop it or choose another NEXUS_H0_UI_PORT." >&2
  exit 1
fi

if [ "$ENGINE_MODE" = mock ]; then
  if curl -sS -m 1 "$MOCK_URL/v1/models" >/dev/null 2>&1; then
    echo "A service already answers at $MOCK_URL; choose another NEXUS_H0_MOCK_PORT." >&2
    exit 1
  fi
  echo ">> starting deterministic mock engine at $MOCK_URL"
  "$PY" "$SCRIPT_DIR/mock_atenea.py" --port "$MOCK_PORT" >"$LOG_DIR/mock-local.log" 2>&1 &
  MOCK_PID=$!
  ENGINE_URL=$MOCK_URL
else
  engine_http_code=$(curl -sS -o /dev/null -w '%{http_code}' -m 3 \
    "$ENGINE_URL/v1/models" 2>/dev/null || true)
  engine_models=$(curl -fsS -m 3 "$ENGINE_URL/v1/models" 2>/dev/null || true)
  case "$engine_http_code" in
    2??)
    echo ">> waiting for existing Atenhea engine to announce a model"
    i=0
    while [ "$i" -lt "$STARTUP_TIMEOUT" ] && ! models_ready "$engine_models"; do
      i=$((i + 1))
      sleep 1
      engine_models=$(curl -sS -m 3 "$ENGINE_URL/v1/models" 2>/dev/null || true)
    done
    if ! models_ready "$engine_models"; then
      echo "Atenhea answered at $ENGINE_URL but announced no model within ${STARTUP_TIMEOUT}s; not starting a second engine." >&2
      exit 1
    fi
    echo ">> reusing Atenhea engine at $ENGINE_URL"
    ;;
    000)
    if curl -fsS -m 1 http://127.0.0.1:11434/v1/models >/dev/null 2>&1; then
      echo "Atenhea agent proxy is responding on :11434, but its H0 engine on :11436 has no model." >&2
      exit 1
    fi
    ;;
    *)
      echo "A service answered $ENGINE_URL/v1/models with HTTP $engine_http_code; refusing to launch another engine." >&2
      exit 1
      ;;
  esac

  if [ "$engine_http_code" = 000 ]; then
    LAUNCHER=$ATENHEA_DIR/start-athenea.sh
    MODEL_DIR=$ATENHEA_DIR/models/gemma4-e2b-trainable
    MODEL_BUNDLE=$ATENHEA_DIR/models/athenea-e2b.nram
    if [ ! -x "$LAUNCHER" ]; then
      echo "Atenhea launcher is missing or not executable: $LAUNCHER" >&2
      exit 1
    fi
    if [ ! -d "$MODEL_DIR" ] || [ ! -f "$MODEL_BUNDLE" ]; then
      echo "Atenhea H0 model assets are missing from this clone:" >&2
      echo "  model directory: $MODEL_DIR" >&2
      echo "  NRAM bundle:     $MODEL_BUNDLE" >&2
      echo "Install/setup the real H0 model, or use NEXUS_H0_ENGINE=mock for the local mock path." >&2
      exit 1
    fi
    echo ">> starting Atenhea from $ATENHEA_DIR"
    ATENHEA_PID=$(cd "$ATENHEA_DIR" && {
      nohup ./start-athenea.sh >"$LOG_DIR/atenea-local.log" 2>&1 </dev/null &
      echo $!
    })
    i=0
    while [ "$i" -lt "$STARTUP_TIMEOUT" ]; do
      engine_models=$(curl -sS -m 3 "$ENGINE_URL/v1/models" 2>/dev/null || true)
      if models_ready "$engine_models"; then break; fi
      if ! kill -0 "$ATENHEA_PID" 2>/dev/null; then
        echo "Atenhea exited during startup; inspect $LOG_DIR/atenea-local.log" >&2
        tail -n 20 "$LOG_DIR/atenea-local.log" >&2 || true
        exit 1
      fi
      i=$((i + 1))
      sleep 1
    done
    if ! models_ready "${engine_models:-}"; then
      echo "Atenhea did not announce a model within ${STARTUP_TIMEOUT}s; inspect $LOG_DIR/atenea-local.log" >&2
      exit 1
    fi
  fi
fi

"$PY" router.py --port "$ROUTER_PORT" --dir "$DATA_DIR" >"$LOG_DIR/router-local.log" 2>&1 &
ROUTER_PID=$!
"$PY" worker_agent.py --router "$ROUTER_URL" --atenea "$ENGINE_URL" \
  --node-dir "$DATA_DIR/node" >"$LOG_DIR/worker-local.log" 2>&1 &
WORKER_PID=$!
NEXUS_H0_ROUTER_URL="$ROUTER_URL" NEXUS_H0_UI_PORT="$UI_PORT" \
  "$PY" "$REPO_ROOT/nexus-web/h0_local.py" >"$LOG_DIR/ui-local.log" 2>&1 &
UI_PID=$!

i=0
models=
while [ "$i" -lt "$STARTUP_TIMEOUT" ]; do
  if ! job_running "$ROUTER_PID"; then
    echo "Router exited during startup; inspect $LOG_DIR/router-local.log" >&2
    exit 1
  fi
  if ! job_running "$WORKER_PID"; then
    echo "Worker exited during model discovery/calibration; inspect $LOG_DIR/worker-local.log" >&2
    exit 1
  fi
  if ! job_running "$UI_PID"; then
    echo "UI exited during startup; inspect $LOG_DIR/ui-local.log" >&2
    exit 1
  fi
  if [ -n "$MOCK_PID" ] && ! job_running "$MOCK_PID"; then
    echo "Mock engine exited during startup; inspect $LOG_DIR/mock-local.log" >&2
    exit 1
  fi
  if curl -fsS -m 2 "$ROUTER_URL/ready" >/dev/null 2>&1; then
    models=$(curl -fsS -m 2 "$ROUTER_URL/v1/models" 2>/dev/null || true)
    if models_ready "$models"; then break; fi
  fi
  i=$((i + 1))
  sleep 1
done
if ! models_ready "${models:-}"; then
  echo "Router/worker did not announce a model within ${STARTUP_TIMEOUT}s; inspect $LOG_DIR/router-local.log and worker-local.log" >&2
  exit 1
fi

ui_models=
i=0
while [ "$i" -lt 30 ]; do
  ui_models=$(curl -fsS -m 2 "$UI_URL/v1/models" 2>/dev/null || true)
  if models_ready "$ui_models"; then break; fi
  if ! job_running "$UI_PID"; then
    echo "UI exited during startup; inspect $LOG_DIR/ui-local.log" >&2
    exit 1
  fi
  i=$((i + 1))
  sleep 1
done
if ! models_ready "${ui_models:-}"; then
  echo "H0 UI did not become ready at $UI_URL; inspect $LOG_DIR/ui-local.log" >&2
  exit 1
fi

echo "NEXUS H0 ready: $UI_URL"
echo "Engine: $ENGINE_MODE ($ENGINE_URL)"
if [ "$ENGINE_MODE" = real ]; then
  echo "Press Ctrl-C to stop Router, worker and UI."
  echo "Atenhea remains running after the H0 stack stops."
else
  echo "Press Ctrl-C to stop Router, worker, UI and mock engine."
fi
wait "$UI_PID"
