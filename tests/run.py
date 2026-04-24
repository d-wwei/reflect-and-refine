#!/usr/bin/env python3
"""
reflect-and-refine test suite — stdlib only, no pytest dependency.

Run:
    python3 tests/run.py            # full suite, verbose
    python3 tests/run.py -q         # quiet, exit nonzero on any failure

CI-style usage:
    python3 tests/run.py || exit 1

Coverage:
    - frontmatter parser (scalar / list / list-of-dict / empty / no frontmatter)
    - is_real_user_record filter (hook injection / tool result / real)
    - gate_state semantics (activate / shutdown / idempotent / unknown / typo / cross-session)
    - dimension snippet assembly (all 7 dims × 3 strictness)
    - prompt resolution 4-layer fallback (bundled only)
    - build_block_reason end-to-end with model_preference variants
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "stop-gate.py"

spec = importlib.util.spec_from_file_location("sg", HOOK)
sg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sg)


def _mk_user_rec(cmd: str, args: str = "", ts: str = "2026-04-23T01:00:00Z", is_meta=None, tool_result=None):
    rec = {
        "type": "user",
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": f"<command-name>/{cmd}</command-name>\n<command-args>{args}</command-args>",
        },
    }
    if is_meta is not None:
        rec["isMeta"] = is_meta
    if tool_result is not None:
        rec["toolUseResult"] = tool_result
    return rec


def _mk_plain_user(text: str, ts="2026-04-23T01:00:00Z"):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}


REGISTERED = {"reflect-and-refine", "better-work", "better-code", "better-test"}


class FrontmatterParser(unittest.TestCase):
    def test_scalar_fields(self):
        fm, body = sg.parse_frontmatter("---\nlanguage: zh\nstrictness: strict\n---\nhello")
        self.assertEqual(fm["language"], "zh")
        self.assertEqual(fm["strictness"], "strict")
        self.assertEqual(body, "hello")

    def test_string_list(self):
        fm, _ = sg.parse_frontmatter("---\ndimensions:\n  - evidence\n  - hedging\n---\n")
        self.assertEqual(fm["dimensions"], ["evidence", "hedging"])

    def test_list_of_dicts(self):
        text = "---\ncustom_checks:\n  - name: sec\n    description: SQL injection\n  - name: cov\n    description: test coverage\n---\n"
        fm, _ = sg.parse_frontmatter(text)
        self.assertEqual(len(fm["custom_checks"]), 2)
        self.assertEqual(fm["custom_checks"][0], {"name": "sec", "description": "SQL injection"})

    def test_empty_list(self):
        fm, _ = sg.parse_frontmatter("---\ncustom_checks: []\n---\n")
        self.assertEqual(fm["custom_checks"], [])

    def test_comments_skipped(self):
        fm, _ = sg.parse_frontmatter("---\n# this is a comment\nlanguage: en\n---\n")
        self.assertEqual(fm["language"], "en")
        self.assertNotIn("# this is a comment", fm)

    def test_no_frontmatter(self):
        fm, body = sg.parse_frontmatter("just a plain body\nno frontmatter here")
        self.assertEqual(fm, {})
        self.assertEqual(body, "just a plain body\nno frontmatter here")

    def test_quoted_values_stripped(self):
        fm, _ = sg.parse_frontmatter("---\nlanguage: \"en\"\nstrictness: 'strict'\n---\n")
        self.assertEqual(fm["language"], "en")
        self.assertEqual(fm["strictness"], "strict")


class RealUserFilter(unittest.TestCase):
    def test_plain_user_is_real(self):
        self.assertTrue(sg.is_real_user_record(_mk_plain_user("hello")))

    def test_hook_injection_filtered(self):
        rec = _mk_plain_user("Stop hook feedback: blah")
        rec["isMeta"] = True
        self.assertFalse(sg.is_real_user_record(rec))

    def test_tool_result_filtered(self):
        rec = _mk_plain_user("some tool output")
        rec["toolUseResult"] = {"x": 1}
        self.assertFalse(sg.is_real_user_record(rec))

    def test_assistant_not_user(self):
        rec = {"type": "assistant", "message": {"content": "hi"}}
        self.assertFalse(sg.is_real_user_record(rec))


class GateStateSemantics(unittest.TestCase):
    def test_parent_skill_opens(self):
        self.assertEqual(
            sg.gate_state([_mk_user_rec("better-code", "init")], REGISTERED),
            ("OPEN", "better-code"),
        )

    def test_rar_shutdown_closes(self):
        self.assertEqual(
            sg.gate_state([_mk_user_rec("reflect-and-refine", "shutdown")], REGISTERED),
            ("CLOSED", ""),
        )

    def test_rar_activate_opens(self):
        self.assertEqual(
            sg.gate_state([_mk_user_rec("reflect-and-refine", "activate")], REGISTERED),
            ("OPEN", "reflect-and-refine"),
        )

    def test_rar_empty_args_opens(self):
        self.assertEqual(
            sg.gate_state([_mk_user_rec("reflect-and-refine", "")], REGISTERED),
            ("OPEN", "reflect-and-refine"),
        )

    def test_rar_status_transparent(self):
        self.assertEqual(
            sg.gate_state([_mk_user_rec("reflect-and-refine", "status")], REGISTERED),
            ("CLOSED", ""),
        )

    def test_rar_audit_transparent(self):
        self.assertEqual(
            sg.gate_state([_mk_user_rec("reflect-and-refine", "audit")], REGISTERED),
            ("CLOSED", ""),
        )

    def test_rar_customize_transparent(self):
        # v0.2.0 fix: customize is idempotent, doesn't activate
        self.assertEqual(
            sg.gate_state([_mk_user_rec("reflect-and-refine", "customize better-code")], REGISTERED),
            ("CLOSED", ""),
        )

    def test_unknown_subcommand_transparent(self):
        # v0.2.0 fix: typos fall through as transparent, not fail-safe OPEN
        self.assertEqual(
            sg.gate_state([_mk_user_rec("reflect-and-refine", "actvate")], REGISTERED),
            ("CLOSED", ""),
        )

    def test_rate_limit_transparent(self):
        self.assertEqual(
            sg.gate_state([_mk_user_rec("reflect-and-refine", "rate-limit 5")], REGISTERED),
            ("CLOSED", ""),
        )

    def test_shutdown_then_query_stays_closed(self):
        seq = [
            _mk_user_rec("better-code", "init"),
            _mk_user_rec("reflect-and-refine", "shutdown"),
            _mk_user_rec("reflect-and-refine", "customize better-code"),
            _mk_user_rec("reflect-and-refine", "status"),
        ]
        self.assertEqual(sg.gate_state(seq, REGISTERED), ("CLOSED", ""))

    def test_active_then_query_preserves_trigger(self):
        seq = [
            _mk_user_rec("better-code", "init"),
            _mk_user_rec("reflect-and-refine", "audit"),
            _mk_user_rec("reflect-and-refine", "status"),
        ]
        self.assertEqual(sg.gate_state(seq, REGISTERED), ("OPEN", "better-code"))

    def test_reactivate_after_shutdown(self):
        seq = [
            _mk_user_rec("better-code", "init"),
            _mk_user_rec("reflect-and-refine", "shutdown"),
            _mk_user_rec("better-test", "strategy"),
        ]
        self.assertEqual(sg.gate_state(seq, REGISTERED), ("OPEN", "better-test"))

    def test_no_markers_closed(self):
        seq = [_mk_plain_user("hello there")]
        self.assertEqual(sg.gate_state(seq, REGISTERED), ("CLOSED", ""))

    def test_unregistered_skill_ignored(self):
        seq = [_mk_user_rec("some-other-skill", "xxx")]
        self.assertEqual(sg.gate_state(seq, REGISTERED), ("CLOSED", ""))

    def test_hook_injection_not_a_marker(self):
        # Hook injection records contain synthetic text that may include
        # <command-name>; filter must skip them and find only REAL markers.
        injected = _mk_plain_user(
            "Stop hook feedback: <command-name>/reflect-and-refine</command-name>\n<command-args>activate</command-args>"
        )
        injected["isMeta"] = True
        seq = [_mk_user_rec("reflect-and-refine", "shutdown"), injected]
        # The injected record must be ignored; real shutdown wins.
        self.assertEqual(sg.gate_state(seq, REGISTERED), ("CLOSED", ""))


class PinDirective(unittest.TestCase):
    def test_no_pin_returns_empty(self):
        recs = [_mk_user_rec("better-code", "init")]
        self.assertEqual(sg.find_pin_directive(recs), ("", ""))

    def test_pin_defaults_to_scenario(self):
        recs = [_mk_user_rec("reflect-and-refine", "pin coding")]
        self.assertEqual(sg.find_pin_directive(recs), ("scenario", "coding"))

    def test_pin_scenario_explicit(self):
        recs = [_mk_user_rec("reflect-and-refine", "pin scenario testing")]
        self.assertEqual(sg.find_pin_directive(recs), ("scenario", "testing"))

    def test_pin_skill_explicit(self):
        recs = [_mk_user_rec("reflect-and-refine", "pin skill better-test")]
        self.assertEqual(sg.find_pin_directive(recs), ("skill", "better-test"))

    def test_unpin_clears(self):
        recs = [
            _mk_user_rec("reflect-and-refine", "pin coding"),
            _mk_user_rec("reflect-and-refine", "unpin"),
        ]
        self.assertEqual(sg.find_pin_directive(recs), ("", ""))

    def test_later_pin_replaces_earlier(self):
        recs = [
            _mk_user_rec("reflect-and-refine", "pin coding"),
            _mk_user_rec("reflect-and-refine", "pin testing"),
        ]
        self.assertEqual(sg.find_pin_directive(recs), ("scenario", "testing"))

    def test_scenario_pin_then_skill_pin(self):
        recs = [
            _mk_user_rec("reflect-and-refine", "pin coding"),
            _mk_user_rec("reflect-and-refine", "pin skill better-code"),
        ]
        self.assertEqual(sg.find_pin_directive(recs), ("skill", "better-code"))

    def test_pin_without_arg_ignored(self):
        recs = [_mk_user_rec("reflect-and-refine", "pin")]
        self.assertEqual(sg.find_pin_directive(recs), ("", ""))

    def test_hook_injection_ignored_for_pin(self):
        fake = _mk_plain_user(
            "Stop hook feedback: <command-name>/reflect-and-refine</command-name>\n<command-args>pin malicious</command-args>"
        )
        fake["isMeta"] = True
        self.assertEqual(sg.find_pin_directive([fake]), ("", ""))


class ScenarioLookup(unittest.TestCase):
    """scenario_for_skill reads skill_scenario_map from config."""

    def test_mapped_skill_returns_scenario(self):
        cfg = {"reviewer": {"skill_scenario_map": {"better-code": "coding"}}}
        self.assertEqual(sg.scenario_for_skill("better-code", cfg), "coding")

    def test_unmapped_skill_returns_empty(self):
        cfg = {"reviewer": {"skill_scenario_map": {"better-code": "coding"}}}
        self.assertEqual(sg.scenario_for_skill("something-else", cfg), "")

    def test_no_map_in_config(self):
        self.assertEqual(sg.scenario_for_skill("better-code", {}), "")

    def test_nondict_map_returns_empty(self):
        cfg = {"reviewer": {"skill_scenario_map": "garbage"}}
        self.assertEqual(sg.scenario_for_skill("better-code", cfg), "")


class DimensionAssembly(unittest.TestCase):
    def test_all_dimensions_have_three_strictness_levels(self):
        for name, snippets in sg.DIMENSION_SNIPPETS.items():
            self.assertEqual(
                set(snippets.keys()),
                {"lenient", "default", "strict"},
                f"{name} is missing a strictness variant",
            )

    def test_assembly_returns_numbered_list(self):
        out = sg.assemble_dimensions_block(["evidence", "hedging"], "default")
        self.assertIn("1.", out)
        self.assertIn("2.", out)

    def test_unknown_dimension_rendered_as_placeholder(self):
        out = sg.assemble_dimensions_block(["evidence", "nonexistent_dim"], "default")
        self.assertIn("nonexistent_dim", out)
        self.assertIn("unknown dimension", out)

    def test_empty_dimensions_handled(self):
        out = sg.assemble_dimensions_block([], "default")
        self.assertIn("no dimensions", out.lower())

    def test_strict_differs_from_lenient(self):
        strict_out = sg.assemble_dimensions_block(["evidence"], "strict")
        lenient_out = sg.assemble_dimensions_block(["evidence"], "lenient")
        self.assertNotEqual(strict_out, lenient_out)


class CustomChecksAssembly(unittest.TestCase):
    def test_dict_checks(self):
        out = sg.assemble_custom_checks_block([{"name": "sec", "description": "XSS"}])
        self.assertIn("sec", out)
        self.assertIn("XSS", out)

    def test_string_checks(self):
        out = sg.assemble_custom_checks_block(["no-breaking-changes"])
        self.assertIn("no-breaking-changes", out)

    def test_empty_returns_empty(self):
        self.assertEqual(sg.assemble_custom_checks_block([]), "")


class PromptResolution(unittest.TestCase):
    """
    resolve_prompt_path consults module-level paths derived from ~/. Here we
    temporarily repoint those paths to an empty tempdir so we can exercise
    each fallback layer deterministically, regardless of what the running
    user has in their real ~/.reflect-and-refine/.
    """

    def setUp(self):
        self._saved = {
            "CONFIG_DIR": sg.CONFIG_DIR,
            "USER_PROMPTS_DIR": sg.USER_PROMPTS_DIR,
            "USER_OVERRIDES_DIR": sg.USER_OVERRIDES_DIR,
            "USER_SCENARIOS_DIR": sg.USER_SCENARIOS_DIR,
            "USER_DEFAULT_PROMPT": sg.USER_DEFAULT_PROMPT,
        }
        self.tmp = Path(tempfile.mkdtemp())
        sg.CONFIG_DIR = self.tmp
        sg.USER_PROMPTS_DIR = self.tmp / "prompts"
        sg.USER_OVERRIDES_DIR = self.tmp / "prompts" / "overrides"
        sg.USER_SCENARIOS_DIR = self.tmp / "prompts" / "scenarios"
        sg.USER_DEFAULT_PROMPT = self.tmp / "prompts" / "default.md"
        sg.USER_OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
        sg.USER_SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k, v in self._saved.items():
            setattr(sg, k, v)

    def test_bundled_fallback_when_nothing_else(self):
        # Empty tempdir, empty config → falls through to bundled
        p = sg.resolve_prompt_path("better-code", {})
        self.assertEqual(p, sg.BUNDLED_PROMPT)

    def test_user_default_layer3(self):
        sg.USER_DEFAULT_PROMPT.write_text("user default body")
        p = sg.resolve_prompt_path("better-code", {})
        self.assertEqual(p, sg.USER_DEFAULT_PROMPT)

    def test_override_layer2_wins_over_default(self):
        sg.USER_DEFAULT_PROMPT.write_text("user default body")
        override = sg.USER_OVERRIDES_DIR / "better-code.md"
        override.write_text("override body")
        p = sg.resolve_prompt_path("better-code", {})
        self.assertEqual(p, override)

    def test_config_mapping_layer1_wins(self):
        sg.USER_DEFAULT_PROMPT.write_text("default")
        override = sg.USER_OVERRIDES_DIR / "better-code.md"
        override.write_text("override")
        custom = self.tmp / "custom.md"
        custom.write_text("custom")
        config = {"reviewer": {"per_skill": {"better-code": str(custom)}}}
        p = sg.resolve_prompt_path("better-code", config)
        self.assertEqual(p, custom)

    def test_config_mapping_with_relative_path(self):
        custom = self.tmp / "relative.md"
        custom.write_text("x")
        config = {"reviewer": {"per_skill": {"better-code": "relative.md"}}}
        p = sg.resolve_prompt_path("better-code", config)
        self.assertEqual(p, custom)

    def test_empty_trigger_falls_through_to_bundled(self):
        p = sg.resolve_prompt_path("", {})
        self.assertEqual(p, sg.BUNDLED_PROMPT)

    def test_nonexistent_config_path_falls_through(self):
        # If config maps to a file that doesn't exist, skip to next layer
        config = {"reviewer": {"per_skill": {"better-code": str(self.tmp / "nope.md")}}}
        sg.USER_DEFAULT_PROMPT.write_text("default exists")
        p = sg.resolve_prompt_path("better-code", config)
        self.assertEqual(p, sg.USER_DEFAULT_PROMPT)

    def test_scenario_layer_user_file_wins(self):
        user_coding = sg.USER_SCENARIOS_DIR / "coding.md"
        user_coding.write_text("user coding scenario")
        config = {"reviewer": {"skill_scenario_map": {"better-code": "coding"}}}
        p = sg.resolve_prompt_path("better-code", config)
        self.assertEqual(p, user_coding)

    def test_scenario_layer_falls_back_to_bundled(self):
        # No user scenario file, but skill maps to coding → bundled coding.md should exist
        config = {"reviewer": {"skill_scenario_map": {"better-code": "coding"}}}
        p = sg.resolve_prompt_path("better-code", config)
        self.assertEqual(p, sg.BUNDLED_SCENARIOS_DIR / "coding.md")

    def test_unmapped_skill_skips_scenario_layer(self):
        # No map → no scenario → fall through to default / bundled
        sg.USER_DEFAULT_PROMPT.write_text("default")
        p = sg.resolve_prompt_path("unmapped-skill", {})
        self.assertEqual(p, sg.USER_DEFAULT_PROMPT)

    def test_scenario_pointing_at_nonexistent_file_falls_through(self):
        config = {"reviewer": {"skill_scenario_map": {"better-code": "nonexistent-scenario"}}}
        sg.USER_DEFAULT_PROMPT.write_text("default")
        p = sg.resolve_prompt_path("better-code", config)
        self.assertEqual(p, sg.USER_DEFAULT_PROMPT)

    def test_override_file_wins_over_scenario(self):
        override = sg.USER_OVERRIDES_DIR / "better-code.md"
        override.write_text("skill-specific override")
        user_coding = sg.USER_SCENARIOS_DIR / "coding.md"
        user_coding.write_text("user coding")
        config = {"reviewer": {"skill_scenario_map": {"better-code": "coding"}}}
        p = sg.resolve_prompt_path("better-code", config)
        self.assertEqual(p, override)  # override beats scenario


class BuildReviewerPrompt(unittest.TestCase):
    """build_reviewer_prompt reads a prompt file, substitutes placeholders, returns reviewer-only content."""

    def _write_template(self, fm_yaml: str, body: str = None) -> Path:
        if body is None:
            body = """Test body.
language: {LANGUAGE}
strictness: {STRICTNESS_DIRECTIVE}
model_param: {MODEL_PREFERENCE_PARAM}END
dimensions:
{DIMENSIONS_BLOCK}
custom:
{CUSTOM_CHECKS_BLOCK}
user: {USER_REQUEST}
agent: {AGENT_RESPONSE}"""
        tmp = Path(tempfile.mktemp(suffix=".md"))
        tmp.write_text(f"---\n{fm_yaml}\n---\n{body}")
        return tmp

    def test_model_haiku_in_returned_param(self):
        p = self._write_template("model: haiku\nlanguage: en\nstrictness: default\ndimensions: []\ncustom_checks: []")
        try:
            _prompt, model_param, _fm = sg.build_reviewer_prompt("u", "a", p)
            self.assertIn("- `model`: `haiku`", model_param)
        finally:
            p.unlink()

    def test_model_default_empty_param(self):
        p = self._write_template("model: default\nlanguage: en\nstrictness: default\ndimensions: []\ncustom_checks: []")
        try:
            _prompt, model_param, _fm = sg.build_reviewer_prompt("u", "a", p)
            self.assertEqual(model_param, "")
        finally:
            p.unlink()

    def test_all_placeholders_substituted(self):
        p = self._write_template(
            "language: zh\nstrictness: strict\nmodel: opus\ndimensions:\n  - evidence\ncustom_checks:\n  - name: sec\n    description: sql"
        )
        try:
            prompt, _mp, _fm = sg.build_reviewer_prompt("my-request", "my-response", p)
            for ph in ("{LANGUAGE}", "{STRICTNESS_DIRECTIVE}", "{MODEL_PREFERENCE_PARAM}",
                      "{DIMENSIONS_BLOCK}", "{CUSTOM_CHECKS_BLOCK}", "{USER_REQUEST}", "{AGENT_RESPONSE}"):
                self.assertNotIn(ph, prompt, f"{ph} was not substituted")
            self.assertIn("my-request", prompt)
            self.assertIn("my-response", prompt)
            self.assertIn("zh", prompt)
        finally:
            p.unlink()

    def test_extract_reviewer_body_with_inner_markers(self):
        # Template with outer wrapper (legacy v0.2.x structure)
        body = "OUTER\n\n---\nREVIEWER CONTENT\n---\n\nAFTER"
        self.assertEqual(sg.extract_reviewer_prompt_body(body), "REVIEWER CONTENT")

    def test_extract_reviewer_body_without_markers(self):
        # Template that's already inner-only (v0.3.1+ structure)
        body = "Just the reviewer prompt.\n{USER_REQUEST}"
        self.assertEqual(sg.extract_reviewer_prompt_body(body), "Just the reviewer prompt.\n{USER_REQUEST}")


class ShortReasonAndSessionFile(unittest.TestCase):
    """build_block_reason writes reviewer to session file and returns short reason."""

    def setUp(self):
        self._saved_sessions = sg.SESSIONS_DIR
        self.tmp = Path(tempfile.mkdtemp())
        sg.SESSIONS_DIR = self.tmp

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        sg.SESSIONS_DIR = self._saved_sessions

    def test_short_reason_references_file(self):
        # Use the bundled template as input prompt
        reason, session_file = sg.build_block_reason("req", "resp", sg.BUNDLED_PROMPT, "test-session-abc")
        self.assertIn("Completion review required", reason)
        self.assertIn("test-session-abc", str(session_file))
        self.assertTrue(session_file.exists())
        # Short reason should be << 1000 chars (we want ~500)
        self.assertLess(len(reason), 1000, f"short reason is {len(reason)} chars, too long")

    def test_session_file_contains_substituted_content(self):
        _r, session_file = sg.build_block_reason("my-req", "my-resp", sg.BUNDLED_PROMPT, "test-sess")
        content = session_file.read_text()
        self.assertIn("my-req", content)
        self.assertIn("my-resp", content)
        # Placeholders all substituted
        for ph in ("{USER_REQUEST}", "{AGENT_RESPONSE}", "{LANGUAGE}", "{STRICTNESS_DIRECTIVE}",
                  "{DIMENSIONS_BLOCK}", "{CUSTOM_CHECKS_BLOCK}"):
            self.assertNotIn(ph, content)

    def test_session_id_sanitised(self):
        # Unusual chars in session_id shouldn't break filesystem
        _r, session_file = sg.build_block_reason("r", "a", sg.BUNDLED_PROMPT, "../../../etc/passwd")
        # The filename should be sanitised — no path traversal
        self.assertTrue(str(session_file).startswith(str(self.tmp)))

    def test_sweep_removes_old_files(self):
        # Create a file with old mtime
        old = sg.SESSIONS_DIR / "old.md"
        old.write_text("stale")
        import os as _os
        ancient = datetime.now().timestamp() - (30 * 24 * 3600)
        _os.utime(old, (ancient, ancient))
        # Create a recent file
        recent = sg.SESSIONS_DIR / "recent.md"
        recent.write_text("fresh")
        sg.sweep_old_session_files()
        self.assertFalse(old.exists(), "old file should have been swept")
        self.assertTrue(recent.exists(), "recent file should remain")


def main():
    verbosity = 1 if "-q" in sys.argv else 2
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        FrontmatterParser,
        RealUserFilter,
        GateStateSemantics,
        PinDirective,
        ScenarioLookup,
        DimensionAssembly,
        CustomChecksAssembly,
        PromptResolution,
        BuildReviewerPrompt,
        ShortReasonAndSessionFile,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
