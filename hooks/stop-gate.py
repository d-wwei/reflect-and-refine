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
SKILL_ROOT = Path(__file__).resolve().parent.parent
PROMPT_TEMPLATE = SKILL_ROOT / "prompts" / "reviewer-template.md"

SHUTDOWN_MARKER_ARGS = "shutdown"
DEFAULT_MAX_BLOCKS_PER_TURN = 3
AUDIT_HEAD_MAX = 150  # chars to show in audit excerpts

# Subcommands of /reflect-and-refine that are query/config — they MUST NOT
# be treated as activation markers. Only `shutdown` closes the gate;
# `activate` (or empty args) opens it; anything else listed here is
# transparent to gate state.
IDEMPOTENT_RAR_SUBCOMMANDS = {"status", "audit", "rate-limit", "register", "unregister"}


def log_error(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logfile = LOG_DIR / f"errors-{datetime.now():%Y%m%d}.log"
        with logfile.open("a") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass  # last-resort: don't let logging itself break us


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


def gate_state(records: list[dict], registered_skills: set[str]) -> str:
    """
    Scan real user records from newest to oldest. Return 'OPEN' or 'CLOSED'.

    Rules (last matching real-user command wins; query subcommands are transparent):
    - /reflect-and-refine shutdown              -> CLOSED
    - /reflect-and-refine activate | (no args)  -> OPEN
    - /reflect-and-refine <idempotent-query>    -> skip (doesn't change state)
    - /<any-other-registered-skill>             -> OPEN
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
                return "CLOSED"
            if first_arg in IDEMPOTENT_RAR_SUBCOMMANDS:
                continue  # query/config — transparent to gate state
            # activate, empty, or unknown subcommand -> fail-safe OPEN
            return "OPEN"

        if skill in registered_skills:
            return "OPEN"
    return "CLOSED"


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


def build_block_reason(request_text: str, agent_text: str) -> str:
    tpl = PROMPT_TEMPLATE.read_text()
    return tpl.replace("{USER_REQUEST}", request_text or "(transcript did not yield a clear user request — review based on the full transcript)") \
              .replace("{AGENT_RESPONSE}", agent_text or "(no prior assistant text extracted)")


SESSION_BANNER = (
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "REFLECT-AND-REFINE ACTIVE · First review this session.\n"
    "  Active because: a registered skill was invoked in this session.\n"
    "  Disable for this session: /reflect-and-refine shutdown\n"
    "  Persistent disable:       touch ~/.reflect-and-refine/.paused\n"
    "  Settings:                 /reflect-and-refine status | rate-limit <N>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
)


def maybe_prepend_banner(reason: str, session_id: str) -> tuple[str, bool]:
    """
    On the first hook block of a session, prepend a banner so the user sees why
    reflect-and-refine is active and how to disable it. Tracked via a marker
    file in /tmp so it self-expires on reboot.
    Returns (reason_possibly_with_banner, banner_was_shown).
    """
    marker = Path(f"/tmp/rar-{session_id or 'unknown'}.banner-shown")
    if marker.exists():
        return reason, False
    try:
        marker.touch()
    except Exception as e:
        log_error(f"banner marker write failed: {e}")
        # If we can't mark it, showing the banner twice is still acceptable;
        # proceed to show.
    return SESSION_BANNER + reason, True


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
        state = gate_state(records, registered)
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
        reason = build_block_reason(request_text, agent_text)
        reason, banner_shown = maybe_prepend_banner(reason, session_id or "unknown")
    except Exception as e:
        log_error(f"build reason failed: {e}")
        return

    try:
        out = {"decision": "block", "reason": reason}
        print(json.dumps(out))
        audit_log(
            "BLOCKED",
            session_id,
            {
                "count": f"{prior_count + 1}/{max_blocks}",
                "gate_trigger": "registered skill invocation in transcript",
                "banner_shown": "yes (first block this session)" if banner_shown else "no",
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
