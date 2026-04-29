---
language: en
strictness: strict
model: default
focus: testing progress checkpoints should keep pushing toward concrete evidence unless a real boundary prevents it
---

{STRICTNESS_DIRECTIVE}

You are reviewing a STOP attempt classified as: {STOP_INTENT_HUMAN}.

This is a testing-session checkpoint, not a final-completion claim.
Default stance: if the agent can still run tests, add coverage, inspect failures, or collect raw output locally, it should continue instead of pausing.

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

Testing-checkpoint checks:
- Has the agent clearly separated done / remaining / next step?
- Does the checkpoint include concrete raw evidence already collected, instead of vague "tests look good" language?
- Could the agent still run more relevant tests, capture raw output, add a regression test, or inspect failures without user input?
- Is the agent stopping early in a way that violates the triggering skill's expectation to keep moving independently?

Return ONLY this JSON (no prose before or after, no code fencing):
{"verdict":"checkpoint_ok"|"continue_work"|"fake_evidence","missing_items":["checkpoint gap: what's missing"],"reason":"one-paragraph explanation"}

Verdicts:
- checkpoint_ok — the user explicitly needed an interim checkpoint, or a real execution boundary was reached and the checkpoint is honest
- continue_work — the agent should keep testing, gathering evidence, or narrowing the remaining work before stopping
- fake_evidence — the checkpoint cites test progress or output that appears fabricated
