# Changelog

All notable changes to `reflect-and-refine` are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use [SemVer](https://semver.org/).

## [Unreleased]

### Changed — file-based reviewer prompt (v0.3.1)
Cuts user-visible terminal noise per block by ~60%. The hook no longer
injects the full reviewer prompt inline — it writes the substituted
prompt to `~/.reflect-and-refine/sessions/<session-id>.md` and emits a
short reason (~770 chars, was ~1940) that tells the main agent: "Call
Task with prompt = read that file and return only the verdict JSON".
The Task subagent reads the file directly, keeping the main agent's
Task invocation short too.

Per-session files self-clean after 7 days (sweep on every hook fire).

Legacy prompt files with the old outer-`---`/inner-`---` wrapper
structure still work — `extract_reviewer_prompt_body()` detects the
two inner markers and uses only the content between them. All four
bundled scenario files (coding/testing/debugging/general) and the
reviewer-template.md fallback have been simplified to inner-only
structure so they read cleanly.

Audit log adds `session_file`, `short_reason_chars`, and
`reviewer_file_chars` fields.

## [0.2.2 / 0.3.0 retrospective]

### Added — scenario-based prompt binding (major architectural change)
- **Scenario layer** between skills and reviewer prompts. Reviewer prompts are now bound to workflow scenarios (`coding`, `testing`, `debugging`, `general`), not to skill names directly. `skill_scenario_map` in config.json maps skill → scenario; the hook resolves the prompt via scenario lookup. Downstream benefit: a new coding skill just needs a map entry, not a new prompt file.
- **3 specialised bundled scenarios** (`coding.md`, `testing.md`, `debugging.md`) written precisely — each has domain-specific role text + dimension selection + custom_checks. `general.md` ships as a baseline.
  - `coding` — hunts fabricated test output, placeholder code, unverified "should compile"
  - `testing` — strict by default; demands raw test output, edge case enumeration, no silenced tests
  - `debugging` — demands root cause (not symptom), pre-fix reproduction, post-fix verification, regression test, sibling-instance audit
- **`/reflect-and-refine map <skill> <scenario>`** subcommand to add/update skill→scenario mappings.
- **Scenario-scope pin**: `/reflect-and-refine pin <scenario>` (default interpretation) scopes the gate to only those skills mapped to the scenario. `pin skill <name>` remains as the escape hatch for specific-skill pinning. `find_pinned_skill()` replaced by `find_pin_directive()` returning `(scope, target)`.
- **Fully interactive customize wizard**. `/reflect-and-refine customize` with no args now asks "default / scenario / skill?" then branches. `customize scenario`, `customize scenario coding`, `customize skill`, `customize skill better-code` are all valid shortcut entry points; all still run the full question dialog for language/strictness/model/dimensions/custom_checks. Never assumes — every step shows defaults.
- Installer seeds `~/.reflect-and-refine/prompts/scenarios/` directory (empty on user side; hook falls through to bundled). `install.sh --register <skill>` now seeds sensible `skill_scenario_map` defaults for known series skills (better-code→coding, better-test→testing, better-work→general) without overwriting existing user choices.

### Added — smaller items
- `model_preference` (alias: `model`) frontmatter field so users can pin the reviewer sub-agent to `haiku` | `sonnet` | `opus`. `default`, empty, or any unrecognised value omits the `model` param from the Task call and lets Claude Code pick. Rendered into the prompt body via `{MODEL_PREFERENCE_PARAM}`.
- `tests/run.py` — 63-test stdlib-only suite covering frontmatter parsing, real-user filtering, gate-state semantics (all subcommands), pin directive scope (scenario vs skill), scenario lookup, dimension snippet assembly, custom-checks rendering, 5-layer prompt resolution, and end-to-end `build_block_reason` with model variants.
- User-visible error hint: when the hook silently fails (bad YAML, stdin parse error, etc.), one line is emitted to stderr pointing at `~/.reflect-and-refine/logs/`.
- SKILL.md frontmatter `Subcommands:` line updated to include `audit`, `rate-limit`, `customize`, `pin`, `unpin`, `map` (a prior bug — the three were missing from the declaration since v0.1.3/v0.1.4/v0.2.0).

### Changed
- Audit log records `triggered_scenario` and `pinned_to` (with scope) so you can see the full context of each block.
- Prompt resolution expands from 4 layers to 5 (scenario lookup inserted as layer 3).

### Fixed
- Unknown `/reflect-and-refine` subcommand now falls through as transparent (doesn't change gate state) — was previously "fail-safe open".
- `suppressOutput=true` on block decision prevents the reviewer prompt wall from rendering in the terminal (collapsed to `Ran 1 stop hook` summary). Main agent still sees the full reason.
- `is_real_user_record()` correctly filters hook injections (`isMeta: true`) and tool results, preventing the hook from grabbing its own prior injections as user input.

## [0.2.0] — 2026-04-23 · commit `14f16d9`

### Added
- **Structured reviewer prompts**: `prompts/reviewer-template.md` now has a YAML frontmatter header exposing `language`, `strictness` (lenient | default | strict), `dimensions` (multi-select from 7 built-in names), and `custom_checks` (list of `{name, description}` dicts). Body uses placeholders the hook fills at run time: `{USER_REQUEST}`, `{AGENT_RESPONSE}`, `{LANGUAGE}`, `{STRICTNESS_DIRECTIVE}`, `{DIMENSIONS_BLOCK}`, `{CUSTOM_CHECKS_BLOCK}`.
- **Dimension snippet pool**: 7 dimensions (`requirement_split`, `evidence`, `hedging`, `silent_drops`, `fake_evidence`, `consistency`, `completeness`) × 3 strictness levels = 21 short snippets embedded in `stop-gate.py` as `DIMENSION_SNIPPETS`. Selecting a dimension renders the matching-strictness snippet into the numbered `{DIMENSIONS_BLOCK}`.
- **Per-skill prompt routing**: `gate_state()` now returns `(state, triggered_skill)`. `resolve_prompt_path()` performs 4-layer fallback: explicit `config.reviewer.per_skill.<skill>` → `~/.reflect-and-refine/prompts/overrides/<skill>.md` → `~/.reflect-and-refine/prompts/default.md` → bundled `prompts/reviewer-template.md`.
- **`/reflect-and-refine customize [<skill>]` wizard**: 9-step interactive dialog (target skill → language → strictness → dimensions → custom checks → preview → confirm → write file → update config routing). Declarative in SKILL.md; the main agent orchestrates.
- Minimal YAML frontmatter parser (stdlib-only) supporting scalars, string lists, and list-of-dicts (for `custom_checks`). No PyYAML dependency.
- Installer seeds `~/.reflect-and-refine/prompts/default.md` (copied from bundled template) and creates `~/.reflect-and-refine/prompts/overrides/` directory.
- Audit log records `prompt_source` field so you can see which prompt file a given block used.
- `config.json` default includes `"reviewer": {"per_skill": {}}` and `"suppress_output": true` on fresh installs.

### Fixed
- **Gate bug: unknown subcommand no longer activates.** `/reflect-and-refine <typo>` or a command we don't recognise is now transparent (does not change gate state) instead of the old fail-safe-activate. `activate` and empty args still open; `shutdown` still closes; `status` / `audit` / `rate-limit` / `register` / `unregister` / `customize` are all explicit idempotent queries.

## [0.1.7] — 2026-04-23 · commit `e6b4bef`

### Removed
- First-time session banner. Since v0.1.6 suppresses hook output by default, the user-visible banner was dead code — the context was costing tokens with no user signal. Audit log drops the `banner_shown` field.

### Changed
- Reviewer template rewritten as flat structure (no `## Step 1 / Step 2 / Step 3` nesting). Hook pre-fills both `{USER_REQUEST}` and `{AGENT_RESPONSE}` directly; the main agent just copies a pre-baked block between `---` markers to the Task tool. Template shrinks from 3597 → 1829 chars (-49%). Total injected reason (banner + template) drops from ~4023 to ~1829 — 55% smaller.

## [0.1.6] — 2026-04-23 · commit `bf53641`

### Added
- **Quiet terminal output by default.** Hook emits `"suppressOutput": true` on its block decision so Claude Code collapses the reviewer prompt dump behind its standard `Ran 1 stop hook (ctrl+o to expand)` summary. The main agent still receives the full `reason` in its context; only the user-visible terminal rendering is suppressed.
- `"suppress_output"` config.json field. Default `true`; set `false` to restore verbose terminal rendering for debugging.
- Audit log records `suppress_output: on (quiet) | off (verbose)` per block.

## [0.1.5] — 2026-04-23 · commits `1f29a8f`, `0439742`

### Added
- **First-time session banner**: the first block per session prepends a banner explaining why reflect-and-refine is active and how to disable it (`/reflect-and-refine shutdown`, `.paused` flag, `RAR_DISABLED=1`). Tracked via `/tmp/rar-<session>.banner-shown`.

### Fixed
- Transparent query subcommands. `/reflect-and-refine status / audit / rate-limit / register / unregister` no longer re-open the gate after a shutdown. `IDEMPOTENT_RAR_SUBCOMMANDS` set added to `gate_state` logic.

## [0.1.4] — 2026-04-23 · commit `d2739cc`

### Added
- Append-only markdown audit log at `~/.reflect-and-refine/audit.md`. Every `BLOCKED` and `RATE-LIMITED` event records timestamp, session prefix, counter state, gate trigger, and head excerpts of user request + agent response.
- `/reflect-and-refine audit [<N>]` subcommand to print the last N entries.

## [0.1.3] — 2026-04-23 · commit `cc583fd`

### Added
- `/reflect-and-refine rate-limit [<N>] [--force]` subcommand. Adjusts `max_blocks_per_turn` at run time without editing config.json by hand. Validation: `0` or negative rejected (use `.paused`); `1–5` silent; `6–20` warns; `>20` requires `--force`.

## [0.1.2] — 2026-04-22 · commit `02727b3`

### Added
- **Emergency shutdown kill switches** for sessions that started before the skill was installed:
  - `~/.reflect-and-refine/.paused` flag file — file-based, all sessions silent immediately.
  - `RAR_DISABLED` environment variable — set before launching `claude` to disable for that process.

## [0.1.1] — 2026-04-22 · commit `f5a5264`

### Fixed
- **Transcript extraction bugs** surfaced during first real-world smoke test:
  - `user_request` was being polluted by the hook's own prior injections (which appear in the transcript as `type: user, isMeta: true`). Added `is_real_user_record()` filter.
  - `agent_response` only captured the last assistant text record. Now concatenates all assistant text blocks after the last real user message, joined with `\n\n`, capped at 8000 chars.

## [0.1.0] — 2026-04-22 · commits `762f736` → `4445003`

### Added
- Initial release: Stop hook (`hooks/stop-gate.py`) that injects an adversarial reviewer prompt when a registered skill is active in the session.
- Registry-based activation: `config.json` lists registered skills; any slash-command invocation of a registered skill opens the gate.
- Per-turn rate limiting (default 3 blocks per user turn).
- `install.sh` / `uninstall.sh` — safe jq-based merge into `~/.claude/ft-settings.json` or `~/.claude/settings.json`; preserves existing hooks; creates symlink under `~/.claude/skills/`.
- Subcommands: `activate`, `shutdown`, `status`, `register`, `unregister`.
- MIT license.
