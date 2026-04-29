#!/usr/bin/env bash
# reflect-and-refine installer
#
# Usage:
#   ./install.sh               # install into auto-detected settings file
#   ./install.sh --settings=<path>   # explicit settings file
#   ./install.sh --register <skill> [<skill> ...]  # also register skills
#   ./install.sh --enable-codex-feature-flag       # also enable codex_hooks
#   ./install.sh --uninstall   # shortcut to uninstall.sh

set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SCRIPT="$SKILL_ROOT/hooks/stop-gate.py"
CONFIG_DIR="$HOME/.reflect-and-refine"
CONFIG_FILE="$CONFIG_DIR/config.json"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CODEX_CONFIG_FILE="$CODEX_HOME/config.toml"
CODEX_HOOKS_FILE="$CODEX_HOME/hooks.json"

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

ensure_symlink() {
  local target="$1"
  local source="$2"
  local label="$3"

  mkdir -p "$(dirname "$target")"
  if [ -L "$target" ]; then
    current="$(readlink "$target")"
    if [ "$current" != "$source" ]; then
      echo "warning: $target points to $current, replacing with $source" >&2
      rm "$target"
      ln -s "$source" "$target"
    fi
    return
  fi

  if [ -e "$target" ]; then
    echo "warning: $target exists and is not a symlink; leaving $label link unchanged" >&2
    return
  fi

  ln -s "$source" "$target"
  echo "skill linked ($label): $target -> $source"
}

has_codex_feature_flag() {
  [ -f "$CODEX_CONFIG_FILE" ] || return 1
  awk '
    /^\[features\][[:space:]]*$/ { in_features=1; next }
    /^\[/ { in_features=0 }
    in_features && /^[[:space:]]*codex_hooks[[:space:]]*=[[:space:]]*true([[:space:]]|$)/ { found=1 }
    END { exit found ? 0 : 1 }
  ' "$CODEX_CONFIG_FILE"
}

enable_codex_feature_flag() {
  local backup_file temp_file

  mkdir -p "$CODEX_HOME"
  backup_file="$CODEX_CONFIG_FILE.backup-$(date +%Y%m%d%H%M%S)"
  temp_file="$(mktemp)"

  if [ ! -f "$CODEX_CONFIG_FILE" ]; then
    cat > "$temp_file" <<'EOF'
[features]
codex_hooks = true
EOF
    mv "$temp_file" "$CODEX_CONFIG_FILE"
    echo "enabled codex_hooks in: $CODEX_CONFIG_FILE"
    return
  fi

  cp "$CODEX_CONFIG_FILE" "$backup_file"
  awk '
    BEGIN {
      saw_features = 0
      in_features = 0
      inserted = 0
    }
    /^\[features\][[:space:]]*$/ {
      saw_features = 1
      in_features = 1
      print
      next
    }
    /^\[/ {
      if (in_features && !inserted) {
        print "codex_hooks = true"
        inserted = 1
      }
      in_features = 0
      print
      next
    }
    {
      if (in_features && /^[[:space:]]*codex_hooks[[:space:]]*=/) {
        print "codex_hooks = true"
        inserted = 1
        next
      }
      print
    }
    END {
      if (!saw_features) {
        if (NR > 0) {
          print ""
        }
        print "[features]"
        print "codex_hooks = true"
      } else if (in_features && !inserted) {
        print "codex_hooks = true"
      }
    }
  ' "$CODEX_CONFIG_FILE" > "$temp_file"
  mv "$temp_file" "$CODEX_CONFIG_FILE"
  echo "enabled codex_hooks in: $CODEX_CONFIG_FILE (backup: $backup_file)"
}

# Parse args
SETTINGS_FILE=""
REGISTER_SKILLS=()
ENABLE_CODEX_FEATURE_FLAG="no"
while [ $# -gt 0 ]; do
  case "$1" in
    --settings=*) SETTINGS_FILE="${1#--settings=}"; shift ;;
    --settings) SETTINGS_FILE="$2"; shift 2 ;;
    --register) shift; while [ $# -gt 0 ] && [[ "$1" != --* ]]; do REGISTER_SKILLS+=("$1"); shift; done ;;
    --enable-codex-feature-flag) ENABLE_CODEX_FEATURE_FLAG="yes"; shift ;;
    --uninstall) exec bash "$SKILL_ROOT/uninstall.sh" "${@:2}" ;;
    -h|--help)
      cat <<EOF
reflect-and-refine installer

Usage:
  $0 [--settings=<path>] [--register <skill> ...] [--enable-codex-feature-flag] [--uninstall]

Defaults to auto-detecting ~/.claude/ft-settings.json or ~/.claude/settings.json.

Installation always registers 'rnr' (plus the legacy 'reflect-and-refine' alias). Additional skills registered
via --register or later via /rnr register will also open the gate when
invoked.

Claude Code hooks are installed into the detected settings JSON.
Codex hooks are installed into \$CODEX_HOME/hooks.json (default: ~/.codex/hooks.json).
Pass --enable-codex-feature-flag if you also want the installer to set
codex_hooks = true in \$CODEX_HOME/config.toml.
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

# Install skill links for both Claude Code and Codex.
ensure_symlink "$HOME/.claude/skills/reflect-and-refine" "$SKILL_ROOT" "claude-code"
ensure_symlink "$HOME/.claude/skills/rnr" "$SKILL_ROOT" "claude-code-alias"
ensure_symlink "$HOME/.codex/skills/reflect-and-refine" "$SKILL_ROOT" "codex-legacy"
ensure_symlink "$HOME/.codex/skills/rnr" "$SKILL_ROOT" "codex-legacy-alias"
ensure_symlink "$HOME/.agents/skills/reflect-and-refine" "$SKILL_ROOT" "codex-canonical"
ensure_symlink "$HOME/.agents/skills/rnr" "$SKILL_ROOT" "codex-canonical-alias"

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

# Install Codex Stop hook into $CODEX_HOME/hooks.json. This is inert until
# codex_hooks is enabled, which we only do when explicitly asked.
mkdir -p "$CODEX_HOME"
if [ ! -f "$CODEX_HOOKS_FILE" ]; then
  echo "{}" > "$CODEX_HOOKS_FILE"
fi
jq -e . "$CODEX_HOOKS_FILE" >/dev/null 2>&1 || die "Codex hooks file is not valid JSON: $CODEX_HOOKS_FILE"

CODEX_BACKUP="$CODEX_HOOKS_FILE.bak.$(date +%s).rar"
cp "$CODEX_HOOKS_FILE" "$CODEX_BACKUP"
echo "backup: $CODEX_BACKUP"

TMP_CODEX="$(mktemp)"
jq --arg cmd "$HOOK_CMD" '
  .hooks //= {} |
  .hooks.Stop //= [] |
  if any(.hooks.Stop[]?; any(.hooks[]?; .type == "command" and .command == $cmd)) then .
  else .hooks.Stop += [{
    "hooks": [{
      "type": "command",
      "command": $cmd,
      "timeout": 30
    }]
  }]
  end
' "$CODEX_HOOKS_FILE" > "$TMP_CODEX"

jq -e . "$TMP_CODEX" >/dev/null 2>&1 || { rm -f "$TMP_CODEX"; die "Codex hook merge produced invalid JSON. Backup at $CODEX_BACKUP"; }
mv "$TMP_CODEX" "$CODEX_HOOKS_FILE"
echo "Codex hook installed in: $CODEX_HOOKS_FILE"

if [ "$ENABLE_CODEX_FEATURE_FLAG" = "yes" ]; then
  enable_codex_feature_flag
elif has_codex_feature_flag; then
  echo "codex_hooks already enabled in: $CODEX_CONFIG_FILE"
else
  echo "note: Codex hook is installed but codex_hooks is not enabled in: $CODEX_CONFIG_FILE"
  echo "      enable it later with: ./install.sh --enable-codex-feature-flag"
fi

# Config file + prompts scaffolding
mkdir -p "$CONFIG_DIR" "$CONFIG_DIR/prompts/overrides" "$CONFIG_DIR/prompts/scenarios" "$CONFIG_DIR/prompts/intents" "$CONFIG_DIR/sessions"
if [ ! -f "$CONFIG_FILE" ]; then
  cat > "$CONFIG_FILE" <<'JSON'
{
  "registered_skills": ["rnr", "reflect-and-refine"],
  "max_blocks_per_turn": 3,
  "suppress_output": true,
  "reviewer": {
    "trigger_mode": "intent_sensitive",
    "trigger_mode_by_scenario": {
      "coding": "intent_sensitive",
      "testing": "intent_sensitive",
      "debugging": "intent_sensitive",
      "general": "intent_sensitive"
    },
    "skill_scenario_map": {},
    "per_skill": {}
  }
}
JSON
fi

# Seed user-level default prompt (fallback when no scenario is mapped).
USER_DEFAULT="$CONFIG_DIR/prompts/default.md"
if [ ! -f "$USER_DEFAULT" ]; then
  cp "$SKILL_ROOT/prompts/reviewer-template.md" "$USER_DEFAULT"
  echo "seeded user-level default prompt: $USER_DEFAULT"
fi

# Scenarios directory starts empty on the user side; the hook falls through
# to the bundled scenarios shipped with the skill. Users who want to edit
# a scenario run `/rnr customize scenario <name>` which
# copies the bundled file into $CONFIG_DIR/prompts/scenarios/ for editing.

# Register additional skills if requested. When registering a known
# series skill (better-code / better-test / better-work), also seed a
# sensible skill_scenario_map entry unless one already exists.
if [ ${#REGISTER_SKILLS[@]} -gt 0 ]; then
  TMP_CFG="$(mktemp)"
  jq --argjson skills "$(printf '%s\n' "${REGISTER_SKILLS[@]}" | jq -R . | jq -s .)" '
    .registered_skills = ((.registered_skills // []) + $skills | unique) |
    .reviewer = (.reviewer // {}) |
    .reviewer.skill_scenario_map = (.reviewer.skill_scenario_map // {}) |
    # Seed known-skill → scenario defaults WITHOUT overwriting user choices
    (.reviewer.skill_scenario_map["better-code"] //= "coding") |
    (.reviewer.skill_scenario_map["better-test"] //= "testing") |
    (.reviewer.skill_scenario_map["better-work"] //= "general")
  ' "$CONFIG_FILE" > "$TMP_CFG"
  jq -e . "$TMP_CFG" >/dev/null 2>&1 || { rm -f "$TMP_CFG"; die "config merge failed"; }
  mv "$TMP_CFG" "$CONFIG_FILE"
  echo "registered: ${REGISTER_SKILLS[*]}"
  echo "seeded skill_scenario_map defaults (better-code→coding, better-test→testing, better-work→general) where not already set"
fi

echo
echo "registered skills:"
jq '.registered_skills' "$CONFIG_FILE"
echo
echo "IMPORTANT: restart Claude Code (/exit, then claude) and restart Codex after first install so both platforms pick up the skill."
