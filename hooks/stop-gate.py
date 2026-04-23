#!/usr/bin/env python3
"""
reflect-and-refine Stop hook gate.

Reads Claude Code Stop hook JSON from stdin. Decides whether to:
- exit 0 silently (gate closed or rate-limited), OR
- emit a block JSON that instructs the main agent to run a reviewer sub-agent.

Fail-open: any uncaught exception results in exit 0 (we never block the user's
stop due to our own bug). Errors are logged to ~/.reflect-and-refine/logs/.
"""

import json
import os
import re
import sys
import traceback
from pathlib import Path
from datetime import datetime, timezone

HOME = Path(os.path.expanduser("~"))
CONFIG_DIR = HOME / ".reflect-and-refine"
CONFIG_FILE = CONFIG_DIR / "config.json"
PAUSE_FLAG = CONFIG_DIR / ".paused"
LOG_DIR = CONFIG_DIR / "logs"
AUDIT_LOG = CONFIG_DIR / "audit.md"
USER_PROMPTS_DIR = CONFIG_DIR / "prompts"
USER_OVERRIDES_DIR = USER_PROMPTS_DIR / "overrides"
USER_DEFAULT_PROMPT = USER_PROMPTS_DIR / "default.md"
SKILL_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_PROMPT = SKILL_ROOT / "prompts" / "reviewer-template.md"

SHUTDOWN_MARKER_ARGS = "shutdown"
DEFAULT_MAX_BLOCKS_PER_TURN = 3
AUDIT_HEAD_MAX = 150  # chars to show in audit excerpts

# Dimension snippets: {dimension_name: {strictness: text}}. Rendered into the
# {DIMENSIONS_BLOCK} slot based on frontmatter config. Keep each snippet to
# one numbered line so the assembled block reads as an ordered list.
DIMENSION_SNIPPETS = {
    "requirement_split": {
        "lenient": "Is every major requirement in the user's request identified?",
        "default": "Is every distinct requirement in the user's request enumerated?",
        "strict":  "Enumerate every distinct requirement in the user's request, splitting multi-part asks into discrete items. Missing one = fail.",
    },
    "evidence": {
        "lenient": "Does each requirement have some supporting evidence (even if partial)?",
        "default": "Does each requirement have concrete evidence of completion — file:line, command output, test result, or observable state change? \"I did X\" without artifact is NOT evidence.",
        "strict":  "Every requirement MUST cite one of: file:line reference, verbatim command output, actual test pass line, or directly observable state change. Narrative claims without artifact are failures.",
    },
    "hedging": {
        "lenient": "Flag outright uncertain language (\"unsure\", \"might not work\").",
        "default": "Any hedging (\"should work\", \"probably\", \"likely\", \"I believe\")? Flag as insufficient.",
        "strict":  "Any hedging at all (\"should\", \"probably\", \"likely\", \"I believe\", \"pretty sure\", \"I think\")? Automatic insufficient-evidence flag.",
    },
    "silent_drops": {
        "lenient": "Any obviously ignored requirement?",
        "default": "Any requirement silently dropped, deferred, or glossed over?",
        "strict":  "Any requirement the agent did not explicitly address — even a trivial \"skipped because X\" disclosure? Silence is a failure.",
    },
    "fake_evidence": {
        "lenient": "Any clearly fabricated claim (e.g., file path that obviously doesn't exist)?",
        "default": "Any evidence that looks fabricated — references to nonexistent files, test results without the command that produced them, internal contradictions?",
        "strict":  "Verify that every cited file path, command output, and test result is internally consistent with the response. Any unverified reference is potentially fabricated.",
    },
    "consistency": {
        "lenient": "Are the claims internally consistent?",
        "default": "Is the response internally consistent — no claims that contradict each other?",
        "strict":  "Cross-check every factual claim against every other claim. Flag any tension, even minor.",
    },
    "completeness": {
        "lenient": "Are the explicit user questions answered?",
        "default": "Are all explicit AND implicit sub-questions answered?",
        "strict":  "Answer ALL explicit questions, ALL implicit sub-questions, AND note any latent questions the user didn't think to ask but should care about.",
    },
}

STRICTNESS_DIRECTIVES = {
    "lenient": "You are a completion reviewer. Flag only serious gaps. Minor omissions may be acceptable.",
    "default": "You are an adversarial completion reviewer. Your job is to find gaps in the main agent's work. Do not confirm completion unless you cannot find a single gap worth flagging.",
    "strict":  "You are a strict adversarial completion reviewer. Assume the main agent is cutting corners; your job is to prove it. Do not confirm completion unless every dimension passes unambiguously.",
}

# Valid enum values for the `model` frontmatter field. `default` / empty /
# anything else we don't recognize causes the hook to omit the model param
# so the main agent's Task tool picks the inherited model.
VALID_REVIEWER_MODELS = {"haiku", "sonnet", "opus"}

# Subcommands of /reflect-and-refine that are query/config — they MUST NOT
# be treated as activation markers. Only `shutdown` closes the gate;
# `activate` (or empty args) opens it; anything else listed here is
# transparent to gate state.
IDEMPOTENT_RAR_SUBCOMMANDS = {
    "status", "audit", "rate-limit", "register", "unregister", "customize",
}


def log_error(msg: str) -> None:
    """
    Write to ~/.reflect-and-refine/logs/errors-YYYYMMDD.log AND emit a
    one-line stderr hint so the user has a visible signal something went
    wrong. stderr from a Claude Code Stop hook is shown in the terminal
    (exit code 2 would block, we use 0 here so it's non-blocking).
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logfile = LOG_DIR / f"errors-{datetime.now():%Y%m%d}.log"
        with logfile.open("a") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass  # last-resort: don't let logging itself break us
    try:
        # Single concise line to stderr; truncate long messages so we never
        # spam the terminal. Don't include full traceback here — it's in the
        # log file.
        head = msg.splitlines()[0][:120] if msg else "unknown"
        sys.stderr.write(f"[reflect-and-refine] hook error: {head} (see ~/.reflect-and-refine/logs/)\n")
    except Exception:
        pass


def _head(s: str, n: int = AUDIT_HEAD_MAX) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def audit_log(event: str, session_id: str, details: dict) -> None:
    """
    Append a markdown audit entry. Never raises — logging must not break the hook.
    One entry = one heading + a bullet list. Append-only, newest-at-bottom.
    """
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not AUDIT_LOG.exists() or AUDIT_LOG.stat().st_size == 0:
            AUDIT_LOG.write_text(
                "# reflect-and-refine audit log\n\n"
                "Every hook fire that took action (BLOCKED or RATE-LIMITED) is "
                "recorded here for human review. Append-only; prune manually if needed.\n\n"
            )
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        short_sess = (session_id or "unknown")[:8]
        lines = [
            "---",
            f"## {now} · session={short_sess} · event={event}",
        ]
        for k, v in details.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")  # trailing blank
        with AUDIT_LOG.open("a") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        log_error(f"audit_log failed: {e}")


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open() as f:
        return json.load(f)


def read_transcript(path: Path) -> list[dict]:
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def is_real_user_record(rec: dict) -> bool:
    """
    A 'real' user message is one typed/pasted by the human user, NOT:
    - hook injections (isMeta: true)
    - tool results (toolUseResult present)
    - sidechain / meta records
    """
    if rec.get("type") != "user":
        return False
    if rec.get("isMeta") is True:
        return False
    if rec.get("toolUseResult") is not None:
        return False
    content = rec.get("message", {}).get("content", "")
    if not isinstance(content, str):
        # tool results often have list content; real user messages are strings
        return False
    return True


def gate_state(records: list[dict], registered_skills: set[str]) -> tuple[str, str]:
    """
    Scan real user records from newest to oldest. Return (state, triggered_skill).
    - state: 'OPEN' or 'CLOSED'
    - triggered_skill: the skill name that caused the OPEN state, or "" if CLOSED.
      Used downstream for per-skill prompt routing.

    Rules (last matching real-user command wins; query subcommands are transparent):
    - /reflect-and-refine shutdown              -> CLOSED
    - /reflect-and-refine activate | (no args)  -> OPEN, triggered_skill="reflect-and-refine"
    - /reflect-and-refine <idempotent-query>    -> skip (doesn't change state)
    - /<any-other-registered-skill>             -> OPEN, triggered_skill=<skill>
    - no markers found                          -> CLOSED
    """
    name_pat = re.compile(r"<command-name>/([\w-]+)</command-name>")
    args_pat = re.compile(r"<command-args>([^<]*)</command-args>", re.DOTALL)
    for rec in reversed(records):
        if not is_real_user_record(rec):
            continue
        content = rec["message"]["content"]
        m = name_pat.search(content)
        if not m:
            continue
        skill = m.group(1)
        args_match = args_pat.search(content)
        args = args_match.group(1).strip() if args_match else ""

        if skill == "reflect-and-refine":
            first_arg = args.split()[0] if args else ""
            if first_arg == SHUTDOWN_MARKER_ARGS:
                return "CLOSED", ""
            if first_arg == "" or first_arg == "activate":
                return "OPEN", "reflect-and-refine"
            if first_arg in IDEMPOTENT_RAR_SUBCOMMANDS:
                continue  # query/config — transparent to gate state
            # Unknown subcommand (typo, new command we don't recognize): be
            # transparent rather than fail-safe-activate.
            continue

        if skill in registered_skills:
            return "OPEN", skill
    return "CLOSED", ""


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    Minimal YAML frontmatter parser (stdlib-only). Supports:
    - scalar fields: key: value
    - list fields:   key: \n  - item1 \n  - item2
    - list of dicts: key: \n  - name: foo \n    description: bar
    - comments: lines starting with #
    - empty lists: key: []
    Does NOT support nested maps, multi-line strings, flow-style syntax.

    Returns (config_dict, body_text). If no frontmatter, config_dict is {}.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    fm_lines: list[str] = []
    body_start = len(lines)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body_start = i + 1
            break
        fm_lines.append(lines[i])

    config: dict = {}
    current_key: str | None = None
    current_list: list | None = None
    current_dict: dict | None = None

    for raw in fm_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # List item
        if stripped.startswith("- "):
            item_text = stripped[2:].strip()
            if current_list is None:
                continue  # malformed, skip
            # List of dicts: "- key: value"
            if ":" in item_text and not item_text.startswith('"'):
                k, _, v = item_text.partition(":")
                current_dict = {k.strip(): v.strip().strip('"').strip("'")}
                current_list.append(current_dict)
            else:
                current_list.append(item_text.strip('"').strip("'"))
                current_dict = None
            continue

        # Continuation of a dict list item: "  key: value" (indented)
        if raw.startswith("    ") and current_dict is not None and ":" in raw:
            k, _, v = raw.strip().partition(":")
            current_dict[k.strip()] = v.strip().strip('"').strip("'")
            continue

        # New top-level key
        if ":" in raw and not raw.startswith((" ", "\t")):
            k, _, v = raw.partition(":")
            k = k.strip()
            v = v.strip()
            if v == "" or v == "|":
                # Following lines will be a list (or indented scalar — not supported)
                current_key = k
                current_list = []
                config[k] = current_list
                current_dict = None
            elif v == "[]":
                config[k] = []
                current_key = k
                current_list = None
                current_dict = None
            else:
                config[k] = v.strip('"').strip("'")
                current_key = k
                current_list = None
                current_dict = None

    body = "\n".join(lines[body_start:])
    return config, body


def assemble_dimensions_block(dimension_names: list[str], strictness: str) -> str:
    """Render selected dimension snippets as a numbered list."""
    if not dimension_names:
        return "(no dimensions configured)"
    out = []
    for i, name in enumerate(dimension_names, 1):
        snippets = DIMENSION_SNIPPETS.get(name)
        if snippets is None:
            out.append(f"{i}. ({name} — unknown dimension; hook did not render)")
            continue
        text = snippets.get(strictness) or snippets.get("default") or ""
        out.append(f"{i}. {text}")
    return "\n".join(out)


def assemble_custom_checks_block(custom_checks: list) -> str:
    if not custom_checks:
        return ""
    lines = ["Project-specific checks:"]
    for check in custom_checks:
        if isinstance(check, dict):
            name = check.get("name", "unnamed")
            desc = check.get("description", "")
            lines.append(f"- **{name}**: {desc}")
        elif isinstance(check, str):
            lines.append(f"- {check}")
    return "\n".join(lines)


def resolve_prompt_path(triggered_skill: str, config: dict) -> Path:
    """
    Three-layer fallback (highest precedence first):
      1. Explicit per-skill path in config.reviewer.per_skill.<skill>
      2. ~/.reflect-and-refine/prompts/overrides/<triggered_skill>.md
      3. ~/.reflect-and-refine/prompts/default.md (user-writable)
      4. <bundled>/prompts/reviewer-template.md (ships with skill)
    """
    reviewer_cfg = config.get("reviewer", {}) if isinstance(config.get("reviewer"), dict) else {}
    per_skill = reviewer_cfg.get("per_skill", {}) if isinstance(reviewer_cfg.get("per_skill"), dict) else {}

    # Layer 1: explicit config mapping
    mapped = per_skill.get(triggered_skill) if triggered_skill else None
    if mapped:
        mapped_path = Path(os.path.expanduser(str(mapped)))
        if not mapped_path.is_absolute():
            mapped_path = CONFIG_DIR / mapped_path
        if mapped_path.exists():
            return mapped_path

    # Layer 2: overrides directory, by skill name
    if triggered_skill:
        override = USER_OVERRIDES_DIR / f"{triggered_skill}.md"
        if override.exists():
            return override

    # Layer 3: user-level default
    if USER_DEFAULT_PROMPT.exists():
        return USER_DEFAULT_PROMPT

    # Layer 4: bundled (always exists in a valid install)
    return BUNDLED_PROMPT


def last_user_timestamp(records: list[dict]) -> str:
    for rec in reversed(records):
        if is_real_user_record(rec):
            return rec.get("timestamp", "")
    return ""


def last_user_command_parts(records: list[dict]) -> tuple[str, str]:
    """
    Return (request_text, agent_response_text).

    request_text: the most recent REAL user message (hook injections and tool
    results skipped). If slash-command, render as "/skill args"; else plain text.

    agent_response_text: concatenation of ALL assistant text blocks that appear
    AFTER the most recent real user message. This captures the full response
    across tool-call boundaries, not just the last text block.
    """
    name_pat = re.compile(r"<command-name>/([\w-]+)</command-name>")
    args_pat = re.compile(r"<command-args>([^<]*)</command-args>", re.DOTALL)

    # Find index of last real user record
    last_user_idx = -1
    for i in range(len(records) - 1, -1, -1):
        if is_real_user_record(records[i]):
            last_user_idx = i
            break

    if last_user_idx == -1:
        return "", ""

    user_rec = records[last_user_idx]
    content = user_rec["message"]["content"]
    name_match = name_pat.search(content)
    args_match = args_pat.search(content)
    if name_match and args_match:
        request_text = f"/{name_match.group(1)} {args_match.group(1).strip()}"
    elif name_match:
        request_text = f"/{name_match.group(1)}"
    else:
        cleaned = re.sub(r"<system-reminder>.*?</system-reminder>", "", content, flags=re.DOTALL).strip()
        request_text = cleaned[:4000]

    agent_text_blocks: list[str] = []
    for rec in records[last_user_idx + 1 :]:
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = (block.get("text") or "").strip()
                    if t:
                        agent_text_blocks.append(t)
        elif isinstance(content, str):
            s = content.strip()
            if s:
                agent_text_blocks.append(s)

    agent_text = "\n\n".join(agent_text_blocks)[:8000]
    return request_text, agent_text


def increment_counter(session_id: str, last_user_ts: str, max_blocks: int) -> bool:
    """
    Per-turn counter. Returns True if we should block, False if rate-limited.
    State format: "<last_user_ts> <count>\n" in /tmp/rar-<session>.state
    """
    state_file = Path(f"/tmp/rar-{session_id}.state")
    saved_ts, saved_count = "", 0
    if state_file.exists():
        try:
            parts = state_file.read_text().strip().split(maxsplit=1)
            if len(parts) == 2:
                saved_ts, saved_count = parts[0], int(parts[1])
        except Exception:
            saved_ts, saved_count = "", 0

    if last_user_ts != saved_ts:
        # New user turn -> reset
        count = 0
    else:
        count = saved_count

    if count >= max_blocks:
        return False

    try:
        state_file.write_text(f"{last_user_ts} {count + 1}\n")
    except Exception as e:
        log_error(f"failed to write state {state_file}: {e}")

    return True


def build_block_reason(request_text: str, agent_text: str, prompt_path: Path) -> str:
    """
    Read the prompt file at prompt_path, parse its YAML frontmatter for
    reviewer config (language, strictness, dimensions, custom_checks), and
    substitute all placeholders in the body:
        {USER_REQUEST}, {AGENT_RESPONSE},
        {LANGUAGE}, {STRICTNESS_DIRECTIVE},
        {DIMENSIONS_BLOCK}, {CUSTOM_CHECKS_BLOCK}

    Templates without frontmatter (legacy or user-edited without YAML) still
    work — sane defaults fill in for missing fields.
    """
    full = prompt_path.read_text()
    fm, body = parse_frontmatter(full)

    language = fm.get("language", "en") or "en"
    strictness = fm.get("strictness", "default") or "default"
    if strictness not in STRICTNESS_DIRECTIVES:
        strictness = "default"

    model_raw = (fm.get("model") or fm.get("model_preference") or "").strip().lower()
    if model_raw in VALID_REVIEWER_MODELS:
        model_preference_param = f"- `model`: `{model_raw}`\n"
    else:
        model_preference_param = ""  # "default" / "" / unknown → inherit

    dimensions = fm.get("dimensions", [])
    if not isinstance(dimensions, list):
        dimensions = []
    # Default dimensions when none specified
    if not dimensions:
        dimensions = ["requirement_split", "evidence", "hedging", "silent_drops", "fake_evidence"]

    custom_checks = fm.get("custom_checks", [])
    if not isinstance(custom_checks, list):
        custom_checks = []

    strictness_directive = STRICTNESS_DIRECTIVES.get(strictness, STRICTNESS_DIRECTIVES["default"])
    dimensions_block = assemble_dimensions_block(dimensions, strictness)
    custom_checks_block = assemble_custom_checks_block(custom_checks)

    return (
        body
        .replace("{USER_REQUEST}", request_text or "(transcript did not yield a clear user request — review based on the full transcript)")
        .replace("{AGENT_RESPONSE}", agent_text or "(no prior assistant text extracted)")
        .replace("{LANGUAGE}", language)
        .replace("{STRICTNESS_DIRECTIVE}", strictness_directive)
        .replace("{MODEL_PREFERENCE_PARAM}", model_preference_param)
        .replace("{DIMENSIONS_BLOCK}", dimensions_block)
        .replace("{CUSTOM_CHECKS_BLOCK}", custom_checks_block)
    )


def main() -> None:
    # Emergency shutdown (checked BEFORE reading stdin so it's as cheap as
    # possible):
    # 1. RAR_DISABLED env var non-empty  -> silent exit.
    # 2. ~/.reflect-and-refine/.paused file exists -> silent exit.
    # Both exist so users can disable the hook from outside Claude Code
    # (e.g. from an old session that predates skill install, where the
    # /reflect-and-refine shutdown slash command isn't registered).
    if os.environ.get("RAR_DISABLED"):
        return
    if PAUSE_FLAG.exists():
        return

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        payload = json.loads(raw)
    except Exception as e:
        log_error(f"bad stdin: {e}")
        return

    transcript_path = payload.get("transcript_path", "")
    session_id = payload.get("session_id", "")
    if not transcript_path or not os.path.isfile(transcript_path):
        return

    try:
        config = load_config()
    except Exception as e:
        log_error(f"bad config: {e}")
        return

    registered = set(config.get("registered_skills", []))
    if not registered:
        return  # nothing registered -> never fire

    try:
        records = read_transcript(Path(transcript_path))
    except Exception as e:
        log_error(f"read transcript failed: {e}")
        return

    try:
        state, triggered_skill = gate_state(records, registered)
    except Exception as e:
        log_error(f"gate_state failed: {e}")
        return

    if state != "OPEN":
        return

    max_blocks = int(config.get("max_blocks_per_turn", DEFAULT_MAX_BLOCKS_PER_TURN))
    last_ts = last_user_timestamp(records)
    state_file = Path(f"/tmp/rar-{session_id or 'unknown'}.state")
    prior_count = 0
    try:
        if state_file.exists():
            parts = state_file.read_text().strip().split(maxsplit=1)
            if len(parts) == 2 and parts[0] == last_ts:
                prior_count = int(parts[1])
    except Exception:
        prior_count = 0

    should_block = increment_counter(session_id or "unknown", last_ts, max_blocks)
    if not should_block:
        audit_log(
            "RATE-LIMITED",
            session_id,
            {
                "reason": f"per-turn cap reached ({prior_count}/{max_blocks}); stop allowed",
                "turn_user_ts": last_ts,
            },
        )
        return

    try:
        request_text, agent_text = last_user_command_parts(records)
        prompt_path = resolve_prompt_path(triggered_skill, config)
        reason = build_block_reason(request_text, agent_text, prompt_path)
    except Exception as e:
        log_error(f"build reason failed: {e}")
        return

    # Quiet terminal by default: suppress the verbose reviewer-prompt dump
    # from the transcript display. The main agent still receives the full
    # `reason` in its context — only the user-visible terminal output is
    # collapsed. User can restore verbose mode by setting
    # "suppress_output": false in ~/.reflect-and-refine/config.json.
    suppress_output = bool(config.get("suppress_output", True))

    try:
        out = {"decision": "block", "reason": reason}
        if suppress_output:
            out["suppressOutput"] = True
        print(json.dumps(out))
        audit_log(
            "BLOCKED",
            session_id,
            {
                "count": f"{prior_count + 1}/{max_blocks}",
                "gate_trigger": f"/{triggered_skill} in transcript",
                "prompt_source": str(prompt_path).replace(str(HOME), "~"),
                "suppress_output": "on (quiet)" if suppress_output else "off (verbose)",
                "user_request_head": _head(request_text),
                "agent_response_head": _head(agent_text),
                "agent_response_full_chars": len(agent_text),
                "reviewer_reason_chars": len(reason),
            },
        )
    except Exception as e:
        log_error(f"emit failed: {e}")
        return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(f"uncaught: {traceback.format_exc()}")
        sys.exit(0)
