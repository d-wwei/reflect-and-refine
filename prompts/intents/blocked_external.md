---
language: en
strictness: default
model: default
focus: blocker clarity, self-unblocking effort, and exact external dependency needed
---

{STRICTNESS_DIRECTIVE}

You are reviewing a STOP attempt classified as: {STOP_INTENT_HUMAN}.

This is NOT a final-completion review. The agent appears to be pausing because of an external blocker.
Judge whether the blocker is real, specific, and already narrowed down as far as the agent can take it.

Scenario focus:
{SCENARIO_FOCUS}

Respond in: {LANGUAGE}.

USER'S ORIGINAL REQUEST:
{USER_REQUEST}

AGENT'S MOST RECENT RESPONSE:
{AGENT_RESPONSE}

Check these dimensions:
{DIMENSIONS_BLOCK}

{CUSTOM_CHECKS_BLOCK}

Blocker-specific checks:
- Is the blocker concrete (permission / credential / service / human input), not vague?
- Did the agent explain what it already tried before giving up?
- Did it state the smallest external thing needed to unblock progress?
- Is there an obvious local next step the agent could still take instead of stopping now?

Return ONLY this JSON (no prose before or after, no code fencing):
{"verdict":"waiting_for_external_dependency"|"continue_work"|"fake_evidence","missing_items":["blocker gap: what's missing"],"reason":"one-paragraph explanation"}

Verdicts:
- waiting_for_external_dependency — the blocker is real, specific, and stopping is acceptable until the dependency is resolved
- continue_work — the blocker is underspecified or the agent should still do more local work before stopping
- fake_evidence — the blocker or prior attempts appear fabricated or internally inconsistent
