# reflect-and-refine

Adversarial completion review at Stop time for Claude Code agents.

When the main agent tries to claim "done", a Stop hook forces it to spawn an **independent reviewer sub-agent** that audits whether the user's original request is actually complete with concrete evidence. The reviewer has no skin in the game, sees only the facts (request + response), and must return a structured verdict.

If the verdict is `incomplete` or `fake_evidence`, the agent is told to continue. Only `approved` lets it stop.

## Why this exists

Agents routinely:
- Claim "done" with silent gaps ("forgot to run the tests", "dropped half the requirements")
- Halt citing vague worries ("context is running low", "this should probably work")
- Produce "evidence" that's really just reassurances ("it should work", "looks good")

Written protocols (CLAUDE.md, skill guidance) help but are often bypassed in the moment. `reflect-and-refine` is the **mechanical backstop**: a hook-based checkpoint the agent cannot simply talk its way past.

## How the gate works

A per-session **gate** decides whether the review fires on a given Stop event.

- **OPEN** when the most recent slash-command invocation in the transcript is a *registered* skill.
- **CLOSED** when the last marker is `/reflect-and-refine shutdown` or there are no registered invocations.
- **Rate-limited** to 3 blocks per user turn so you never get stuck in an infinite loop.

The default registry contains only `reflect-and-refine` itself. Parent skills (like `better-work`) add themselves via `install.sh --register`.

No time window by default — once activated, the gate stays open until you `shutdown` or start a new session.

## Install (standalone)

Requires: `jq`, `python3`, Claude Code.

```bash
git clone https://github.com/d-wwei/reflect-and-refine.git
cd reflect-and-refine
./install.sh
```

Then **exit and restart Claude Code**:

```bash
/exit
claude
```

Activate in a session:

```
/reflect-and-refine activate
```

Any subsequent stop will trigger the review until you `/reflect-and-refine shutdown`.

### Install with parent skills pre-registered

```bash
./install.sh --register better-work better-code better-test
```

After this, invoking `/better-work`, `/better-code`, or `/better-test` will also open the gate.

## Usage

| Command | Effect |
|---------|--------|
| `/reflect-and-refine activate` | Open the gate in this session (marker-only; no state file) |
| `/reflect-and-refine shutdown` | Close the gate until re-activated |
| `/reflect-and-refine status` | Show registry, rate limit, current turn block count |
| `/reflect-and-refine register <name> ...` | Append skills to the registry |
| `/reflect-and-refine unregister <name> ...` | Remove skills from the registry |
| `/reflect-and-refine rate-limit [<N>]` | Get or set `max_blocks_per_turn`. Range 1–5 silent, 6–20 warns, >20 requires `--force`. 0/negative rejected (use `.paused` instead). |
| `/reflect-and-refine audit [<N>]` | Print last N audit entries (default 5). See `~/.reflect-and-refine/audit.md` for full history. |

## Integration with parent skills

Parent skills register themselves at install time. Example `better-work` installer:

```bash
if [ -x ~/.better-work-series/reflect-and-refine/install.sh ]; then
  ~/.better-work-series/reflect-and-refine/install.sh --register better-work better-code better-test
fi
```

`reflect-and-refine` does not know about `better-work`; parents register themselves.

## Emergency shutdown (from any shell)

If the `/reflect-and-refine` slash command isn't available (e.g. you installed mid-session and the current Claude Code session can't see new skills), you still have two kill switches that work from outside Claude Code:

```bash
# Pause the hook (file-based kill switch — hook checks before any work)
touch ~/.reflect-and-refine/.paused
# Resume
rm ~/.reflect-and-refine/.paused
```

```bash
# Per-launch override (env var — set before launching claude)
RAR_DISABLED=1 claude
```

Both are checked at the top of the hook script before transcript or config is read, so the override is cheap.

## Uninstall

```bash
./uninstall.sh           # removes hook, preserves config
./uninstall.sh --purge   # also deletes ~/.reflect-and-refine/
```

Restart Claude Code for the removal to take effect.

## Files

```
reflect-and-refine/
├── SKILL.md                   # skill entry (loaded by Claude Code)
├── install.sh / uninstall.sh  # cross-platform installer
├── hooks/
│   └── stop-gate.py           # the hook script (invoked per Stop)
└── prompts/
    └── reviewer-template.md   # the block reason injected into the main agent
```

User state:

```
~/.reflect-and-refine/
├── config.json                # registered_skills, max_blocks_per_turn
├── audit.md                   # human-readable append-only log of every BLOCKED / RATE-LIMITED event
├── .paused                    # (optional) kill-switch flag file
└── logs/                      # error logs (hook is fail-open, logs for debugging)
```

## Auditability (for humans)

Every time the hook takes action it appends a markdown entry to `~/.reflect-and-refine/audit.md`. The file is meant for human review — open in any editor, grep, or `tail -n 50`. Example entry:

```markdown
---
## 2026-04-23 00:58:07 UTC · session=abc12345 · event=BLOCKED
- **count**: 1/3
- **gate_trigger**: registered skill invocation in transcript
- **user_request_head**: "2要做的。另外还要加一个审计面板..."
- **agent_response_head**: "两个任务安排：先做审计面板..."
- **agent_response_full_chars**: 110
- **reviewer_reason_chars**: 3739
```

Events logged: `BLOCKED` (reason was injected), `RATE-LIMITED` (would have blocked but per-turn cap reached). Silent passes (gate closed, paused, env-disabled) are not logged by default — their absence in the audit log is itself the signal.

## Limitations

- **Quiet by default**: the injected reviewer prompt is sent to the main agent's context but NOT rendered in the terminal (via `suppressOutput`). You'll see Claude Code's brief "Ran 1 stop hook" line instead of a 4000-character wall. To restore verbose terminal output, set `"suppress_output": false` in `~/.reflect-and-refine/config.json`.
- **Main agent can still try to game the reviewer** by biasing the prompt it constructs. The hook pre-extracts transcript excerpts to reduce this; strong adversarial behavior needs prompt iteration over time.
- **Reviewer costs tokens per Stop** while the gate is open. If the gate is open all session, every stop triggers a sub-agent call. Budget accordingly.
- **Requires Claude Code session restart** to load/unload the hook (hooks are session-scope, not hot-reloadable).
- **Cross-platform auth**: relies on `Task` tool being available in the main session, which uses the session's own auth. Does NOT spawn external `claude -p` processes, so Futu-internal builds work fine.
- **Single-session state**: rate-limit counter is per session. Parallel sessions do not interfere.

## Design decisions

See `docs/DESIGN.md` (TODO — extract from conversation log) for the full reasoning. High-level:

- Chose Task sub-agent over `claude -p` subprocess → no auth/plumbing issues across Claude Code forks.
- Chose command-type Stop hook over prompt-type → prompt type has ecosystem coverage gaps; command type is universally supported.
- Chose registry + transcript grep over flag files → activation happens automatically when parent skills are invoked, no manual `touch` needed.
- Chose per-turn rate limit (3) over time-based → clear semantics, tied to user intent.

## License

MIT. Author: eli🥑 ([@d-wwei](https://github.com/d-wwei)).
