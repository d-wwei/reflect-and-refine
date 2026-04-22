[REFLECT-AND-REFINE v1] Before stopping, you must run a completion review. This is mandatory — do not claim done until the reviewer agrees.

## Step 1 — Spawn an adversarial reviewer sub-agent

Use the Task tool with these exact parameters:

- `subagent_type`: `general-purpose`
- `description`: `Adversarial completion reviewer`
- `prompt`: paste the template below verbatim, substituting ONLY the two `<<<PASTE ... >>>` blocks with the text the reflect-and-refine hook has pre-extracted for you (see below).

The hook has already extracted the relevant transcript excerpts for you:

### User's original request (copy exactly into the `<<<PASTE USER REQUEST>>>` slot):

```
{USER_REQUEST}
```

### Your most recent response (copy exactly into the `<<<PASTE AGENT RESPONSE>>>` slot):

```
{AGENT_RESPONSE}
```

### Reviewer prompt template (copy from here to the end of this code block, do the 2 substitutions, pass as `prompt`):

```
You are an adversarial completion reviewer. Your sole task is to judge whether the main agent actually completed the user's request. Be strict: your job is to find gaps, not to confirm completion. If you cannot find gaps, either (a) you did not look carefully enough, or (b) the work is genuinely complete — say which.

USER'S ORIGINAL REQUEST (verbatim; do not paraphrase):
<<<PASTE USER REQUEST>>>

MAIN AGENT'S LAST RESPONSE (verbatim; do not summarize):
<<<PASTE AGENT RESPONSE>>>

Evaluate on these dimensions:

1. Enumerate every distinct requirement in the user's request (split multi-part asks into discrete items).
2. For each requirement, does the main agent's response contain concrete, verifiable evidence of completion? Evidence = file path + line number, command output, test result, or directly observable state change. "I did X" without artifact is NOT evidence.
3. Flag any hedging ("should work", "probably", "likely", "I believe") as insufficient evidence.
4. Flag any requirement the main agent silently dropped, deferred, or glossed over.
5. Flag evidence that looks fabricated: references to files that likely do not exist, test results without the command that produced them, contradictions within the response.

Output ONLY this JSON (no preamble, no markdown fencing, no commentary before or after):

{
  "verdict": "approved" | "incomplete" | "fake_evidence",
  "missing_items": [
    "<requirement X>: <what specifically is missing or unverified>"
  ],
  "reason": "<one-paragraph explanation of your judgment>"
}

Verdict guide:
- "approved" = every requirement has concrete, non-hedged evidence, no silent drops
- "incomplete" = ≥1 requirement lacks evidence or was skipped; list them all in missing_items
- "fake_evidence" = main agent claimed done, but ≥1 piece of evidence appears fabricated or contradictory
```

## Step 2 — Act on the reviewer's verdict

- **`approved`** → Output exactly one line: `REVIEWER APPROVED. Stopping.` and stop.
- **`incomplete`** or **`fake_evidence`** → Do NOT stop. State the `missing_items` one by one, then continue working on them. Only stop after the next reviewer pass approves.

## Step 3 — Constraints

- Do NOT paraphrase, summarize, or shorten the user's request or your response when constructing the reviewer prompt. Paste verbatim. The reviewer's value comes from seeing unfiltered input.
- If you cannot invoke the Task tool (permissions, etc.), state that clearly and stop. Do NOT skip the review silently.
- This gate is per-turn rate-limited; repeated approvals within the same user turn are allowed to stop after the cap is reached, so do not loop indefinitely.
