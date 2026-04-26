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

### Quick-start control panel

```
/reflect-and-refine configure
```

One interactive wizard covers everything most users need:
- Toggle which skills auto-trigger the gate
- Enable all installed skills at once (or disable all)
- Change the scenario mapping (which prompt each skill uses)
- Pause or unpause the hook globally
- Adjust the per-turn rate limit

Use this if you're unsure which specific subcommand to run.

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
| **`/reflect-and-refine configure`** | **Interactive control panel — toggle skills on/off, enable/disable all, change scenario mapping, pause/unpause. Best starting point if unsure.** |
| `/reflect-and-refine register <name> ...` | Append skills to the registry (CLI-style shortcut for `configure → option 1`) |
| `/reflect-and-refine unregister <name> ...` | Remove skills from the registry |
| `/reflect-and-refine rate-limit [<N>]` | Get or set `max_blocks_per_turn`. Range 1–5 silent, 6–20 warns, >20 requires `--force`. 0/negative rejected (use `.paused` instead). |
| `/reflect-and-refine audit [<N>]` | Print last N audit entries (default 5). See `~/.reflect-and-refine/audit.md` for full history. |
| `/reflect-and-refine customize [<skill>]` | Interactive wizard to tune the reviewer (language, strictness, dimensions, project-specific checks) for one skill or the global default. Writes a structured markdown file with YAML frontmatter + placeholders. |

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
├── config.json                # registered_skills, max_blocks_per_turn, suppress_output, reviewer.per_skill
├── audit.md                   # human-readable append-only log of every BLOCKED / RATE-LIMITED event
├── prompts/
│   ├── default.md             # user-level default reviewer (seeded on install, hand-editable)
│   └── overrides/
│       └── <skill>.md         # per-skill override (created by `/reflect-and-refine customize <skill>`)
├── .paused                    # (optional) kill-switch flag file
└── logs/                      # error logs (hook is fail-open, logs for debugging)
```

## Customising the reviewer — scenarios vs skills

reflect-and-refine binds prompts to **scenarios** (stable workflow categories), not directly to skill names. A skill like `/better-code` is mapped to the `coding` scenario; when it triggers the gate, the `coding` reviewer prompt is used. This way:

- Adding a new coding skill (`/dev-coder`, `/claude-code`, whatever) just needs a map entry, not a new prompt file.
- Improving the `coding` reviewer improves review for ALL coding skills at once.
- Prompts don't rot when skill names change.

### Built-in scenarios

| Scenario | Specialised for | Default strictness |
|----------|----------------|-------------------|
| `general` | Fallback, no specialisation | default |
| `coding` | Source code changes — hunts fabricated test output, placeholder code, unverified "should compile" | default |
| `testing` | Test authorship + runs — demands raw test output, edge cases enumerated, no silenced tests | **strict** |
| `debugging` | Bug diagnosis + fixes — demands root cause (not symptom), pre-fix reproduction, post-fix verification, regression test | default |

Each lives at `<install_root>/prompts/scenarios/<name>.md` (bundled) or `~/.reflect-and-refine/prompts/scenarios/<name>.md` (user override — created on first `customize`).

### Three ways to customise

1. **Quickest — frontmatter edit**: open the scenario file (or default.md), change `language`, `strictness`, `model`, or the `dimensions` list. Takes effect on the next Stop event (hook rereads on every fire).
2. **Guided — fully interactive wizard**: `/reflect-and-refine customize` (no args) — agent asks "default / scenario / skill?" then walks you through language, strictness, model, dimensions, custom checks. Every step has a default; you can just accept. Works for any target type.
3. **Power-user — hand-written body**: copy `<install_root>/prompts/scenarios/general.md` as a starting point, rewrite role text / verdict schema / action protocol. Placeholders honoured by the hook: `{USER_REQUEST}`, `{AGENT_RESPONSE}`, `{LANGUAGE}`, `{STRICTNESS_DIRECTIVE}`, `{MODEL_PREFERENCE_PARAM}`, `{DIMENSIONS_BLOCK}`, `{CUSTOM_CHECKS_BLOCK}`.

### Adding a new scenario

```
/reflect-and-refine customize scenario          # wizard; type a new name when prompted
/reflect-and-refine map my-research-skill research   # route the skill to it
```

The scenario file lives at `~/.reflect-and-refine/prompts/scenarios/<name>.md` and is edited like any built-in.

### Mapping a new skill

```
/reflect-and-refine map <skill> <scenario>
```

Or edit `config.json` → `reviewer.skill_scenario_map.<skill>` directly. Unmapped skills fall through to `default.md`.

### Prompt resolution order (highest priority first)

```
1. config.reviewer.per_skill.<skill>                      (skill-level file mapping — rare)
2. ~/.reflect-and-refine/prompts/overrides/<skill>.md     (skill-level file override)
3. scenario lookup: skill_scenario_map[<skill>] →
   a. ~/.reflect-and-refine/prompts/scenarios/<scenario>.md   (user)
   b. <install_root>/prompts/scenarios/<scenario>.md          (bundled)
4. ~/.reflect-and-refine/prompts/default.md                (user default)
5. <install_root>/prompts/reviewer-template.md             (bundled final fallback)
```

Layers 1–2 are escape hatches; layer 3 (scenario) is the main path.

### Pinning: scope the gate to one scenario or skill

```
/reflect-and-refine pin coding               # only skills mapped to coding trigger
/reflect-and-refine pin scenario testing     # same, explicit
/reflect-and-refine pin skill better-test    # only /better-test triggers (escape hatch)
/reflect-and-refine unpin                    # clear
```

### Built-in dimensions (used inside scenarios / default / skill overrides)

Each can be toggled via the `dimensions` list in frontmatter; the hook renders each name using its internal snippet (one of three strictness variants):

| Name | What it checks |
|------|---------------|
| `requirement_split` | Every distinct requirement enumerated? |
| `evidence` | Concrete artifact (file:line, command output, test result) for each? |
| `hedging` | "Should work" / "probably" / "likely" / "I believe"? |
| `silent_drops` | Any requirement dropped or deferred without disclosure? |
| `fake_evidence` | References to files that don't exist, unrun tests, contradictions? |
| `consistency` | Internal consistency across the response? |
| `completeness` | Implicit sub-questions also answered? |

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
