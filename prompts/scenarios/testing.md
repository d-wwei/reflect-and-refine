---
# ╔═══════════════════════════════════════════════════════════════╗
# ║ Scenario: TESTING                                              ║
# ║ For skills that author tests, run test suites, triage failures,║
# ║ or verify coverage. Strict by default because testing-about-   ║
# ║ testing is where fake evidence is most tempting and most       ║
# ║ damaging (a silent test gap masks real bugs downstream).       ║
# ╚═══════════════════════════════════════════════════════════════╝

language: en
# Testing work warrants strict: a lenient review here means bugs get
# through the safety net that's supposed to catch them.
strictness: strict
model: default

# completeness is critical in testing — implicit edge cases (empty,
# large, unicode, concurrency, malformed) are the point of the job.
dimensions:
  - requirement_split
  - evidence
  - completeness
  - fake_evidence
  - silent_drops
  - consistency

custom_checks:
  - name: test_output_verbatim
    description: The response must quote the actual test runner output — pass/fail/skip counts, exact assertion failures if any, execution time. "Tests pass" without the raw output block is fake_evidence.
  - name: edge_cases_enumerated
    description: The response must explicitly enumerate the edge cases considered (empty input, maximum size, unicode/emoji, null/undefined, concurrency, network failure, permission denied — whichever apply). If the author consciously did not test a case, they must say so.
  - name: failing_tests_not_silenced
    description: No `--skip`, no `@pytest.mark.skip`, no `xit(...)`, no `/* istanbul ignore */`, no commented-out assertions. If the agent needed to skip a test, they must justify it and flag it as a known gap.
  - name: regressions_checked
    description: If the work addresses a bug or behavioural change, a regression test (or equivalent repro) must be added — not just "the fix works on my machine".
  - name: coverage_direction
    description: If coverage numbers are quoted, the response must say which direction it moved (not just "coverage is good"). A drop without explanation is a silent drop.
---

[REFLECT-AND-REFINE] Completion review required before stop.

Call the Task tool with these parameters:
- `subagent_type`: `general-purpose`
{MODEL_PREFERENCE_PARAM}- `description`: `Completion reviewer (testing)`
- `prompt`: copy the block below between the `---` markers verbatim — the hook has already substituted all placeholders, so no further editing is needed.

---
{STRICTNESS_DIRECTIVE}

You are reviewing TESTING work. Tests are the safety net; fabricated test evidence is the safety net failing silently. Be especially strict about:
1. Claimed test output without the raw runner output (pass/fail/skip counts, assertion messages).
2. Silenced or skipped tests that are presented as "green".
3. Edge cases that were assumed without being executed.
4. Regression tests missing for bug-fix work.

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
- approved — every requirement has concrete evidence, raw test output included, edge cases addressed or explicitly skipped with reason
- incomplete — ≥1 requirement lacks evidence or edge case was silently dropped
- fake_evidence — ≥1 claim of test output, coverage, or assertion appears fabricated or is missing the raw output
---

After the reviewer returns:
- `approved` → output exactly `REVIEWER APPROVED. Stopping.` and stop.
- `incomplete` or `fake_evidence` → list the `missing_items`, continue working on them, do NOT stop.
