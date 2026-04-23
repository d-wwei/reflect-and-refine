---
# ╔═══════════════════════════════════════════════════════════════╗
# ║ Reviewer configuration — structured fields.                    ║
# ║ Edit these to tune the review quickly. See body below for      ║
# ║ deeper customisation (role, verdict schema, main-agent steps). ║
# ╚═══════════════════════════════════════════════════════════════╝

# Output language the reviewer should use. The value is injected verbatim
# into the reviewer prompt as a directive. Free text; common values: "zh"
# (will render as Chinese), "en" (English), or any phrase like "Chinese,
# keep technical terms in English".
language: en

# How strict the reviewer should be. Affects the opening directive and how
# each dimension is phrased. Valid: lenient | default | strict
strictness: default

# Preferred model for the reviewer subagent. When set, the hook adds a
# `model:` param to the Task call so the main agent invokes the reviewer
# on that specific model tier.
# Valid: haiku | sonnet | opus | default (inherit parent session's model)
# Recommendation:
#   haiku  — fast + cheap, good for routine completion checks
#   sonnet — balanced (default for most projects)
#   opus   — deepest analysis, reserve for high-stakes / architectural reviews
model: default

# Which built-in review dimensions to include. The hook looks up each name
# in its internal snippet dict (per strictness) and splices the rendered
# block into {DIMENSIONS_BLOCK} below. Available dimension names:
#   evidence           — does every requirement have concrete evidence?
#   hedging            — flag "should", "probably", etc.
#   silent_drops       — any silently dropped / deferred requirement?
#   fake_evidence      — references to files that don't exist, unrun tests
#   requirement_split  — enumerate every distinct requirement
#   consistency        — is the response internally consistent?
#   completeness       — are implicit sub-questions answered?
dimensions:
  - requirement_split
  - evidence
  - hedging
  - silent_drops
  - fake_evidence

# Extra project-specific checks. Each entry becomes a bullet under the
# "Project-specific checks" section in the reviewer prompt. Leave empty
# when not needed.
custom_checks: []
# custom_checks:
#   - name: security_review
#     description: Check for common security issues (SQL injection, XSS, permission leaks).
#   - name: test_coverage
#     description: Verify tests exist for files that were modified.
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
