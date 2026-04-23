---
# ╔═══════════════════════════════════════════════════════════════╗
# ║ Scenario: CODING                                               ║
# ║ For skills that modify source code, configuration, or infra.   ║
# ║ Optimised to catch the three most common coding shortcuts:     ║
# ║   1. fabricated test output ("tests pass" with no run command) ║
# ║   2. placeholder code left behind (TODO, empty bodies)         ║
# ║   3. implementation-without-verification ("should compile")    ║
# ╚═══════════════════════════════════════════════════════════════╝

language: en
strictness: default
model: default

# Dimensions chosen for code-change review. requirement_split and
# silent_drops catch broken multi-file asks; evidence + fake_evidence
# are the primary lines of defence against "tests pass" without logs;
# consistency covers contradiction between claims and code; hedging
# flags "should work" narratives.
dimensions:
  - requirement_split
  - evidence
  - fake_evidence
  - hedging
  - silent_drops
  - consistency

# Coding-specific probes that routinely catch real failures.
custom_checks:
  - name: tests_actually_ran
    description: If code changed, the response must include the verbatim command used to run tests AND the output (pass count, skipped count, any failures). "All tests pass" with no command/output is insufficient — flag as fake_evidence.
  - name: builds_successful
    description: If the change requires compilation or a build step, the response must show the build command and its output. "Should build fine" is not acceptable.
  - name: no_placeholder_code
    description: Scan the response for TODO, FIXME, "left for the reader", empty function bodies, or dummy return values. Any such artifact in a completed-work claim is a silent drop.
  - name: imports_and_references_valid
    description: Cross-check file paths, imported symbols, and function names mentioned in the response. Any path or name that's implausible given the codebase context counts as fake_evidence.
---

[REFLECT-AND-REFINE] Completion review required before stop.

Call the Task tool with these parameters:
- `subagent_type`: `general-purpose`
{MODEL_PREFERENCE_PARAM}- `description`: `Completion reviewer (coding)`
- `prompt`: copy the block below between the `---` markers verbatim — the hook has already substituted all placeholders, so no further editing is needed.

---
{STRICTNESS_DIRECTIVE}

You are reviewing CODE-CHANGE work. Your highest-value targets are the three shortcuts agents take under time pressure:
1. Fabricated test output — "tests pass" without the command or log.
2. Placeholder code — TODOs, empty bodies, "handled elsewhere" that isn't.
3. Unverified narrative — "should compile / should work" instead of a build or run.

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
- approved — every requirement has concrete, non-hedged evidence; tests/builds demonstrably ran
- incomplete — ≥1 requirement lacks evidence or was skipped
- fake_evidence — ≥1 claim of test output, build success, or file reference appears fabricated
---

After the reviewer returns:
- `approved` → output exactly `REVIEWER APPROVED. Stopping.` and stop.
- `incomplete` or `fake_evidence` → list the `missing_items`, continue working on them, do NOT stop.
