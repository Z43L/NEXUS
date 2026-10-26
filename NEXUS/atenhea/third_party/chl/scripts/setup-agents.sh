#!/usr/bin/env bash
# CHL Universal Agent Setup
# Configura CHL para todos los agentes instalados en el sistema.
# Ejecutar: bash scripts/setup-agents.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CHL_AGENT_RULE="$PROJECT_DIR/CHL_AGENT_RULE.md"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "═══════════════════════════════════════════"
echo "  CHL Universal Agent Setup"
echo "═══════════════════════════════════════════"
echo ""

# ─── Codex ────────────────────────────────────────────────

setup_codex() {
    local SKILL_DIR="$HOME/.codex/skills/chl-auto"
    local SKILL_FILE="$SKILL_DIR/SKILL.md"
    local SOURCE="$PROJECT_DIR/agents/codex/SKILL.md"

    if [ -d "$HOME/.codex" ]; then
        mkdir -p "$SKILL_DIR"
        cp "$SOURCE" "$SKILL_FILE"
        echo -e "${GREEN}✓ Codex${NC} — skill instalada en ~/.codex/skills/chl-auto/"
    else
        echo -e "${YELLOW}○ Codex${NC} — no detectado (~/.codex no existe)"
    fi
}

# ─── Claude Code ──────────────────────────────────────────

setup_claude_code() {
    local CLAUDE_DIR="$HOME/.claude"
    local CLAUDE_FILE="$CLAUDE_DIR/CLAUDE.md"
    local SOURCE="$PROJECT_DIR/agents/claude-code/CLAUDE.md"

    if command -v claude &>/dev/null || [ -d "$CLAUDE_DIR" ]; then
        mkdir -p "$CLAUDE_DIR"
        cp "$SOURCE" "$CLAUDE_FILE"
        echo -e "${GREEN}✓ Claude Code${NC} — reglas en ~/.claude/CLAUDE.md"
    else
        echo -e "${YELLOW}○ Claude Code${NC} — no detectado"
    fi
}

# ─── OpenCode ─────────────────────────────────────────────

setup_opencode() {
    local OPENCODE_DIR="$HOME/.opencode"
    local RULES_FILE="$OPENCODE_DIR/rules.md"
    local SOURCE="$PROJECT_DIR/agents/opencode/RULES.md"

    if [ -d "$OPENCODE_DIR" ]; then
        mkdir -p "$OPENCODE_DIR"
        cp "$SOURCE" "$RULES_FILE"
        echo -e "${GREEN}✓ OpenCode${NC} — reglas en ~/.opencode/rules.md"
    else
        echo -e "${YELLOW}○ OpenCode${NC} — no detectado"
    fi
}

# ─── OpenClaw ─────────────────────────────────────────────

setup_openclaw() {
    local OPENCLAW_DIR="$HOME/.openclaw"
    local RULES_FILE="$OPENCLAW_DIR/rules.md"
    local SOURCE="$PROJECT_DIR/agents/openclaw/RULES.md"

    if [ -d "$OPENCLAW_DIR" ]; then
        mkdir -p "$OPENCLAW_DIR"
        cp "$SOURCE" "$RULES_FILE"
        echo -e "${GREEN}✓ OpenClaw${NC} — reglas en ~/.openclaw/rules.md"
    else
        echo -e "${YELLOW}○ OpenClaw${NC} — no detectado"
    fi
}

# ─── Hermes Agent ─────────────────────────────────────────

setup_hermes() {
    local HERMES_DIR="$HOME/.hermes"
    local RULES_FILE="$HERMES_DIR/instructions.md"
    local SOURCE="$PROJECT_DIR/agents/openclaw/RULES.md"  # mismo formato simple

    if [ -d "$HERMES_DIR" ]; then
        mkdir -p "$HERMES_DIR"
        cp "$SOURCE" "$RULES_FILE"
        echo -e "${GREEN}✓ Hermes Agent${NC} — instrucciones en ~/.hermes/instructions.md"
    else
        echo -e "${YELLOW}○ Hermes Agent${NC} — no detectado"
    fi
}

# ─── Ejecutar ─────────────────────────────────────────────

setup_codex
setup_claude_code
setup_opencode
setup_openclaw
setup_hermes

echo ""
echo "═══════════════════════════════════════════"
echo "  Regla universal:"
echo "  $CHL_AGENT_RULE"
echo ""
echo "  Cópiala manualmente en cualquier otro"
echo "  agente como system prompt o rules file."
echo "═══════════════════════════════════════════"
