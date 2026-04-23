---
# ╔═══════════════════════════════════════════════════════════════╗
# ║ Scenario: GENERAL                                              ║
# ║ Fallback for work that doesn't fit a specialised scenario.     ║
# ║ This mirrors default.md at install time; diverge as you like.  ║
# ║                                                                ║
# ║ When a skill is NOT in skill_scenario_map, the hook falls      ║
# ║ through to default.md (one layer below this file). This file   ║
# ║ is used only when a skill is explicitly mapped to "general".   ║
# ╚═══════════════════════════════════════════════════════════════╝

language: en
strictness: default
model: default

dimensions:
  - requirement_split
  - evidence
  - hedging
  - silent_drops
  - fake_evidence

custom_checks: []
---

[REFLECT-AND-REFINE] Completion review required before stop.

Call the Task tool with these parameters:
- `subagent_type`: `general-purpose`
{MODEL_PREFERENCE_PARAM}- `description`: `Completion reviewer`
- `prompt`: copy the block below between the `---` markers verbatim — the hook has already substituted all placeholders, so no further editing is needed.

---
{STRICTNESS_DIRECTIVE}

Respond in: {LANGUAGE}.

USER'S ORIGINAL REQUEST:
{USER_REQUEST}

AGENT'S MOST RECENT RESPONSE:
{AGENT_RESPONSE}

Check these dimensions:
{DIMENSIONS_BLOCK}

{CUSTOM_CHECKS_BLOCK}

Return ONLY this JSON (no prose before or after, no code fencing):
{"verdict":"approved"|"incomplete"|"fake_evidence","missing_items":["requirement: what's missing"],"reason":"one-paragraph explanation"}

Verdicts:
- approved — every requirement has concrete, non-hedged evidence
- incomplete — ≥1 requirement lacks evidence or was skipped
- fake_evidence — ≥1 claim of evidence appears fabricated
---

After the reviewer returns:
- `approved` → output exactly `REVIEWER APPROVED. Stopping.` and stop.
- `incomplete` or `fake_evidence` → list the `missing_items`, continue working on them, do NOT stop.
