---
# ╔═══════════════════════════════════════════════════════════════╗
# ║ Scenario: DEBUGGING                                            ║
# ║ For skills that diagnose bugs, triage incidents, explain       ║
# ║ unexpected behaviour, or validate fixes. The most common       ║
# ║ debugging failure is "fixed the symptom, missed the root       ║
# ║ cause" — this scenario's checks are biased toward catching it. ║
# ╚═══════════════════════════════════════════════════════════════╝

language: en
strictness: default
model: default
focus: root-cause analysis, reproduction quality, and fix verification

# For debugging, consistency matters most (does the proposed fix
# actually match the stated cause?) and silent_drops catches the
# "other call sites with the same pattern" miss.
dimensions:
  - requirement_split
  - evidence
  - consistency
  - fake_evidence
  - silent_drops
  - hedging

custom_checks:
  - name: root_cause_named
    description: The response must name the root cause at the right abstraction layer — not just the observable symptom. "Variable was None" is a symptom; "the config loader silently returns None on missing keys instead of raising" is a root cause. Symptom-only answers are incomplete.
  - name: reproduction_before_fix
    description: Did the agent reproduce the bug (or confirm the failing test) BEFORE attempting a fix? If not, there's no evidence the fix addresses the actual problem.
  - name: fix_verified_against_reproduction
    description: After applying the fix, did the agent re-run the reproduction / failing test / triggering command and confirm it now passes/behaves correctly? "Should fix it" is not verification.
  - name: regression_test_added
    description: Is there a new test (or repro script) that will fail without the fix, so this specific bug can't silently recur? If no regression test is added, the agent must explicitly say why not.
  - name: sibling_instances_audited
    description: If the root cause is a pattern (e.g., "same copy-pasted block in 3 places"), were the other instances also checked? Patching only the reported one is a silent drop.
  - name: fix_matches_root_cause
    description: Compare the diff to the stated root cause. If the fix addresses something different (e.g., root cause = loader silently returns None, but fix = null-check at the call site), that's a consistency failure — it may work but doesn't fix what was diagnosed.
---

{STRICTNESS_DIRECTIVE}

You are reviewing DEBUGGING work. The characteristic failure mode is "symptom-level patch, root cause unaddressed" — code that makes the specific error go away while leaving the underlying problem intact to surface again later. Watch for:
1. A stated root cause that's really just the symptom (observable error, not the mechanism that caused it).
2. A fix applied without first reproducing the bug — no evidence the problem is actually understood.
3. A fix applied without re-running the reproduction afterward — no evidence the problem is actually gone.
4. "Same pattern exists in 5 other places" being ignored — only the reported instance patched.
5. No regression test to prevent silent recurrence.

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
- approved — root cause named, reproduction verified, fix verified against reproduction, regression test added, sibling instances considered
- continue_work — ≥1 of the above missing (e.g., fix works but no regression test)
- fake_evidence — claimed reproduction or verification steps appear fabricated / inconsistent with the diff
