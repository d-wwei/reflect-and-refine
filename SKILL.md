---
name: reflect-and-refine
description: |
  Adversarial completion review at agent Stop time. When an active skill's gate is open,
  every time the main agent tries to stop, a mandatory reviewer sub-agent is spawned to
  audit whether the user's original request is actually complete with concrete evidence.
  Use when: (1) you keep catching agents claiming "done" with hidden gaps;
  (2) you want a mechanical enforcement of completion standards on top of written
  protocols. Works standalone; integrates loosely with any parent skill via registration.
  Subcommands: status, shutdown, activate, register, unregister.
---

# Reflect and Refine

Mechanical completion review: a Stop hook that forces the main agent to spawn an independent
reviewer sub-agent before it can claim "done". The reviewer has no skin in the game, sees only
the user's request and the agent's response, and must return a structured verdict.

## How the gate works

A per-session "gate" decides whether the review fires on a given Stop event.

**Which commands change gate state** (last one wins; query subcommands are transparent):

| Command | Effect |
|---------|--------|
| `/reflect-and-refine shutdown` | CLOSE |
| `/reflect-and-refine activate` (or empty args) | OPEN |
| `/reflect-and-refine status` / `audit` / `rate-limit` / `register` / `unregister` | **transparent** — gate state unchanged |
| `/<any-registered-parent-skill>` (e.g. `/better-work`, `/better-code`, `/better-test`) | OPEN |
| no command markers in transcript | CLOSED |

Query/config subcommands of reflect-and-refine itself are intentionally transparent — running `/reflect-and-refine status` after a `shutdown` keeps the gate closed; running `/reflect-and-refine audit` in the middle of an active session keeps the gate open.

**First-time session banner**: the first time the hook blocks in a session, the injected reason is prefixed with a one-time banner explaining *why* reflect-and-refine is active and *how* to disable it (`/reflect-and-refine shutdown`, `.paused` flag, or `RAR_DISABLED=1`). Tracked via `/tmp/rar-<session>.banner-shown` — self-expires on reboot.

**Rate limit**: within a single user turn, the gate blocks at most `max_blocks_per_turn` times (default 3). After that it allows the stop so you can break out of loops.

There is no time-window expiry by default — activation persists until you explicitly shut it down or start a new session.

## Subcommands

### `/reflect-and-refine activate`
Open the gate in this session without invoking another skill. A no-op convenience command —
the invocation itself leaves a marker in the transcript that the hook recognizes.

### `/reflect-and-refine shutdown`
Close the gate for the remainder of the session. Emits a shutdown marker. Can be reopened by
invoking any registered skill again (including `/reflect-and-refine activate`).

### `/reflect-and-refine status`
Show the current gate state, registered skills, per-turn block count, and whether any kill switch is active.

When invoked, read `~/.reflect-and-refine/config.json` and report:
- Registered skills
- `max_blocks_per_turn` setting
- Current turn's block count (from `/tmp/rar-<session-id>.state` if present)
- Last OPEN/CLOSED marker detected in this session's transcript
- Whether `~/.reflect-and-refine/.paused` exists (kill switch #1 active)
- Whether `RAR_DISABLED` env var is set on the Claude Code process (kill switch #2 active — inspect via the transcript's env info if available, else state it's unverifiable from the agent)

### `/reflect-and-refine register <skill-name> [<skill-name> ...]`
Append one or more skill names to the registered list in `~/.reflect-and-refine/config.json`.
After registration, invoking any of those skills opens the gate.

When invoked: read config, append names (de-duplicated), write back. Preserve unknown fields.

### `/reflect-and-refine unregister <skill-name> [<skill-name> ...]`
Remove skill names from the registered list.

### `/reflect-and-refine audit [<N>]`
Print the last N audit entries from `~/.reflect-and-refine/audit.md` (default N=5). Each hook fire that resulted in BLOCKED or RATE-LIMITED is recorded there with: timestamp, session, counter state, gate trigger, and head excerpts of the user request and agent response. Use this to see whether the hook is actually firing and what it saw — it is the primary visibility surface for human users.

If no audit file exists, say so (means the hook has never fired, or was always paused/closed).

### `/reflect-and-refine rate-limit [<N>] [--force]`
Get or set `max_blocks_per_turn` — how many times the hook may block consecutively within one user turn before giving up and allowing the stop.

- **No argument** → print the current value.
- **Positive integer N** → set to N, with the following validation:
  - `N == 0` or negative → reject with message: "use `touch ~/.reflect-and-refine/.paused` to disable; rate-limit sets strictness, not on/off."
  - `1 ≤ N ≤ 5` → accept silently.
  - `6 ≤ N ≤ 20` → accept **with warning**: "heads-up: with max_blocks_per_turn=<N>, a single user turn may contain up to <N> reviewer rounds, which will take longer and cost more tokens."
  - `N > 20` or non-integer → reject **unless `--force` is also passed**. With `--force`, accept regardless (still warn if feasible).

When invoked: read config, validate per above, write `max_blocks_per_turn` with jq-style merge (preserve `registered_skills` and any unknown fields), report new value and any warning.

Change takes effect immediately — the hook re-reads config.json on every Stop event, so no restart or new session needed.

## Configuration

Stored in `~/.reflect-and-refine/config.json`:

```json
{
  "registered_skills": ["reflect-and-refine"],
  "max_blocks_per_turn": 3,
  "suppress_output": true
}
```

**`suppress_output`** (default `true`): when true, the injected reviewer prompt dump does NOT render in the terminal — Claude Code shows only a brief "Ran 1 stop hook" summary line (collapsed; press ctrl+o to expand). The main agent still receives the full instructions in its context. Set to `false` if you want to see the full prompt in the terminal for debugging. First-time session banner is also suppressed in quiet mode.

## Emergency shutdown (without a slash command)

If you're in a Claude Code session that was started BEFORE `reflect-and-refine` was installed, the `/reflect-and-refine` slash command isn't registered and `/reflect-and-refine shutdown` won't work. Two escape hatches work from any shell:

1. **Pause flag file** — the hook checks for `~/.reflect-and-refine/.paused` before doing any work. If present, it exits silently:
   ```bash
   touch ~/.reflect-and-refine/.paused     # pause
   rm    ~/.reflect-and-refine/.paused     # resume
   ```
2. **Env var on Claude Code's process** — set `RAR_DISABLED=1` before launching `claude`:
   ```bash
   RAR_DISABLED=1 claude
   ```

Both are checked at the very top of the hook script, so the override is essentially free (no transcript read, no config parse).

## Install / uninstall

See `install.sh` and `uninstall.sh` in the skill root. The installer writes the Stop hook entry
into your Claude Code user settings (auto-detects `ft-settings.json` vs `settings.json`),
backing up first, and merges via `jq` so other hooks are preserved.

**Hooks are loaded at Claude Code session start.** After install/uninstall you must exit and
restart Claude Code for the change to take effect.

## Limitations

- Requires Python 3 (macOS default includes it; Linux usually has it).
- `jq` required for install/uninstall (installer checks and errors clearly if missing).
- The reviewer sub-agent costs tokens per Stop event while the gate is open. Budget accordingly.
- The main agent can still try to manipulate what it feeds the reviewer. The hook pre-extracts
  transcript excerpts to reduce this risk, but strong adversarial behavior needs prompt iteration.
