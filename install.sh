#!/usr/bin/env bash
# reflect-and-refine installer
#
# Usage:
#   ./install.sh               # install into auto-detected settings file
#   ./install.sh --settings=<path>   # explicit settings file
#   ./install.sh --register <skill> [<skill> ...]  # also register skills
#   ./install.sh --uninstall   # shortcut to uninstall.sh

set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SCRIPT="$SKILL_ROOT/hooks/stop-gate.py"
CONFIG_DIR="$HOME/.reflect-and-refine"
CONFIG_FILE="$CONFIG_DIR/config.json"

die() { echo "error: $*" >&2; exit 1; }

detect_settings() {
  if [ -f "$HOME/.claude/ft-settings.json" ]; then
    echo "$HOME/.claude/ft-settings.json"
  elif [ -f "$HOME/.claude/settings.json" ]; then
    echo "$HOME/.claude/settings.json"
  else
    echo "$HOME/.claude/settings.json"  # will be created
  fi
}

# Parse args
SETTINGS_FILE=""
REGISTER_SKILLS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --settings=*) SETTINGS_FILE="${1#--settings=}"; shift ;;
    --settings) SETTINGS_FILE="$2"; shift 2 ;;
    --register) shift; while [ $# -gt 0 ] && [[ "$1" != --* ]]; do REGISTER_SKILLS+=("$1"); shift; done ;;
    --uninstall) exec bash "$SKILL_ROOT/uninstall.sh" "${@:2}" ;;
    -h|--help)
      cat <<EOF
reflect-and-refine installer

Usage:
  $0 [--settings=<path>] [--register <skill> ...] [--uninstall]

Defaults to auto-detecting ~/.claude/ft-settings.json or ~/.claude/settings.json.

Installation always registers 'reflect-and-refine' itself. Additional skills registered
via --register or later via /reflect-and-refine register will also open the gate when
invoked.

After install, restart Claude Code for the hook to take effect.
EOF
      exit 0
      ;;
    *) die "unknown arg: $1" ;;
  esac
done

command -v jq >/dev/null 2>&1 || die "jq is required. Install with: brew install jq"
command -v python3 >/dev/null 2>&1 || die "python3 is required."
[ -f "$HOOK_SCRIPT" ] || die "hook script missing: $HOOK_SCRIPT"
chmod +x "$HOOK_SCRIPT"

SETTINGS_FILE="${SETTINGS_FILE:-$(detect_settings)}"
SETTINGS_DIR="$(dirname "$SETTINGS_FILE")"
mkdir -p "$SETTINGS_DIR"

# Ensure settings file exists and is valid JSON
if [ ! -f "$SETTINGS_FILE" ]; then
  echo "{}" > "$SETTINGS_FILE"
fi
jq -e . "$SETTINGS_FILE" >/dev/null 2>&1 || die "settings file is not valid JSON: $SETTINGS_FILE"

# Backup
BACKUP="$SETTINGS_FILE.bak.$(date +%s).rar"
cp "$SETTINGS_FILE" "$BACKUP"
echo "backup: $BACKUP"

# Merge Stop hook entry (idempotent — if a matching entry exists, don't duplicate)
HOOK_CMD="python3 $HOOK_SCRIPT"
TMP_FILE="$(mktemp)"
jq --arg cmd "$HOOK_CMD" '
  .hooks //= {} |
  .hooks.Stop //= [] |
  if any(.hooks.Stop[]?; .matcher == "*" and any(.hooks[]?; .type == "command" and .command == $cmd)) then .
  else .hooks.Stop += [{
    "matcher": "*",
    "hooks": [{
      "type": "command",
      "command": $cmd,
      "timeout": 30
    }]
  }]
  end
' "$SETTINGS_FILE" > "$TMP_FILE"

jq -e . "$TMP_FILE" >/dev/null 2>&1 || { rm -f "$TMP_FILE"; die "merge produced invalid JSON. Backup at $BACKUP"; }
mv "$TMP_FILE" "$SETTINGS_FILE"
echo "hook installed in: $SETTINGS_FILE"

# Config file
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_FILE" ]; then
  echo '{"registered_skills":["reflect-and-refine"],"max_blocks_per_turn":3}' > "$CONFIG_FILE"
fi

# Register additional skills if requested
if [ ${#REGISTER_SKILLS[@]} -gt 0 ]; then
  TMP_CFG="$(mktemp)"
  jq --argjson skills "$(printf '%s\n' "${REGISTER_SKILLS[@]}" | jq -R . | jq -s .)" '
    .registered_skills = ((.registered_skills // []) + $skills | unique)
  ' "$CONFIG_FILE" > "$TMP_CFG"
  jq -e . "$TMP_CFG" >/dev/null 2>&1 || { rm -f "$TMP_CFG"; die "config merge failed"; }
  mv "$TMP_CFG" "$CONFIG_FILE"
  echo "registered: ${REGISTER_SKILLS[*]}"
fi

echo
echo "registered skills:"
jq '.registered_skills' "$CONFIG_FILE"
echo
echo "IMPORTANT: restart Claude Code (/exit, then claude) for the Stop hook to take effect."
