---
# ╔═══════════════════════════════════════════════════════════════╗
# ║ Reviewer configuration — structured fields.                    ║
# ║ Edit these to tune the review quickly. See body below for      ║
# ║ deeper customisation (role, verdict schema).                   ║
# ║                                                                ║
# ║ This is the BUNDLED final fallback (resolve layer 5). On a     ║
# ║ fresh install it's also copied to                              ║
# ║ ~/.reflect-and-refine/prompts/default.md (layer 4) so you can  ║
# ║ edit in place without a reinstall.                             ║
# ╚═══════════════════════════════════════════════════════════════╝

language: en
strictness: default
focus: general work completion and evidence quality

# Preferred model for the reviewer subagent. Valid: haiku | sonnet |
# opus | default (inherit). Recommendation: haiku for routine checks,
# sonnet for balance, opus for high-stakes reviews.
model: default

dimensions:
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
