"""Regressions from the first field report on real hardware (v2.4.3, F103C8 + ST-Link V2-1).

Each case below cost the reporting session real time, and most of them misled the AI
into changing code that was already correct: a link fault reported as a firmware fault,
an unchanged rerun reported as a failed patch, a repeated flag silently dropped, a slow
clock waved through as a pass.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KIT)

from autodebug import timebase
from autodebug.builder import BuildResult, CompilerMessage
from autodebug.config import AutoDebugConfig, DebuggerConfig
from autodebug.diagnostic_report import (
    DiagnosticReporter, STATUS_TIMEBASE_SKEW, missing_hal_modules,
)
from autodebug.engine import (
    AutoDebugEngine, EXIT_CODES, fold_iteration_outcome, fresh_loop_state, source_fingerprint,
)
from autodebug.hal_modules import enable_hal_modules
from autodebug.hardware_probe import HardwareProbe

CRLF = "\r\n"

UVPROJX = """<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<Project>
  <Targets>
    <Target>
      <TargetName>App</TargetName>
      <ToolsetName>ARM-ADS</ToolsetName>
      <TargetOption>
        <TargetCommonOption>
          <IncludePath></IncludePath>
          <OutputName>App</OutputName>
          <CreateExecutable>1</CreateExecutable>
        </TargetCommonOption>
        <TargetArmAds>
          <Cads>
            <VariousControls>
              <MiscControls></MiscControls>
              <Define>USE_HAL_DRIVER,STM32F103xB</Define>
              <Undefine></Undefine>
              <IncludePath>../Core/Inc</IncludePath>
            </VariousControls>
          </Cads>
        </TargetArmAds>
      </TargetOption>
      <Groups>
        <Group>
          <GroupName>Drivers/STM32F1xx_HAL_Driver</GroupName>
          <Files>
            <File>
              <FileName>stm32f1xx_hal_gpio.c</FileName>
              <FileType>1</FileType>
              <FilePath>../Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_gpio.c</FilePath>
            </File>
          </Files>
        </Group>
      </Groups>
    </Target>
  </Targets>
</Project>
"""

HAL_CONF = CRLF.join([
    "#define HAL_MODULE_ENABLED",
    "/*#define HAL_ADC_MODULE_ENABLED   */",
    "/*#define HAL_I2C_MODULE_ENABLED   */",
    "#define HAL_GPIO_MODULE_ENABLED",
    "#ifdef HAL_ADC_MODULE_ENABLED",
    "#include \"stm32f1xx_hal_adc.h\"",
    "#endif /* HAL_ADC_MODULE_ENABLED */",
    "",
])


class ProjectCase(unittest.TestCase):
    """A CubeMX-shaped HAL project in a temp dir: Core/, Drivers/, MDK-ARM/."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "Proj")
        for d in ("MDK-ARM", "Core/Inc", "Core/Src",
                  "Drivers/STM32F1xx_HAL_Driver/Src", "Drivers/STM32F1xx_HAL_Driver/Inc"):
            os.makedirs(os.path.join(self.root, d))
        self.uvprojx = os.path.join(self.root, "MDK-ARM", "App.uvprojx")
        self.write("MDK-ARM/App.uvprojx", UVPROJX)
        with open(os.path.join(self.root, "Core/Inc/stm32f1xx_hal_conf.h"), "w",
                  encoding="utf-8", newline="") as f:
            f.write(HAL_CONF)
        for stem in ("stm32f1xx_hal_gpio",):
            self.write(f"Drivers/STM32F1xx_HAL_Driver/Src/{stem}.c", "/* gpio */\n")
            self.write(f"Drivers/STM32F1xx_HAL_Driver/Inc/{stem}.h", "/* gpio */\n")
        # An empty home, so the real CubeMX repository on the test machine is never used.
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.env = mock.patch.dict(os.environ, {"USERPROFILE": self.home})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def read(self, rel, newline=None):
        with open(os.path.join(self.root, rel), encoding="utf-8", newline=newline) as f:
            return f.read()


# --------------------------------------------------------------------------- CLI flags

class RepeatedFlagsAccumulate(ProjectCase):
    """`--add-include A --add-include B` kept only B: nargs="+" without action="extend"."""

    def cli(self, *args):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, os.path.join(KIT, "run_autodebug.py"),
                               "--project", self.uvprojx, *args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=120)

    def test_every_include_lands(self):
        for d in ("Mw/FreeRTOS/include", "Mw/FreeRTOS/portable"):
            os.makedirs(os.path.join(self.root, d))
        proc = self.cli("--add-include", os.path.join(self.root, "Mw/FreeRTOS/include"),
                        "--add-include", os.path.join(self.root, "Mw/FreeRTOS/portable"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = self.read("MDK-ARM/App.uvprojx")
        self.assertIn("FreeRTOS\\include", text)
        self.assertIn("FreeRTOS\\portable", text)
        self.assertIn("当前包含路径", proc.stdout, "the end state must be echoed")

    def test_every_define_lands(self):
        proc = self.cli("--add-define", "A_ONE", "--add-define", "B_TWO")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("A_ONE", proc.stdout)
        self.assertIn("B_TWO", self.read("MDK-ARM/App.uvprojx"))


# --------------------------------------------------------------------------- stall policy

class UnchangedSourceIsNotAFailedPatch(unittest.TestCase):
    def test_same_failure_same_source_is_not_counted(self):
        state, repeated, stalled = fold_iteration_outcome(
            fresh_loop_state(), "TIMEOUT|no bytes", False, source_fingerprint="fp1")
        state, repeated, stalled = fold_iteration_outcome(
            state, "TIMEOUT|no bytes", False, source_fingerprint="fp1")
        self.assertFalse(stalled, "nothing was patched, so nothing failed to take effect")
        self.assertFalse(repeated)
        self.assertTrue(state["source_unchanged"])

    def test_same_failure_after_an_edit_still_escalates(self):
        state, _, _ = fold_iteration_outcome(fresh_loop_state(), "X", False, source_fingerprint="a")
        _, repeated, stalled = fold_iteration_outcome(state, "X", False, source_fingerprint="b")
        self.assertTrue(repeated)
        self.assertTrue(stalled)

    def test_unchanged_reruns_do_not_pile_up_in_the_window(self):
        state, _, _ = fold_iteration_outcome(fresh_loop_state(), "X", False, source_fingerprint="a")
        for _ in range(5):
            state, _, stalled = fold_iteration_outcome(state, "X", False, source_fingerprint="a")
            self.assertFalse(stalled)
        self.assertEqual(state["recent_signatures"], ["X"])


class SourceFingerprint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "Core"))
        os.makedirs(os.path.join(self.tmp, "MDK-ARM", "Objects"))
        self.c = os.path.join(self.tmp, "Core", "main.c")
        with open(self.c, "w") as f:
            f.write("int main(void){return 0;}\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_content_edit_changes_it(self):
        before = source_fingerprint(self.tmp)
        with open(self.c, "a") as f:
            f.write("/* edit */\n")
        self.assertNotEqual(before, source_fingerprint(self.tmp))

    def test_rewrite_with_identical_bytes_does_not(self):
        """Keil regenerates RTE headers with the same bytes on every build."""
        before = source_fingerprint(self.tmp)
        os.utime(self.c, (1, 1))
        self.assertEqual(before, source_fingerprint(self.tmp))

    def test_build_output_is_ignored(self):
        before = source_fingerprint(self.tmp)
        with open(os.path.join(self.tmp, "MDK-ARM", "Objects", "main.o"), "wb") as f:
            f.write(b"\x00")
        with open(os.path.join(self.tmp, "MDK-ARM", "build_autodebug.log"), "w") as f:
            f.write("log")
        self.assertEqual(before, source_fingerprint(self.tmp))


# --------------------------------------------------------------------------- silent link

class SilentLinkLeadsWithWiring(unittest.TestCase):
    def report(self, raw, hwid=""):
        return DiagnosticReporter.create_from_timeout(
            1, "App.uvprojx", raw, 15, "COM6", True, ["[ALL TESTS PASSED]"],
            port_hwid=hwid)

    def test_zero_bytes_points_at_the_link_first(self):
        r = self.report("")
        self.assertEqual(r.signature, "TIMEOUT|no bytes")
        self.assertIn("物理链路", r.next_actions[0])

    def test_stlink_vcp_is_named(self):
        r = self.report("", "USB VID:PID=0483:374B SER=0672FF545348867187011624")
        self.assertTrue(any("ST-Link 自带的虚拟串口" in a for a in r.next_actions))

    def test_output_present_keeps_the_firmware_advice(self):
        r = self.report("[BOOT] hello\r\n")
        self.assertEqual(r.signature, "TIMEOUT|no pass token")
        self.assertNotIn("物理链路", r.next_actions[0])


# --------------------------------------------------------------------------- device packs

class PackInstall(unittest.TestCase):
    def cfg(self, **debugger):
        cfg = AutoDebugConfig.load()
        for k, v in debugger.items():
            setattr(cfg.debugger, k, v)
        return cfg

    def test_missing_pack_is_installed_automatically(self):
        cfg = self.cfg(auto_install_pack=True)
        answers = iter([False, True])
        with mock.patch.object(AutoDebugConfig, "_pyocd_knows_target",
                               side_effect=lambda n: next(answers)), \
             mock.patch.object(AutoDebugConfig, "_install_pack",
                               return_value=(True, "")) as install:
            self.assertEqual(cfg._pack_problems("stm32f103c8"), [])
        install.assert_called_once_with("stm32f103c8")

    def test_failed_install_explains_both_routes(self):
        cfg = self.cfg(auto_install_pack=True)
        with mock.patch.object(AutoDebugConfig, "_pyocd_knows_target", return_value=False), \
             mock.patch.object(AutoDebugConfig, "_install_pack",
                               return_value=(False, "：网络超时")):
            (msg,) = cfg._pack_problems("stm32f103c8")
        self.assertIn("python -m pyocd pack install stm32f103c8", msg)
        self.assertIn("debugger.pack_files", msg, "the offline route must be named")

    def test_offline_pack_files_skip_the_index(self):
        with tempfile.NamedTemporaryFile(suffix=".pack", delete=False) as f:
            pack = f.name
        try:
            cfg = self.cfg(pack_files=[pack])
            with mock.patch.object(AutoDebugConfig, "_pyocd_knows_target") as knows:
                self.assertEqual(cfg._pack_problems("stm32f103c8"), [])
            knows.assert_not_called()
            probe = HardwareProbe(cfg.debugger)
            self.assertEqual(probe._session_options()["pack"], [pack])
        finally:
            os.remove(pack)

    def test_missing_offline_pack_is_reported(self):
        cfg = self.cfg(pack_files=[r"Z:\nope\Keil.STM32F1xx_DFP.2.4.1.pack"])
        (msg,) = cfg._pack_problems("stm32f103c8")
        self.assertIn("不存在", msg)


# --------------------------------------------------------------------------- HAL modules

class EnableHalModules(ProjectCase):
    def add_driver(self, base, stem):
        for ext, sub in ((".c", "Src"), (".h", "Inc")):
            path = os.path.join(base, sub, stem + ext)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(f"/* {stem} */\n")

    def test_macro_files_and_project_in_one_step(self):
        drv = os.path.join(self.root, "Drivers", "STM32F1xx_HAL_Driver")
        self.add_driver(drv, "stm32f1xx_hal_adc")
        self.add_driver(drv, "stm32f1xx_hal_adc_ex")
        result, errors = enable_hal_modules(self.uvprojx, ["adc"])
        self.assertEqual(errors, [])
        conf = self.read("Core/Inc/stm32f1xx_hal_conf.h", newline="")
        self.assertIn("\r\n#define HAL_ADC_MODULE_ENABLED\r\n", conf, "CRLF must survive")
        project = self.read("MDK-ARM/App.uvprojx")
        self.assertIn("stm32f1xx_hal_adc.c", project)
        self.assertIn("stm32f1xx_hal_adc_ex.c", project)
        self.assertEqual(project.count("<GroupName>"), 1, "must join the existing HAL group")

    def test_missing_files_come_from_the_cube_repository(self):
        repo = os.path.join(self.home, "STM32Cube", "Repository", "STM32Cube_FW_F1_V1.8.7",
                            "Drivers", "STM32F1xx_HAL_Driver")
        self.add_driver(repo, "stm32f1xx_hal_i2c")
        result, errors = enable_hal_modules(self.uvprojx, ["i2c"])
        self.assertEqual(errors, [])
        self.assertTrue(os.path.exists(os.path.join(
            self.root, "Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_i2c.c")))
        self.assertTrue(any("CubeMX" in n for n in result.notes))

    def test_any_error_means_no_change_at_all(self):
        drv = os.path.join(self.root, "Drivers", "STM32F1xx_HAL_Driver")
        self.add_driver(drv, "stm32f1xx_hal_adc")
        before = (self.read("Core/Inc/stm32f1xx_hal_conf.h"), self.read("MDK-ARM/App.uvprojx"))
        _result, errors = enable_hal_modules(self.uvprojx, ["adc", "nosuch"])
        self.assertTrue(errors)
        self.assertEqual(before, (self.read("Core/Inc/stm32f1xx_hal_conf.h"),
                                  self.read("MDK-ARM/App.uvprojx")))

    def test_missing_driver_everywhere_says_where_to_get_it(self):
        _result, errors = enable_hal_modules(self.uvprojx, ["i2c"])
        self.assertTrue(errors)
        self.assertIn("CubeMX", errors[0])

    def test_second_run_changes_nothing(self):
        drv = os.path.join(self.root, "Drivers", "STM32F1xx_HAL_Driver")
        self.add_driver(drv, "stm32f1xx_hal_adc")
        enable_hal_modules(self.uvprojx, ["adc"])
        result, errors = enable_hal_modules(self.uvprojx, ["adc"])
        self.assertEqual(errors, [])
        self.assertFalse(result.changed)


class MissingHalModuleHint(unittest.TestCase):
    def err(self, message):
        return CompilerMessage("main.c", 1, None, "error", "", message)

    def test_every_symptom_maps_to_its_module(self):
        errors = [
            self.err('cannot open source input file "stm32f1xx_hal_adc.h": No such file'),
            self.err('identifier "I2C_HandleTypeDef" is undefined'),
            self.err("Undefined symbol HAL_TIM_PWM_Start (referred from main.o)."),
            self.err("unknown type name 'SPI_HandleTypeDef'"),
            self.err("Undefined symbol HAL_ADCEx_Calibration_Start (referred from main.o)."),
        ]
        self.assertEqual(missing_hal_modules(errors), ["adc", "i2c", "tim", "spi"])

    def test_core_modules_are_not_suggested(self):
        errors = [self.err('identifier "GPIO_InitTypeDef" is undefined'),
                  self.err("Undefined symbol HAL_Delay (referred from main.o)."),
                  self.err('cannot open source input file "stm32f1xx_hal_conf.h"')]
        self.assertEqual(missing_hal_modules(errors), [])

    def test_build_report_leads_with_the_command(self):
        res = BuildResult(False, 2, "App", None, None,
                          errors=[self.err('identifier "ADC_HandleTypeDef" is undefined')])
        report = DiagnosticReporter.create_from_build_failure(res, 1, "App.uvprojx")
        self.assertIn("--enable-hal adc", report.next_actions[0])


# --------------------------------------------------------------------------- timebase

class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


class TimebaseCheck(unittest.TestCase):
    def reader(self, clock, rates, extra=None):
        """Counters that advance at `rates` Hz against the fake clock."""
        start = clock.now

        def read(addr, width):
            if extra and addr in extra:
                return extra[addr]
            return int((clock.now - start) * rates[addr])
        return read

    def test_correct_tick_passes(self):
        clock = FakeClock()
        read = self.reader(clock, {0x2000: 1000.0})
        found = timebase.measure([timebase.TickCounter("uwTick", 0x2000, 1000.0)], read, 0.5,
                                 clock=clock, sleep=clock.sleep)
        self.assertEqual(timebase.skewed(found, 0.05), [])

    def test_eight_times_slow_is_caught(self):
        clock = FakeClock()
        read = self.reader(clock, {0x2000: 125.0})
        found = timebase.measure([timebase.TickCounter("uwTick", 0x2000, 1000.0)], read, 0.5,
                                 clock=clock, sleep=clock.sleep)
        bad = timebase.skewed(found, 0.05)
        self.assertEqual(len(bad), 1)
        self.assertAlmostEqual(bad[0].ratio, 0.125, places=2)

    def test_stopped_counter_is_not_a_failure(self):
        clock = FakeClock()
        found = timebase.measure([timebase.TickCounter("uwTick", 0x2000, 1000.0)],
                                 lambda a, w: 42, 0.5, clock=clock, sleep=clock.sleep)
        self.assertEqual(timebase.skewed(found, 0.05), [])

    def test_slow_tick_gets_a_longer_window(self):
        clock = FakeClock()
        read = self.reader(clock, {0x2000: 10.0})
        found = timebase.measure([timebase.TickCounter("t", 0x2000, 10.0)], read, 0.5,
                                 clock=clock, sleep=clock.sleep)
        self.assertGreaterEqual(found[0].seconds, 2.0 - 1e-9)

    def test_hal_tick_freq_sets_the_expectation(self):
        symbols = {"uwTick": 0x2000, "uwTickFreq": 0x2004}
        counters = timebase.find_counters(symbols.get, lambda a, w: 10 if a == 0x2004 else 0)
        self.assertEqual(counters[0].expected_hz, 100.0)

    def test_freertos_rate_comes_from_its_config(self):
        tmp = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmp, "FreeRTOSConfig.h"), "w") as f:
                f.write("#define configTICK_RATE_HZ   ( ( TickType_t ) 1000 )\n"
                        "#define configUSE_TICKLESS_IDLE 0\n")
            counters = timebase.find_counters({"xTickCount": 0x3000}.get,
                                              lambda a, w: 0, tmp)
            self.assertEqual([(c.name, c.expected_hz) for c in counters],
                             [("xTickCount", 1000.0)])
            with open(os.path.join(tmp, "FreeRTOSConfig.h"), "a") as f:
                f.write("#undef configUSE_TICKLESS_IDLE\n#define configUSE_TICKLESS_IDLE 1\n")
            self.assertEqual(timebase.freertos_settings(tmp)["tickless"], 1)
            self.assertEqual(timebase.find_counters({"xTickCount": 0x3000}.get,
                                                    lambda a, w: 0, tmp), [],
                             "tickless idle advances in jumps: not measurable this way")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_systick_context_reproduces_the_field_bug(self):
        values = {timebase.SYST_CSR: 0x00010003, timebase.SYST_RVR: 71999, 0x2000: 72000000}
        ctx = timebase.systick_context(lambda a, w: values.get(a),
                                       {"SystemCoreClock": 0x2000}.get)
        self.assertEqual(ctx["clock_source"], "HCLK/8")
        self.assertEqual(ctx["systick_hz_from_registers"], 125.0)

    def test_report_names_the_hclk8_trap(self):
        finding = timebase.TimebaseFinding("uwTick", 125.0, 1000.0, 62, 0.5)
        r = DiagnosticReporter.create_from_timebase_skew(1, "App.uvprojx", "", [finding], {})
        self.assertEqual(r.status, STATUS_TIMEBASE_SKEW)
        self.assertEqual(EXIT_CODES[STATUS_TIMEBASE_SKEW], 3)
        self.assertIn("configSYSTICK_CLOCK_HZ", r.next_actions[0])

    def test_engine_check_uses_the_probe_and_symbols(self):
        engine = AutoDebugEngine.__new__(AutoDebugEngine)
        engine.config = AutoDebugConfig.load()
        engine.config.loop.timebase_sample_seconds = 0.2
        engine.verbose = False

        def read_memory(addr, width=32):
            if addr == 0x2000:               # uwTick: advances 125 per real 1000 ms
                import time as _t
                return int(_t.perf_counter() * 125)
            return None
        engine.probe = SimpleNamespace(read_memory=read_memory)
        resolver = SimpleNamespace(loaded=True,
                                   get_symbol_address={"uwTick": 0x2000}.get)
        bad, _ctx = engine._check_timebase(resolver, tempfile.gettempdir())
        self.assertEqual([b.name for b in bad], ["uwTick"])
        engine.config.loop.timebase_check = False
        self.assertEqual(engine._check_timebase(resolver, tempfile.gettempdir()), ([], {}))


# --------------------------------------------------------------------------- setup + docs

class DepsCheck(unittest.TestCase):
    def test_pip_leftovers_are_cleared(self):
        from autodebug import deps_check
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "~msis_pack_manager"))
            os.makedirs(os.path.join(tmp, "yaml"))
            with mock.patch.object(deps_check, "site_dirs", return_value=[tmp]):
                removed = deps_check.clear_leftovers()
            self.assertEqual([os.path.basename(p) for p in removed], ["~msis_pack_manager"])
            self.assertTrue(os.path.isdir(os.path.join(tmp, "yaml")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unfixable_import_fails_with_the_command(self):
        from autodebug import deps_check
        out = io.StringIO()
        with mock.patch.object(deps_check, "REQUIRED", {"no_such_mod_xyz": "no-such-pkg"}), \
             mock.patch.object(deps_check, "OPTIONAL", {}), \
             mock.patch.object(deps_check, "clear_leftovers", return_value=[]), \
             mock.patch.object(deps_check.subprocess, "call", return_value=1), \
             mock.patch("sys.stdout", out):
            self.assertEqual(deps_check.main(), 1)
        self.assertIn("--force-reinstall no-such-pkg", out.getvalue())


class DocsUnzipCommand(unittest.TestCase):
    """`tar -xf x.zip` fails in Git Bash (GNU tar), which is the shell most agents use."""

    def test_no_doc_tells_agents_to_untar_a_zip(self):
        for rel in ("README.md", "AGENTS.md", "skills/stm32-autodebug/SKILL.md"):
            with self.subTest(doc=rel):
                with open(os.path.join(KIT, rel), encoding="utf-8") as f:
                    text = f.read()
                self.assertNotIn("tar -xf", text)
                if "template.zip" in text:
                    self.assertIn("python -m zipfile -e", text)


if __name__ == "__main__":
    unittest.main()
