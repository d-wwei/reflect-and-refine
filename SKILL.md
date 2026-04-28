---
name: reflect-and-refine
description: |
  Adversarial completion review at agent Stop time. When an active skill's gate is open,
  every time the main agent tries to stop, a mandatory adversarial review step runs to
  audit whether the user's original request is actually complete with concrete evidence.
  Use when: (1) you keep catching agents claiming "done" with hidden gaps;
  (2) you want a mechanical enforcement of completion standards on top of written
  protocols. Works in Claude Code and Codex; integrates loosely with any parent skill via registration.
  Subcommands: configure, status, shutdown, activate, register, unregister, audit, rate-limit, customize, pin, unpin, map.
---

# Reflect and Refine

Mechanical completion review: a Stop hook that forces the main agent through an independent
review step before it can claim "done". In Claude Code this is a reviewer sub-agent; in Codex it
uses a runtime-native reviewer when available, otherwise an explicit in-turn adversarial review.
The reviewer sees only the user's request and the agent's response, and must return a structured verdict.

## How the gate works

A per-session "gate" decides whether the review fires on a given Stop event.

**Which commands change gate state** (last one wins; query subcommands are transparent):

| Command | Effect |
|---------|--------|
| `/reflect-and-refine shutdown` | CLOSE |
| `/reflect-and-refine activate` (or empty args) | OPEN |
| `/reflect-and-refine status` / `audit` / `rate-limit` / `register` / `unregister` / `customize` / `pin` / `unpin` | **transparent** — gate state unchanged |
| `/<any-registered-parent-skill>` (e.g. `/better-work`, `/better-code`, `/better-test`) | OPEN |
| no command markers in transcript | CLOSED |

**Pin filter** (applied after gate-state decision): if a `/reflect-and-refine pin <skill>` directive is active, the hook fires only when the triggering skill equals `<skill>`. Other registered skills still appear in the transcript but are silently skipped. `/reflect-and-refine unpin` clears the filter.

Query/config subcommands of reflect-and-refine itself are intentionally transparent — running `/reflect-and-refine status` after a `shutdown` keeps the gate closed; running `/reflect-and-refine audit` in the middle of an active session keeps the gate open.

**Rate limit**: within a single user turn, the gate blocks at most `max_blocks_per_turn` times (default 3). After that it allows the stop so you can break out of loops.

There is no time-window expiry by default — activation persists until you explicitly shut it down or start a new session.

Once the gate is open, the hook classifies the stop into one of:
- `final_completion`
- `checkpoint_update`
- `needs_user_decision`
- `blocked_external`
- `exploratory_pause`

That stop intent is then combined with the current scenario. In practice this means a coding/testing checkpoint is no longer reviewed with the exact same questions as a claimed final completion.

## Subcommands

### `/reflect-and-refine configure`

**One-stop control panel**. Fully interactive — use this when you're not sure which specific subcommand to run. Shows the live state, offers one-click enable/disable, per-skill toggle, scenario mapping adjustment, and global pause/unpause.

**Dialog flow**:

1. **Read current state** — main agent runs:
   ```bash
   jq . ~/.reflect-and-refine/config.json
   ls -la ~/.reflect-and-refine/.paused 2>&1  # existence of pause flag
   ls ~/.claude/skills/ 2>/dev/null || true
   ls ~/.codex/skills/ 2>/dev/null || true
   ls ~/.agents/skills/ 2>/dev/null || true
   ls ~/.better-work-series/reflect-and-refine/prompts/scenarios/  # available scenarios (bundled)
   ls ~/.reflect-and-refine/prompts/scenarios/ 2>&1  # available scenarios (user)
   ```

2. **Present summary** like:
   ```
   === reflect-and-refine · current state ===
   Gate:           [ACTIVE | PAUSED via ~/.reflect-and-refine/.paused]
   Rate limit:     3 blocks / user turn
   Registered skills (3) — these auto-trigger the gate:
     ✓ better-code    → coding
     ✓ better-test    → testing
     ✓ better-work    → general
   Other detected skills not registered (union of ~/.claude/skills, ~/.codex/skills, ~/.agents/skills) (N):
     ○ great-writer
     ○ cognitive-kernel
     ○ labloop
     ○ ...
   Available scenarios: coding, testing, debugging, general (+ any user-added)
   ```

3. **Offer these options** (numbered list; let user pick one or "quit"):

   | # | Option | Effect |
   |---|--------|--------|
   | 1 | **Toggle individual skills** | Checklist UI: for each detected skill (union of `~/.claude/skills/`, `~/.codex/skills/`, `~/.agents/skills/`), show ✓ or ○; user flips as many as wanted; confirm before writing |
   | 2 | **Enable all detected skills** | Add every detected skill to `registered_skills`; default-map unmapped ones to `general` |
   | 3 | **Disable all** | Clear `registered_skills` to `[]`; gate will be CLOSED everywhere until you re-register something |
   | 4 | **Change scenario mapping** | For each registered skill show current scenario; ask which to change; offer `coding / testing / debugging / general / <new>` |
   | 5 | **Pause the hook globally** | `touch ~/.reflect-and-refine/.paused`; all sessions silent until unpause |
   | 6 | **Unpause** | `rm ~/.reflect-and-refine/.paused` |
   | 7 | **Adjust rate limit** | Short-circuit to `/reflect-and-refine rate-limit <N>` logic |
   | 8 | **Cancel** | Exit without changes |

4. **Apply change** — after user picks, run the sub-dialog for that option. Each sub-dialog ends with **preview + confirm** before writing anything. All changes use `jq` merge that preserves unknown fields in `config.json`.

5. **Show new state** — after applying, re-display the summary so user confirms the change landed.

6. **Offer follow-up** — "Anything else? (back to main menu / done)"

**Sub-dialog details**:

**Option 1 — Toggle individual**:
- Show each detected skill as `[✓|○] <name>  (scenario: <mapped-or-unmapped>)`. Build the list from the union of `~/.claude/skills/`, `~/.codex/skills/`, and `~/.agents/skills/`.
- Let user type a list of skill names to flip (or numbers if listed with indices).
- For each skill being ENABLED that has no scenario mapping, ask "which scenario?" (default: general).
- Write via jq merge.

**Option 2 — Enable all**:
- List everything about to be registered.
- Warn: "this will run reflect-and-refine's review on EVERY skill invocation. Token cost and review latency will scale accordingly."
- Confirm before applying. Default-map to `general` for skills without an existing mapping.

**Option 3 — Disable all**:
- Warn: "after this, no slash command will auto-trigger reflect-and-refine. You'll need to re-register or re-run `configure` to turn it back on."
- Confirm. Write `registered_skills: []` via jq.

**Option 4 — Scenario mapping**:
- For each registered skill, display `<skill> → <current scenario>` (or `(unmapped)`).
- Ask: "Which skill's mapping do you want to change? (name or 'done')".
- For the chosen skill, offer available scenarios + "new" (type new name) + "unmap".
- Write via jq merge into `reviewer.skill_scenario_map`.

**Option 5/6 — Pause/Unpause**:
- Simple: touch or rm the flag file, report success.

**Option 7 — Rate limit**:
- Ask for N.
- Apply the same validation as `/reflect-and-refine rate-limit`: reject 0/negative, accept 1–5 silent, 6–20 warn, >20 require `--force`.

**Principles** (same as customize):
- Never assume. Ask.
- Show defaults on every question.
- Allow back-stepping.
- Confirm before writing.
- All writes via jq merge — preserve unknown fields.

### `/reflect-and-refine activate`
Open the gate in this session without invoking another skill. A no-op convenience command —
the invocation itself leaves a marker in the transcript that the hook recognizes.

### `/reflect-and-refine shutdown`
Close the gate for the remainder of the session. Emits a shutdown marker. Can be reopened by
invoking any registered skill again (including `/reflect-and-refine activate`).

### `/reflect-and-refine pin <scenario-or-skill>`
Scope the gate to a **scenario** (preferred) or a **specific skill**. Default interpretation is scenario — explicit skill pinning requires the `skill` keyword.

**Scenario pin** (recommended — stable across skill churn):
```
/reflect-and-refine pin coding        # scope gate to any skill mapped to coding
/reflect-and-refine pin scenario coding   # same, explicit
/reflect-and-refine pin testing
```
The gate fires only for skills whose `skill_scenario_map` entry equals the pinned scenario. Unmapped skills (no scenario) will NOT trigger while a scenario pin is active.

**Skill pin** (escape hatch — use only when one specific skill needs isolation):
```
/reflect-and-refine pin skill better-code    # only /better-code triggers; other skills quiet
```

**Use cases**:
- Long coding session: `pin coding` → audits `/better-code`, `/dev-coder`, any mapped coding skill; quiet on `/better-test` side work.
- Debugging an incident: `pin debugging` → all debugging skills audited strictly; coding changes made during triage audited by their own scenario.
- Isolating one tool: `pin skill better-test` → only `/better-test` audited.

### `/reflect-and-refine unpin`
Clear any active pin — gate returns to "any registered skill triggers". Last pin/unpin directive in the transcript wins.

### `/reflect-and-refine map <skill> <scenario>`
Add or update a skill → scenario mapping in `~/.reflect-and-refine/config.json`. Enables scenario-based routing and scenario pins to include this skill.

```
/reflect-and-refine map my-custom-coder coding      # route my-custom-coder through coding.md
/reflect-and-refine map my-qa-assistant testing
```

When invoked: read config, set `reviewer.skill_scenario_map.<skill> = <scenario>`, write back preserving other fields. If `<scenario>` is not one of the built-in scenarios (coding / testing / debugging / general / or whatever files exist in `prompts/scenarios/`), warn but allow — the user may be about to create a new scenario file.

To remove a mapping, use `map <skill>` with no scenario, or edit config.json directly.

### `/reflect-and-refine status`
Show the current gate state, registered skills, per-turn block count, and whether any kill switch is active.

When invoked, read `~/.reflect-and-refine/config.json` and report:
- Registered skills
- `max_blocks_per_turn` setting
- Current turn's block count (from `/tmp/rar-<session-id>.state` if present)
- Last OPEN/CLOSED marker detected in this session's transcript
- Whether `~/.reflect-and-refine/.paused` exists (kill switch #1 active)
- Whether `RAR_DISABLED` env var is set on the current agent process (kill switch #2 active — inspect via the runtime's available env/process context if possible, else state it's unverifiable from inside the agent)

### `/reflect-and-refine register <skill-name> [<skill-name> ...]`
Append one or more skill names to the registered list in `~/.reflect-and-refine/config.json`.
After registration, invoking any of those skills opens the gate.

When invoked: read config, append names (de-duplicated), write back. Preserve unknown fields.

### `/reflect-and-refine unregister <skill-name> [<skill-name> ...]`
Remove skill names from the registered list.

### `/reflect-and-refine audit [<N>]`
Print the last N audit entries from `~/.reflect-and-refine/audit.md` (default N=5). Each hook fire that resulted in BLOCKED or RATE-LIMITED is recorded there with: timestamp, session, counter state, gate trigger, and head excerpts of the user request and agent response. Use this to see whether the hook is actually firing and what it saw — it is the primary visibility surface for human users.

If no audit file exists, say so (means the hook has never fired, or was always paused/closed).

### `/reflect-and-refine customize [<target-spec>]`

Fully interactive, guided wizard to create or edit a reviewer prompt. **Every entry point is dialog-driven** — the agent asks questions rather than assuming intent. Optional positional args shortcut the first step only.

**Invocation forms**:

| Form | First dialog step |
|------|------------------|
| `/reflect-and-refine customize` | "What would you like to customise? (default / scenario / skill)" |
| `/reflect-and-refine customize default` | Skip to default-edit dialog |
| `/reflect-and-refine customize scenario` | "Which scenario? (coding / testing / debugging / general / new)" |
| `/reflect-and-refine customize scenario coding` | Skip to coding-edit dialog |
| `/reflect-and-refine customize skill` | "Which skill do you want a per-skill override for?" |
| `/reflect-and-refine customize skill better-code` | Skip to skill-override dialog |

**Three target types and where the file lands**:

| Target | File location | Hook resolution layer | When to use |
|--------|---------------|---------------------|-------------|
| `default` | `~/.reflect-and-refine/prompts/default.md` | Layer 4 (fallback for unmapped skills) | Baseline for anything without a scenario mapping |
| `scenario <name>` | `~/.reflect-and-refine/prompts/scenarios/<name>.md` | Layer 3 (main path — skills routed here via `skill_scenario_map`) | Domain-level tuning; **recommended** |
| `skill <name>` | `~/.reflect-and-refine/prompts/overrides/<name>.md` + `config.json` `reviewer.per_skill.<name>` entry | Layer 1-2 (beats scenario) | Escape hatch when one specific skill needs unusual treatment |

**Dialog flow** (after target is known, same steps apply to all three targets):

1. **Overwrite check** — if the target file already exists, show its current values and ask: "Edit existing / overwrite fresh / cancel?"
2. **Language** — "Response language for the reviewer? (en / zh / free text)"
3. **Strictness** — offer three options with one-line descriptions:
   - `lenient` — flag only serious gaps
   - `default` — standard completion review
   - `strict` — assume the agent is cutting corners
4. **Model preference** — "Which reviewer model tier do you prefer when the runtime supports choosing one?":
   - `haiku` — fast + cheap (routine checks)
   - `sonnet` — balanced (most projects)
   - `opus` — deepest analysis (high-stakes reviews)
   - `default` — inherit the main session's model
5. **Dimensions** — multi-select from 7 built-ins (show as numbered list, let user toggle on/off):
   - 1. `requirement_split` — enumerate every distinct requirement
   - 2. `evidence` — each requirement must have concrete artifact
   - 3. `hedging` — flag "should"/"probably"/"likely"
   - 4. `silent_drops` — requirement silently dropped or deferred
   - 5. `fake_evidence` — references to nonexistent files / unrun tests
   - 6. `consistency` — internal consistency of the response
   - 7. `completeness` — implicit sub-questions also answered
   Suggest sensible defaults based on target type (e.g., coding scenario defaults lean toward evidence + fake_evidence).
6. **Custom checks** — "Any project-specific checks? (leave empty to skip)" — for each, collect `name` and one-line `description`. Let user add multiple in a loop.
7. **Preview** — show the agent the assembled YAML frontmatter and ask: "Looks right? (yes / adjust / cancel)"
8. **Write** — write the file:
   - Use the appropriate body template (bundled `reviewer-template.md` for fresh, or `prompts/scenarios/general.md` as a starting point for new scenarios)
   - Preserve all placeholders (`{USER_REQUEST}`, `{AGENT_RESPONSE}`, `{LANGUAGE}`, `{STRICTNESS_DIRECTIVE}`, `{MODEL_PREFERENCE_PARAM}`, `{DIMENSIONS_BLOCK}`, `{CUSTOM_CHECKS_BLOCK}`)
9. **Routing (skill-target only)** — if target was `skill <name>`, merge `.reviewer.per_skill.<name> = "prompts/overrides/<name>.md"` into config.json. For `default` and `scenario`, no config change needed.
10. **Confirm** — print the final file path and (for skill) the config routing. Tell the user: "Takes effect on the next hook fire — no restart needed; the hook rereads config and re-parses the prompt file on every Stop event."

**Principles**:

- **Never assume**: even with all positional args, the agent must still run through language/strictness/dimensions/custom_checks — those are the actual customisation work.
- **Show defaults**: on each question, show the current/default value so the user can press enter / say "keep".
- **Allow back-stepping**: if the user at step 7 says "adjust", go back to the relevant step(s) rather than restarting.
- **Be forgiving of target typos**: if the user says "scenario codeing" and there's no `codeing.md` in scenarios/, ask: "No scenario named 'codeing' exists. Create new / did you mean 'coding'?"
- **Mention scenario vs skill trade-off**: when user invokes `customize skill <x>`, remind: "Most users are better served by customising a scenario. Are you sure you want a per-skill override?" unless the answer is obvious.

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
  "registered_skills": ["reflect-and-refine", "better-work", "better-code", "better-test"],
  "max_blocks_per_turn": 3,
  "suppress_output": true,
  "reviewer": {
    "trigger_mode": "intent_sensitive",
    "trigger_mode_by_scenario": {
      "coding": "claim_done_only",
      "testing": "claim_done_only",
      "debugging": "intent_sensitive",
      "general": "intent_sensitive"
    },
    "skill_scenario_map": {
      "better-code": "coding",
      "better-test": "testing",
      "better-work": "general"
    },
    "per_skill": {}
  }
}
```

**`skill_scenario_map`** (main routing): skill name → scenario name. The hook looks up the scenario at trigger time and uses `prompts/scenarios/<scenario>.md`. Update via `/reflect-and-refine map <skill> <scenario>`.

**`reviewer.per_skill`** (escape hatch): skill name → absolute or relative path to a specific prompt file. Takes precedence over scenario lookup. Use when one skill needs treatment completely different from its domain scenario.

**`reviewer.trigger_mode`** / **`reviewer.trigger_mode_by_scenario`**: controls how aggressively Stop events are reviewed.
- `always` → every eligible Stop is reviewed
- `claim_done_only` → only stops classified as `final_completion`
- `intent_sensitive` → final completion plus user-facing pauses (`checkpoint_update`, `needs_user_decision`, `blocked_external`); exploratory pauses are skipped

**`suppress_output`** (default `true`): when true, the injected reviewer prompt dump does NOT render in the terminal. Claude Code currently collapses this well; Codex parses the field too, but terminal suppression may vary by runtime version. Set to `false` if you want maximal hook visibility while debugging.

## Emergency shutdown (without a slash command)

If you're in a session that was started BEFORE `reflect-and-refine` was installed, the command marker may not be available yet and `/reflect-and-refine shutdown` won't work. Two escape hatches work from any shell:

1. **Pause flag file** — the hook checks for `~/.reflect-and-refine/.paused` before doing any work. If present, it exits silently:
   ```bash
   touch ~/.reflect-and-refine/.paused     # pause
   rm    ~/.reflect-and-refine/.paused     # resume
   ```
2. **Env var on the agent process** — set `RAR_DISABLED=1` before launching the client:
   ```bash
   RAR_DISABLED=1 claude
   RAR_DISABLED=1 codex
   ```

Both are checked at the very top of the hook script, so the override is essentially free (no transcript read, no config parse).

## Install / uninstall

See `install.sh` and `uninstall.sh` in the skill root. The installer:

- writes the Claude Code Stop hook into user settings (auto-detects `ft-settings.json` vs `settings.json`)
- writes the Codex Stop hook into `~/.codex/hooks.json`
- installs skill symlinks for Claude Code and Codex skill locations
- preserves unrelated hooks via `jq` merge
- only enables Codex's experimental `codex_hooks` feature flag when explicitly asked (`./install.sh --enable-codex-feature-flag`)

**Hooks are loaded at client session start.** After install/uninstall you must restart Claude Code and Codex for the change to take effect.

## Limitations

- Requires Python 3 (macOS default includes it; Linux usually has it).
- `jq` required for install/uninstall (installer checks and errors clearly if missing).
- The reviewer step costs tokens per Stop event while the gate is open. Budget accordingly.
- The main agent can still try to manipulate what it feeds the reviewer. The hook pre-extracts
  transcript excerpts to reduce this risk, but strong adversarial behavior needs prompt iteration.
