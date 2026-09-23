"""Regressions for the problems found during the first outside-user run of v2.3.3.

Every case here cost real minutes in that session. They share a shape: the failure was
knowable up front, but surfaced late and pointed somewhere other than its cause.
"""
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autodebug.config import AutoDebugConfig
from autodebug.firmware_setup import check_ac5_source_encoding
from autodebug.project_editor import iter_named_targets, iter_target_spans

BS = chr(92)

# A .uvprojx with the nesting uVision actually emits: a second <Target> element living
# inside <TargetOption><DebugOption>, after the section an edit needs to reach.
NESTED_PROJECT = """<Project>
  <Targets>
    <Target>
      <TargetName>App</TargetName>
      <TargetOption>
        <DebugOption>
          <Target><UseTarget>1</UseTarget></Target>
        </DebugOption>
        <CreateExecutable>1</CreateExecutable>
      </TargetOption>
    </Target>
    <Target>
      <TargetName>Bootloader</TargetName>
      <TargetOption><CreateExecutable>1</CreateExecutable></TargetOption>
    </Target>
  </Targets>
</Project>"""


class TargetSpans(unittest.TestCase):
    """`<Target>.*?</Target>` stops at the nested closing tag and truncates the block."""

    def test_finds_only_the_real_build_targets(self):
        names = [n for _s, _e, _b, n in iter_named_targets(NESTED_PROJECT)]
        self.assertEqual(names, ["App", "Bootloader"],
                         "the <Target> inside <DebugOption> is not a build target")

    def test_block_is_not_truncated_at_the_nested_tag(self):
        block = next(b for _s, _e, b, n in iter_named_targets(NESTED_PROJECT) if n == "App")
        self.assertIn("<CreateExecutable>", block,
                      "CreateExecutable is the anchor ensure_debug_information inserts "
                      "before; a truncated block drops it and the edit silently no-ops")
        self.assertTrue(block.rstrip().endswith("</Target>"))

    def test_spans_do_not_overlap(self):
        spans = list(iter_target_spans(NESTED_PROJECT))
        for (_s1, e1), (s2, _e2) in zip(spans, spans[1:]):
            self.assertLessEqual(e1, s2)

    def test_target_name_filter(self):
        got = [n for _s, _e, _b, n in iter_named_targets(NESTED_PROJECT, "Bootloader")]
        self.assertEqual(got, ["Bootloader"])

    def test_builder_and_editor_share_one_implementation(self):
        """The duplicate regex in builder.py is what let the two drift apart."""
        import autodebug.builder as builder
        self.assertFalse(hasattr(builder.KeilBuilder, "_TARGET_BLOCK"),
                         "builder must reuse project_editor, not keep its own copy")

    def test_plain_project_still_works(self):
        plain = ("<Targets><Target><TargetName>App</TargetName>"
                 "<TargetOption><CreateExecutable>1</CreateExecutable>"
                 "</TargetOption></Target></Targets>")
        self.assertEqual([n for _s, _e, _b, n in iter_named_targets(plain)], ["App"])


class AC5SourceEncoding(unittest.TestCase):
    """armcc reads source in the host ANSI code page, so UTF-8 literals break it."""

    def _scan(self, files):
        with tempfile.TemporaryDirectory() as d:
            for name, body in files.items():
                with io.open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    f.write(body)
            return check_ac5_source_encoding(d)

    def test_flags_a_non_ascii_string_literal(self):
        out = self._scan({"main.c": 'int main(void){ printf("温度正常"); }\n'})
        self.assertEqual(len(out), 1)
        self.assertIn("main.c", out[0])

    def test_flags_a_literal_containing_an_escape(self):
        body = 'int main(void){ printf("湿度 %d' + BS + 'n", h); }\n'
        self.assertEqual(len(self._scan({"a.c": body})), 1)

    def test_comments_are_not_flagged(self):
        """Comments never reach the compiler's literal parsing, so Chinese is fine
        there -- flagging it would make the check unusable on a documented codebase."""
        files = {
            "block.c": "/* 中文块注释 */\nint f(void){ return 1; }\n",
            "line.c": "// 中文行注释\nint g(void){ return 2; }\n",
            "trailing.c": 'const char *s = "[ALL TESTS PASSED]";  /* 通过令牌 */\n',
        }
        self.assertEqual(self._scan(files), [])

    def test_pure_ascii_project_is_silent(self):
        self.assertEqual(self._scan({"m.c": "int main(void){ return 0; }\n"}), [])

    def test_reports_file_and_line(self):
        body = "int a;\nint b;\n" + 'char *s = "标记";\n'
        out = self._scan({"x.c": body})
        self.assertIn("x.c:3", out[0])

    def test_is_part_of_the_firmware_contract(self):
        from autodebug.firmware_setup import check_firmware_contract
        with tempfile.TemporaryDirectory() as d:
            with io.open(os.path.join(d, "main.c"), "w", encoding="utf-8") as f:
                f.write('int main(void){ printf("[ALL TESTS PASSED]");'
                        ' cm_backtrace_init(); cm_backtrace_putchar(0);'
                        ' printf("温度"); }\n')
            problems = check_firmware_contract(d)
        self.assertTrue(any("ASCII" in p for p in problems),
                        "--check-firmware should surface the encoding trap too")


class Preflight(unittest.TestCase):
    """Build-only runs must not demand hardware; hardware runs should check it early."""

    def test_build_only_does_not_require_a_probe(self):
        cfg = AutoDebugConfig.load()
        problems = cfg.preflight()                      # need_hardware defaults to False
        self.assertFalse(any("调试器" in p for p in problems))
        self.assertFalse(any("pack install" in p for p in problems))

    def test_unknown_target_is_reported_with_the_exact_command(self):
        cfg = AutoDebugConfig.load()
        problems = cfg.preflight(need_hardware=True, target="stm32zz999zz")
        hit = [p for p in problems if "pack install" in p]
        self.assertTrue(hit, "a target pyOCD cannot resolve must be caught before the run")
        self.assertIn("python -m pyocd pack install stm32zz999zz", hit[0],
                      "the message must carry a runnable command, not just a description")

    def test_target_lookup_never_raises(self):
        for value in ("", "nonsense", "stm32f103c8"):
            self.assertIn(AutoDebugConfig._pyocd_knows_target(value), (True, False, None))


class SkillInstallTargets(unittest.TestCase):
    def test_workbuddy_is_a_known_agent_directory(self):
        """Its absence is why a WorkBuddy user's install appeared to succeed while the
        skill never loaded."""
        import install_skill
        names = [d for d, _label, _always in install_skill.AGENT_DIRS]
        self.assertIn(".workbuddy", names)

    def test_optional_agents_are_not_installed_blindly(self):
        import install_skill
        always = {d for d, _l, a in install_skill.AGENT_DIRS if a}
        self.assertEqual(always, {".agents", ".claude"},
                         "only the shared convention and Claude Code install unconditionally")


class SubprocessDecoding(unittest.TestCase):
    def test_build_pipe_declares_an_encoding(self):
        """text=True alone decodes with the local ANSI code page; one non-GBK byte from
        UV4 then raises UnicodeDecodeError and takes the build down as a traceback."""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "autodebug", "builder.py")
        with io.open(path, encoding="utf-8") as fh:
            src = fh.read()
        idx = src.index("proc = subprocess.run(cmd")
        call = src[idx:idx + 400]
        self.assertIn('encoding="utf-8"', call)
        self.assertIn('errors="replace"', call)


if __name__ == "__main__":
    unittest.main()
