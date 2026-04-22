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

## Integration with parent skills

Parent skills register themselves at install time. Example `better-work` installer:

```bash
if [ -x ~/.better-work-series/reflect-and-refine/install.sh ]; then
  ~/.better-work-series/reflect-and-refine/install.sh --register better-work better-code better-test
fi
```

`reflect-and-refine` does not know about `better-work`; parents register themselves.

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
└── logs/                      # error logs (hook is fail-open, logs for debugging)
```

## Limitations

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
