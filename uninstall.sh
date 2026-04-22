#!/usr/bin/env bash
# reflect-and-refine uninstaller

set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SCRIPT="$SKILL_ROOT/hooks/stop-gate.py"
CONFIG_DIR="$HOME/.reflect-and-refine"

die() { echo "error: $*" >&2; exit 1; }

detect_settings() {
  if [ -f "$HOME/.claude/ft-settings.json" ]; then
    echo "$HOME/.claude/ft-settings.json"
  elif [ -f "$HOME/.claude/settings.json" ]; then
    echo "$HOME/.claude/settings.json"
  else
    echo ""
  fi
}

SETTINGS_FILE="${1:-$(detect_settings)}"
PURGE_CONFIG="no"
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE_CONFIG="yes" ;;
    --settings=*) SETTINGS_FILE="${arg#--settings=}" ;;
  esac
done

command -v jq >/dev/null 2>&1 || die "jq is required."

if [ -n "$SETTINGS_FILE" ] && [ -f "$SETTINGS_FILE" ]; then
  BACKUP="$SETTINGS_FILE.bak.$(date +%s).rar-uninstall"
  cp "$SETTINGS_FILE" "$BACKUP"
  echo "backup: $BACKUP"

  HOOK_CMD="python3 $HOOK_SCRIPT"
  TMP_FILE="$(mktemp)"
  jq --arg cmd "$HOOK_CMD" '
    if .hooks.Stop then
      .hooks.Stop = [
        .hooks.Stop[] |
        .hooks = [.hooks[] | select(.command != $cmd)] |
        select(.hooks | length > 0)
      ] |
      if (.hooks.Stop | length) == 0 then del(.hooks.Stop) else . end
    else . end |
    if (.hooks | length) == 0 then del(.hooks) else . end
  ' "$SETTINGS_FILE" > "$TMP_FILE"

  jq -e . "$TMP_FILE" >/dev/null 2>&1 || { rm -f "$TMP_FILE"; die "merge produced invalid JSON. Backup at $BACKUP"; }
  mv "$TMP_FILE" "$SETTINGS_FILE"
  echo "hook removed from: $SETTINGS_FILE"
else
  echo "no settings file found or specified; skipping hook removal."
fi

if [ "$PURGE_CONFIG" = "yes" ]; then
  rm -rf "$CONFIG_DIR"
  echo "purged: $CONFIG_DIR"
else
  echo "config preserved at: $CONFIG_DIR (use --purge to delete)"
fi

echo
echo "IMPORTANT: restart Claude Code (/exit, then claude) for the removal to take effect."
