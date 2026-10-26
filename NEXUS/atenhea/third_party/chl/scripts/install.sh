#!/usr/bin/env bash
# CHL Full Installation Script
# Instala CHL desde cero: dependencias, compilación, MCP config, reglas de agente.
#
# Uso:
#   bash scripts/install.sh
#   bash scripts/install.sh --home /Users/davidmoreno --persist ~/.codex/chl-memory.log
#
# Un agente puede ejecutar este script paso a paso siguiendo INSTALL.md.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

# ─── Args ─────────────────────────────────────────────────

HOME_DIR="${HOME:-$HOME}"
PERSIST_PATH=""
NODE_BIN="node"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --home) HOME_DIR="$2"; shift 2 ;;
        --persist) PERSIST_PATH="$2"; shift 2 ;;
        --node) NODE_BIN="$2"; shift 2 ;;
        *) shift ;;
    esac
done

PERSIST_PATH="${PERSIST_PATH:-$HOME_DIR/.codex/chl-memory.log}"
CODE_CONFIG="$HOME_DIR/.codex/config.toml"
CLAUDE_CONFIG="$HOME_DIR/.claude/mcp.json"

echo -e "${BOLD}═══════════════════════════════════════════${NC}"
echo -e "${BOLD}  CHL Memory — Full Installation${NC}"
echo -e "${BOLD}═══════════════════════════════════════════${NC}"
echo ""
echo -e "  Home:     ${GREEN}$HOME_DIR${NC}"
echo -e "  Proyecto: ${GREEN}$PROJECT_DIR${NC}"
echo -e "  Memoria:  ${GREEN}$PERSIST_PATH${NC}"
echo ""

# ─── Paso 1: Verificar requisitos ─────────────────────────

echo -e "${BOLD}[1/6] Verificando requisitos...${NC}"

if ! command -v "$NODE_BIN" &>/dev/null; then
    echo -e "${RED}✗ Node no encontrado. Instálalo: https://nodejs.org${NC}"
    exit 1
fi

NODE_VERSION=$("$NODE_BIN" --version | sed 's/v//' | cut -d. -f1)
if [ "$NODE_VERSION" -lt 24 ]; then
    echo -e "${YELLOW}⚠ Node $NODE_VERSION < 24. Puede fallar.${NC}"
fi

if ! command -v clang++ &>/dev/null; then
    echo -e "${RED}✗ clang++ no encontrado. Instala Xcode CLI: xcode-select --install${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Node $("$NODE_BIN" --version) + clang++ $(clang++ --version | head -1 | awk '{print $NF}')${NC}"

# ─── Paso 2: Dependencias ────────────────────────────────

echo -e "${BOLD}[2/6] Instalando dependencias npm...${NC}"
cd "$PROJECT_DIR"

if [ ! -d "node_modules" ]; then
    npm install --no-audit --no-fund 2>&1 | tail -1
else
    echo -e "${GREEN}✓ node_modules ya existe${NC}"
fi

# ─── Paso 3: Compilar addon nativo ────────────────────────

echo -e "${BOLD}[3/6] Compilando motor C++...${NC}"

if [ -f "build/Release/chl_addon.node" ]; then
    echo -e "${GREEN}✓ Addon ya compilado${NC}"
else
    "$NODE_BIN" scripts/build-native.js 2>&1 | tail -3
fi

# Verificar
if "$NODE_BIN" -e "const {NativeCHL}=require('$PROJECT_DIR/src/native'); const c=new NativeCHL({persistPath:null}); process.exit(c.fallback?1:0)" 2>/dev/null; then
    echo -e "${GREEN}✓ Motor C++ nativo verificado${NC}"
else
    echo -e "${RED}✗ El motor C++ no carga. Revisa clang++ y node-gyp.${NC}"
    exit 1
fi

# ─── Paso 4: Archivo de persistencia ──────────────────────

echo -e "${BOLD}[4/6] Creando archivo de persistencia...${NC}"

PERSIST_DIR="$(dirname "$PERSIST_PATH")"
mkdir -p "$PERSIST_DIR"
touch "$PERSIST_PATH"
echo -e "${GREEN}✓ $PERSIST_PATH${NC}"

# ─── Paso 5: Configurar MCP ───────────────────────────────

echo -e "${BOLD}[5/6] Configurando MCP en agentes...${NC}"

# Codex
if [ -f "$CODE_CONFIG" ]; then
    if grep -q "chl-memory" "$CODE_CONFIG" 2>/dev/null; then
        echo -e "${GREEN}✓ Codex MCP ya configurado${NC}"
    else
        cat >> "$CODE_CONFIG" << EOF

[mcp_servers.chl-memory]
command = "$NODE_BIN"
args = ["$PROJECT_DIR/src/mcp-server.js"]
startup_timeout_sec = 90
enabled = true

[mcp_servers.chl-memory.env]
CHL_PERSIST_PATH = "$PERSIST_PATH"
CHL_AUTO_REMEMBER = "smart"
EOF
        echo -e "${GREEN}✓ Codex MCP configurado en config.toml${NC}"
    fi
else
    echo -e "${YELLOW}○ Codex no detectado (~/.codex/config.toml no existe)${NC}"
fi

# Claude Code
CLAUDE_DIR="$HOME_DIR/.claude"
if command -v claude &>/dev/null || [ -d "$CLAUDE_DIR" ]; then
    mkdir -p "$CLAUDE_DIR"
    if [ -f "$CLAUDE_CONFIG" ]; then
        echo -e "${GREEN}✓ Claude Code MCP ya existe${NC}"
    else
        cat > "$CLAUDE_CONFIG" << EOF
{
  "mcpServers": {
    "chl-memory": {
      "command": "$NODE_BIN",
      "args": ["$PROJECT_DIR/src/mcp-server.js"],
      "env": {
        "CHL_PERSIST_PATH": "$PERSIST_PATH",
        "CHL_AUTO_REMEMBER": "smart"
      }
    }
  }
}
EOF
        echo -e "${GREEN}✓ Claude Code MCP configurado${NC}"
    fi
else
    echo -e "${YELLOW}○ Claude Code no detectado${NC}"
fi

# ─── Paso 6: Reglas de agente ─────────────────────────────

echo -e "${BOLD}[6/6] Instalando reglas auto-memory...${NC}"
bash "$PROJECT_DIR/scripts/setup-agents.sh" 2>&1 | grep -E "✓|○"

# ─── Hecho ─────────────────────────────────────────────────

echo ""
echo -e "${BOLD}═══════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  ✓ CHL instalado correctamente${NC}"
echo -e "${BOLD}═══════════════════════════════════════════${NC}"
echo ""
echo -e "  Memoria:   ${GREEN}$PERSIST_PATH${NC}"
echo -e "  Proyecto:  ${GREEN}$PROJECT_DIR${NC}"
echo ""
echo "  Para verificar, escribe en tu agente:"
echo "    chl_snapshot"
echo ""
echo "  Para ingerir un proyecto:"
echo "    chl_ingest_directory --dirPath /ruta/proyecto"
echo ""
