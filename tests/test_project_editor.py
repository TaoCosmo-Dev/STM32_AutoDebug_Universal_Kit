"""
Offline tests for the .uvprojx editor - no Keil, no hardware.

These cover the operations that let the AI change project structure on its own. A silent
regression here means a file the AI wrote never reaches the linker, or the project file
gets corrupted, so every case checks the XML is still parseable afterwards.

    python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autodebug.project_editor import (
    BACKUP_SUFFIX, KeilProjectEditor, disable_conflicting_fault_handlers,
)

PROJECT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<Project>
  <Targets>
    <Target>
      <TargetName>App</TargetName>
      <TargetOption>
        <TargetCommonOption>
          <OutputName>App</OutputName>
          <CreateExecutable>1</CreateExecutable>
          <DebugInformation>0</DebugInformation>
        </TargetCommonOption>
        <TargetArmAds>
          <Cads>
            <VariousControls>
              <MiscControls></MiscControls>
              <Define>USE_HAL_DRIVER,STM32F103xB</Define>
              <IncludePath>..\\User;..\\Drivers</IncludePath>
            </VariousControls>
          </Cads>
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

IT_C = """/* stm32f1xx_it.c - HAL template */
#include "main.h"

void NMI_Handler(void)
{
}

void HardFault_Handler(void)
{
  while (1)
  {
  }
}

void SysTick_Handler(void)
{
  HAL_IncTick();
}
"""


class ProjectEditorCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "MDK-ARM"))
        os.makedirs(os.path.join(self.root, "mcu_support"))
        os.makedirs(os.path.join(self.root, "User"))
        self.project = os.path.join(self.root, "MDK-ARM", "App.uvprojx")
        self._write(self.project, PROJECT_XML)
        self.tracer = os.path.join(self.root, "mcu_support", "cm_backtrace_lite.c")
        self.header = os.path.join(self.root, "mcu_support", "cm_backtrace_lite.h")
        self.driver = os.path.join(self.root, "User", "dht11.c")
        for path in (self.tracer, self.header, self.driver):
            self._write(path, "/* stub */\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def _write(path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def read_project(self):
        with open(self.project, encoding="utf-8") as f:
            return f.read()

    def editor(self):
        return KeilProjectEditor(self.project)


class TestAddSources(ProjectEditorCase):
    def test_new_group_is_created_with_the_files(self):
        result = self.editor().add_sources([self.tracer, self.driver]).save()
        self.assertTrue(result.changed)
        text = self.read_project()
        self.assertIn("<GroupName>AutoDebug</GroupName>", text)
        self.assertIn("<FileName>cm_backtrace_lite.c</FileName>", text)
        self.assertIn("<FileName>dht11.c</FileName>", text)
        ET.parse(self.project)

    def test_paths_are_project_relative_with_backslashes(self):
        self.editor().add_sources([self.driver]).save()
        text = self.read_project()
        self.assertIn("<FilePath>..\\User\\dht11.c</FilePath>", text)

    def test_existing_files_are_untouched(self):
        self.editor().add_sources([self.driver]).save()
        self.assertEqual(self.read_project().count("<FilePath>..\\User\\main.c</FilePath>"), 1)

    def test_headers_are_not_added_as_sources(self):
        result = self.editor().add_sources([self.header]).save()
        self.assertFalse(result.changed)

    def test_adding_twice_is_a_no_op(self):
        self.editor().add_sources([self.tracer]).save()
        before = self.read_project()
        result = self.editor().add_sources([self.tracer]).save()
        self.assertFalse(result.changed)
        self.assertEqual(before, self.read_project())

    def test_second_file_joins_the_existing_group(self):
        self.editor().add_sources([self.tracer]).save()
        self.editor().add_sources([self.driver]).save()
        text = self.read_project()
        self.assertEqual(text.count("<GroupName>AutoDebug</GroupName>"), 1)
        self.assertIn("<FileName>dht11.c</FileName>", text)
        ET.parse(self.project)

    def test_can_target_an_existing_group(self):
        self.editor().add_sources([self.driver], group="User").save()
        text = self.read_project()
        self.assertNotIn("<GroupName>AutoDebug</GroupName>", text)
        user_group = text.split("<GroupName>User</GroupName>")[1]
        self.assertIn("<FileName>dht11.c</FileName>", user_group)

    def test_assembly_file_gets_filetype_2(self):
        asm = os.path.join(self.root, "User", "startup.s")
        self._write(asm, "; stub\n")
        self.editor().add_sources([asm]).save()
        block = self.read_project().split("<FileName>startup.s</FileName>")[1]
        self.assertIn("<FileType>2</FileType>", block)


class TestIncludePathsAndDefines(ProjectEditorCase):
    def test_include_path_is_appended_not_replaced(self):
        self.editor().add_include_paths([os.path.join(self.root, "mcu_support")]).save()
        text = self.read_project()
        paths = text.split("<IncludePath>")[1].split("</IncludePath>")[0]
        self.assertIn("..\\User", paths)          # pre-existing entries survive
        self.assertIn("..\\Drivers", paths)
        self.assertIn("..\\mcu_support", paths)

    def test_duplicate_include_path_is_ignored(self):
        self.editor().add_include_paths([os.path.join(self.root, "User")]).save()
        paths = self.read_project().split("<IncludePath>")[1].split("</IncludePath>")[0]
        self.assertEqual(paths.count("..\\User"), 1)

    def test_define_is_appended(self):
        self.editor().add_defines(["AUTODEBUG_ENABLED"]).save()
        defines = self.read_project().split("<Define>")[1].split("</Define>")[0]
        self.assertIn("USE_HAL_DRIVER", defines)
        self.assertIn("AUTODEBUG_ENABLED", defines)

    def test_duplicate_define_is_ignored(self):
        result = self.editor().add_defines(["USE_HAL_DRIVER"]).save()
        self.assertFalse(result.changed)


class TestDebugInformation(ProjectEditorCase):
    def test_switched_on(self):
        self.editor().set_debug_information().save()
        self.assertIn("<DebugInformation>1</DebugInformation>", self.read_project())

    def test_already_on_is_a_no_op(self):
        self._write(self.project, PROJECT_XML.replace(
            "<DebugInformation>0</DebugInformation>", "<DebugInformation>1</DebugInformation>"))
        before = self.read_project()
        result = self.editor().set_debug_information().save()
        self.assertFalse(result.changed)
        self.assertEqual(before, self.read_project())

    def test_missing_tag_is_inserted(self):
        self._write(self.project, PROJECT_XML.replace(
            "          <DebugInformation>0</DebugInformation>\n", ""))
        self.editor().set_debug_information().save()
        self.assertIn("<DebugInformation>1</DebugInformation>", self.read_project())
        ET.parse(self.project)


class TestSafety(ProjectEditorCase):
    def test_original_is_backed_up_once(self):
        self.editor().add_sources([self.driver]).save()
        backup = self.project + BACKUP_SUFFIX
        self.assertTrue(os.path.exists(backup))
        with open(backup, encoding="utf-8") as f:
            self.assertEqual(f.read(), PROJECT_XML)
        # a later edit must not overwrite the pristine backup
        self.editor().add_defines(["EXTRA"]).save()
        with open(backup, encoding="utf-8") as f:
            self.assertEqual(f.read(), PROJECT_XML)

    def test_nothing_to_do_writes_nothing(self):
        editor = self.editor()
        result = editor.save()
        self.assertFalse(result.changed)
        self.assertFalse(os.path.exists(self.project + BACKUP_SUFFIX))

    def test_xml_declaration_and_untouched_regions_survive(self):
        self.editor().add_sources([self.driver]).add_defines(["X"]).save()
        text = self.read_project()
        self.assertTrue(text.startswith('<?xml version="1.0" encoding="UTF-8" standalone="no"?>'))
        self.assertIn("<TargetName>App</TargetName>", text)
        ET.parse(self.project)

    def test_target_names_are_listed(self):
        self.assertEqual(self.editor().target_names(), ["App"])


class TestFaultHandlerCleanup(ProjectEditorCase):
    def setUp(self):
        super().setUp()
        self.it_c = os.path.join(self.root, "User", "stm32f1xx_it.c")
        self._write(self.it_c, IT_C)

    def read_it(self):
        with open(self.it_c, encoding="utf-8") as f:
            return f.read()

    def test_empty_hardfault_stub_is_commented_out(self):
        result = disable_conflicting_fault_handlers(self.root)
        self.assertTrue(result.changed)
        text = self.read_it()
        self.assertIn("AUTODEBUG disabled HardFault_Handler", text)
        # the body is preserved inside the comment, not deleted
        self.assertIn("while (1)", text)

    def test_unrelated_handlers_are_left_alone(self):
        disable_conflicting_fault_handlers(self.root)
        text = self.read_it()
        self.assertIn("void SysTick_Handler(void)", text)
        self.assertIn("HAL_IncTick();", text)
        self.assertIn("void NMI_Handler(void)", text)

    def test_running_twice_changes_nothing_more(self):
        disable_conflicting_fault_handlers(self.root)
        after_first = self.read_it()
        result = disable_conflicting_fault_handlers(self.root)
        self.assertFalse(result.changed)
        self.assertEqual(after_first, self.read_it())

    def test_original_it_c_is_backed_up(self):
        disable_conflicting_fault_handlers(self.root)
        self.assertTrue(os.path.exists(self.it_c + BACKUP_SUFFIX))

    def test_project_without_it_c_is_fine(self):
        os.remove(self.it_c)
        self.assertFalse(disable_conflicting_fault_handlers(self.root).changed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
