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

- **Gate OPEN** when the most recent slash-command invocation in the transcript is a *registered*
  skill (the default registry contains only `reflect-and-refine` itself; parent skills add themselves).
- **Gate CLOSED** when the most recent slash-command invocation is `/reflect-and-refine shutdown`,
  or when no registered invocation is found in the transcript.
- **Rate limit**: within a single user turn, the gate blocks at most 3 times (configurable). After
  that it allows the stop so you can break out of loops.

There is no time-window expiry by default — activation persists until you explicitly shut it down
or start a new session.

## Subcommands

### `/reflect-and-refine activate`
Open the gate in this session without invoking another skill. A no-op convenience command —
the invocation itself leaves a marker in the transcript that the hook recognizes.

### `/reflect-and-refine shutdown`
Close the gate for the remainder of the session. Emits a shutdown marker. Can be reopened by
invoking any registered skill again (including `/reflect-and-refine activate`).

### `/reflect-and-refine status`
Show the current gate state, registered skills, and per-turn block count.

When invoked, read `~/.reflect-and-refine/config.json` and report:
- Registered skills
- `max_blocks_per_turn` setting
- Current turn's block count (from `/tmp/rar-<session-id>.state` if present)
- Last OPEN/CLOSED marker detected in this session's transcript

### `/reflect-and-refine register <skill-name> [<skill-name> ...]`
Append one or more skill names to the registered list in `~/.reflect-and-refine/config.json`.
After registration, invoking any of those skills opens the gate.

When invoked: read config, append names (de-duplicated), write back. Preserve unknown fields.

### `/reflect-and-refine unregister <skill-name> [<skill-name> ...]`
Remove skill names from the registered list.

## Configuration

Stored in `~/.reflect-and-refine/config.json`:

```json
{
  "registered_skills": ["reflect-and-refine"],
  "max_blocks_per_turn": 3
}
```

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
