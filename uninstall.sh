#!/usr/bin/env bash
# reflect-and-refine uninstaller

set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SCRIPT="$SKILL_ROOT/hooks/stop-gate.py"
CONFIG_DIR="$HOME/.reflect-and-refine"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CODEX_HOOKS_FILE="$CODEX_HOME/hooks.json"

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

remove_skill_link() {
  local target="$1"
  local label="$2"
  if [ -L "$target" ]; then
    local link_target
    link_target="$(readlink "$target")"
    if [ "$link_target" = "$SKILL_ROOT" ]; then
      rm "$target"
      echo "skill symlink removed ($label): $target"
    else
      echo "note: $target points to $link_target (not our dir); leaving alone"
    fi
  elif [ -e "$target" ]; then
    echo "warning: $target exists but is not a symlink; leaving alone (remove manually if needed)"
  fi
}

SETTINGS_FILE=""
PURGE_CONFIG="no"
while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE_CONFIG="yes"; shift ;;
    --settings=*) SETTINGS_FILE="${1#--settings=}"; shift ;;
    --settings) SETTINGS_FILE="$2"; shift 2 ;;
    -h|--help)
      cat <<EOF
Usage:
  $0 [--settings=<path>] [--purge]
EOF
      exit 0
      ;;
    *) shift ;;
  esac
done
if [ -z "$SETTINGS_FILE" ]; then
  SETTINGS_FILE="$(detect_settings)"
fi

command -v jq >/dev/null 2>&1 || die "jq is required."

# Remove skill symlinks if they point to our dir
remove_skill_link "$HOME/.claude/skills/reflect-and-refine" "claude-code"
remove_skill_link "$HOME/.claude/skills/rnr" "claude-code-alias"
remove_skill_link "$HOME/.codex/skills/reflect-and-refine" "codex-legacy"
remove_skill_link "$HOME/.codex/skills/rnr" "codex-legacy-alias"
remove_skill_link "$HOME/.agents/skills/reflect-and-refine" "codex-canonical"
remove_skill_link "$HOME/.agents/skills/rnr" "codex-canonical-alias"

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

if [ -f "$CODEX_HOOKS_FILE" ]; then
  CODEX_BACKUP="$CODEX_HOOKS_FILE.bak.$(date +%s).rar-uninstall"
  cp "$CODEX_HOOKS_FILE" "$CODEX_BACKUP"
  echo "backup: $CODEX_BACKUP"

  HOOK_CMD="python3 $HOOK_SCRIPT"
  TMP_CODEX="$(mktemp)"
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
  ' "$CODEX_HOOKS_FILE" > "$TMP_CODEX"

  jq -e . "$TMP_CODEX" >/dev/null 2>&1 || { rm -f "$TMP_CODEX"; die "Codex hook merge produced invalid JSON. Backup at $CODEX_BACKUP"; }
  mv "$TMP_CODEX" "$CODEX_HOOKS_FILE"
  echo "Codex hook removed from: $CODEX_HOOKS_FILE"
else
  echo "no Codex hooks file found; skipping Codex hook removal."
fi

if [ "$PURGE_CONFIG" = "yes" ]; then
  rm -rf "$CONFIG_DIR"
  echo "purged: $CONFIG_DIR"
else
  echo "config preserved at: $CONFIG_DIR (use --purge to delete)"
fi

echo
echo "IMPORTANT: restart Claude Code and Codex for the removal to take effect."
