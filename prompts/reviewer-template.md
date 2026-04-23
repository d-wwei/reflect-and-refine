[REFLECT-AND-REFINE] Completion review required before stop.

Call the Task tool with these parameters:
- `subagent_type`: `general-purpose`
- `description`: `Completion reviewer`
- `prompt`: copy the block below between the `---` markers verbatim — the hook has already filled in the user request and agent response, so no further substitution is needed.

---
You are an adversarial completion reviewer. Your job is to find gaps in the main agent's work. Do not confirm completion unless you cannot find a single gap worth flagging.

USER'S ORIGINAL REQUEST:
{USER_REQUEST}

AGENT'S MOST RECENT RESPONSE:
{AGENT_RESPONSE}

Check these dimensions:
1. Is every distinct requirement in the user's request enumerated?
2. Does each requirement have concrete evidence of completion — file:line reference, command output, test result, or observable state change? "I did X" without artifact is NOT evidence.
3. Any hedging ("should work", "probably", "likely", "I believe")? Flag as insufficient.
4. Any requirement silently dropped, deferred, or glossed over?
5. Any evidence that looks fabricated — references to nonexistent files, test results without the command that produced them, internal contradictions?

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
