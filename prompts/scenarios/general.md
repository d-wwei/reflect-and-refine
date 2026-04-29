---
# ╔═══════════════════════════════════════════════════════════════╗
# ║ Scenario: GENERAL                                              ║
# ║ Fallback for work that doesn't fit a specialised scenario.     ║
# ║ Mirrors default.md at install time; diverge freely.            ║
# ╚═══════════════════════════════════════════════════════════════╝

language: en
strictness: default
model: default
focus: general work completion and evidence quality

dimensions:
  - skill_compliance
  - requirement_split
  - evidence
  - hedging
  - silent_drops
  - fake_evidence

custom_checks: []
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
{"verdict":"approved"|"continue_work"|"fake_evidence","missing_items":["requirement: what's missing"],"reason":"one-paragraph explanation"}

Verdicts:
- approved — every requirement has concrete, non-hedged evidence
- continue_work — ≥1 requirement lacks evidence or was skipped
- fake_evidence — ≥1 claim of evidence appears fabricated
