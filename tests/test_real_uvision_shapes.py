"""Regressions found by building a real project end to end, not by reading code.

Each of these passed the existing suite because the fixtures were simplified: a
.uvprojx with one <IncludePath>, a build log in armcc's native spelling, and no test
that ever ran the CLI entry point. The shapes below are the ones uVision actually
writes, taken from the STM32F103C8 template build.
"""
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KIT)

from autodebug.builder import KeilBuilder
from autodebug.config import BuildConfig
from autodebug.project_editor import KeilProjectEditor

# Trimmed, but with every <IncludePath> / <Define> a uVision target really carries, in
# the order it writes them: Folder Setup first, then the C compiler, then the assembler.
UVISION_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<Project>
  <Targets>
    <Target>
      <TargetName>Template</TargetName>
      <TargetOption>
        <TargetCommonOption>
          <IncludePath></IncludePath>
          <OutputName>Template</OutputName>
          <CreateExecutable>1</CreateExecutable>
          <DebugInformation>1</DebugInformation>
        </TargetCommonOption>
        <TargetArmAds>
          <Cads>
            <VariousControls>
              <MiscControls></MiscControls>
              <Define>USE_STDPERIPH_DRIVER, STM32F10X_MD</Define>
              <Undefine></Undefine>
              <IncludePath>..\\User;..\\Device</IncludePath>
            </VariousControls>
          </Cads>
          <Aads>
            <VariousControls>
              <MiscControls></MiscControls>
              <Define></Define>
              <Undefine></Undefine>
              <IncludePath></IncludePath>
            </VariousControls>
          </Aads>
        </TargetArmAds>
      </TargetOption>
      <Groups>
        <Group>
          <GroupName>User</GroupName>
          <Files>
            <File>
              <FileName>main.c</FileName>
              <FileType>1</FileType>
              <FilePath>..\\User\\main.c</FilePath>
            </File>
          </Files>
        </Group>
      </Groups>
    </Target>
  </Targets>
</Project>
"""


class UVisionProjectCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mdk = os.path.join(self.tmp, "MDK-ARM")
        os.makedirs(self.mdk)
        os.makedirs(os.path.join(self.tmp, "User"))
        self.path = os.path.join(self.mdk, "Template.uvprojx")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(UVISION_XML)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def section(self, xpath):
        return ET.parse(self.path).getroot().find(xpath)


class IncludePathLandsInTheCompiler(UVisionProjectCase):
    """The first <IncludePath> in a target is Folder Setup, which armcc never sees.
    Writing there reported success while the build still failed with #5."""

    def test_include_goes_to_cads(self):
        KeilProjectEditor(self.path).add_include_paths(
            [os.path.join(self.tmp, "mcu_support")]).save()
        cads = self.section(".//Cads/VariousControls/IncludePath").text
        self.assertEqual(cads, "..\\User;..\\Device;..\\mcu_support")

    def test_folder_setup_and_assembler_untouched(self):
        KeilProjectEditor(self.path).add_include_paths(
            [os.path.join(self.tmp, "mcu_support")]).save()
        self.assertFalse(self.section(".//TargetCommonOption/IncludePath").text)
        self.assertFalse(self.section(".//Aads/VariousControls/IncludePath").text)

    def test_define_goes_to_cads(self):
        KeilProjectEditor(self.path).add_defines(["USE_FULL_ASSERT"]).save()
        self.assertIn("USE_FULL_ASSERT",
                      self.section(".//Cads/VariousControls/Define").text)
        self.assertFalse(self.section(".//Aads/VariousControls/Define").text)


class AC5LogAsUVisionWritesIt(unittest.TestCase):
    """Verbatim from the template build. Before the fix the parser returned no errors,
    so the report said only 'no image produced' and the AI had nothing to act on."""

    LOG = (
        "compiling main.c...\n"
        "..\\User\\main.c(17): error:  #5: cannot open source input file "
        "\"cm_backtrace_lite.h\": No such file or directory\n"
        "  #include \"cm_backtrace_lite.h\"\n"
        "..\\User\\main.c: 0 warnings, 1 error\n"
        "..\\User\\main.c(9): warning:  #177-D: variable \"x\" was declared but never referenced\n"
        "\".\\Objects\\Template.axf\" - 1 Error(s), 1 Warning(s).\n"
    )

    def test_error_is_located(self):
        errors, warnings = KeilBuilder(None, BuildConfig())._parse_log_messages(
            self.LOG, r"C:\proj\MDK-ARM")
        self.assertEqual(len(errors), 1)
        e = errors[0]
        self.assertEqual((e.line_number, e.error_code), (17, "5"))
        self.assertTrue(e.file_path.endswith(os.path.join("User", "main.c")))
        self.assertIn("cm_backtrace_lite.h", e.message)
        self.assertEqual([(w.line_number, w.error_code) for w in warnings], [(9, "177-D")])

    def test_path_with_parentheses(self):
        line = 'C:\\Program Files (x86)\\proj\\main.c(5): error:  #20: identifier "a" is undefined'
        errors, _ = KeilBuilder(None, BuildConfig())._parse_log_messages(line, r"C:\proj")
        self.assertEqual(errors[0].line_number, 5)
        self.assertTrue(errors[0].file_path.startswith(r"C:\Program Files (x86)"))


class CompilerRecordSync(UVisionProjectCase):
    """A <pCCUsed> that is missing or names another compiler makes `UV4 -b` rebuild
    every file on every run: uVision fixes it in memory and batch mode never saves."""

    UV4 = r"D:\keil5\UV4\UV4.exe"
    LOG_AC5 = ("*** Using Compiler 'V5.06 update 5 (build 528)', folder: 'D:\\keil5\\ARM\\ARMCC\\Bin'\n"
               "Build target 'Template'\n")
    RECORD = "5060528::V5.06 update 5 (build 528)::ARMCC"

    def setUp(self):
        super().setUp()
        with open(self.path, encoding="utf-8") as f:
            text = f.read()
        # uVision's own element order: ...<TargetName>, <ToolsetName>, [pCCUsed], <uAC6>
        text = text.replace("      <TargetOption>",
                            "      <ToolsetName>ARM-ADS</ToolsetName>\n"
                            "      <uAC6>0</uAC6>\n      <TargetOption>", 1)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
        self.builder = KeilBuilder(self.UV4, BuildConfig())

    def pcc(self):
        return self.section(".//Target/pCCUsed")

    def test_record_matches_what_uvision_writes(self):
        self.assertEqual(self.builder._compiler_record(self.LOG_AC5), self.RECORD)

    def test_ac6_record(self):
        log = "*** Using Compiler 'V6.16', folder: 'D:\\keil5\\ARM\\ARMCLANG\\Bin'\n"
        self.assertEqual(self.builder._compiler_record(log), "6160000::V6.16::ARMCLANG")

    def test_missing_tag_is_inserted_before_uac6(self):
        self.assertIsNotNone(self.builder.sync_compiler_record(self.path, self.LOG_AC5))
        self.assertEqual(self.pcc().text, self.RECORD)
        with open(self.path, encoding="utf-8") as f:
            text = f.read()
        self.assertLess(text.index("<pCCUsed>"), text.index("<uAC6>"))

    def test_cubemx_project_without_uac6_gets_the_record(self):
        """STM32CubeMX writes neither tag. Without a second anchor the sync silently did
        nothing, and every build of a generated HAL project stayed a full rebuild."""
        with open(self.path, encoding="utf-8") as f:
            text = f.read().replace("      <uAC6>0</uAC6>\n", "", 1)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
        self.assertIsNotNone(self.builder.sync_compiler_record(self.path, self.LOG_AC5))
        self.assertEqual(self.pcc().text, self.RECORD)
        with open(self.path, encoding="utf-8") as f:
            text = f.read()
        self.assertLess(text.index("</ToolsetName>"), text.index("<pCCUsed>"))
        self.assertNotIn("<uAC6>", text, "the compiler choice itself must stay untouched")

    def test_other_version_is_replaced(self):
        with open(self.path, encoding="utf-8") as f:
            text = f.read().replace(
                "<uAC6>", "<pCCUsed>5060960::V5.06 update 7 (build 960)::.\\ARMCC</pCCUsed>\n"
                          "      <uAC6>", 1)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
        self.builder.sync_compiler_record(self.path, self.LOG_AC5)
        self.assertEqual(self.pcc().text, self.RECORD)

    def test_same_version_other_folder_spelling_is_left_alone(self):
        own = "5060528::V5.06 update 5 (build 528)::.\\ARMCC"
        with open(self.path, encoding="utf-8") as f:
            text = f.read().replace("<uAC6>", f"<pCCUsed>{own}</pCCUsed>\n      <uAC6>", 1)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
        self.assertIsNone(self.builder.sync_compiler_record(self.path, self.LOG_AC5))
        self.assertEqual(self.pcc().text, own)

    def test_no_compiler_line_changes_nothing(self):
        with open(self.path, "rb") as f:
            before = f.read()
        self.assertIsNone(self.builder.sync_compiler_record(self.path, "Build target 'x'\n"))
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_compiler_outside_the_keil_tree_is_not_guessed(self):
        log = "*** Using Compiler 'V6.22', folder: 'C:\\ArmCompiler6.22\\bin'\n"
        self.assertIsNone(self.builder._compiler_record(log))


class CliEntryPoint(UVisionProjectCase):
    """Nothing ran main() before, so a NameError on the first line of every command
    shipped in five releases."""

    def run_cli(self, *args):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, os.path.join(KIT, "run_autodebug.py"), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=120)

    def test_project_flag_is_honoured(self):
        with open(os.path.join(self.tmp, "User", "main.c"), "w", encoding="utf-8") as f:
            f.write('int main(void){ cm_backtrace_init(); printf("[ALL TESTS PASSED]"); }\n'
                    'void cm_backtrace_putchar(char c){ (void)c; }\n')
        proc = self.run_cli("--project", self.path, "--check-firmware")
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_missing_project_is_a_config_error(self):
        proc = self.run_cli("--project", os.path.join(self.tmp, "nope.uvprojx"), "--no-flash")
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(proc.returncode, 6)


if __name__ == "__main__":
    unittest.main()
