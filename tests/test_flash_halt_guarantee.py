# -*- coding: utf-8 -*-
"""Regressions for four bugs that only showed up on real hardware.

Every one of them made the tool report something that was not true, and each sent the
diagnosis somewhere useless:

  1. A CLI-fallback flash resets and RUNS the target, silently voiding the
     halt-until-the-monitor-is-listening guarantee the whole tool rests on. The boot
     banner was gone before anything could read it, and the run then looked exactly
     like firmware that never printed a pass token.
  2. The success log claimed "CPU 已停在复位入口等待放行" unconditionally, so the
     lost guarantee above was invisible in the log.
  3. is_target_running() read the PC without halting. A Cortex-M debug port refuses
     that on a running core, so the read raised, the handler returned None, and the
     True branch was unreachable -- a healthy board reported as halted or unknown.
  4. "target type ... not recognized" is a missing CMSIS pack, not a wiring fault, but
     the flash-failure report led with four wiring suggestions.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autodebug.diagnostic_report import DiagnosticReporter, _unrecognized_target
from autodebug.firmware_setup import _cmsis_header, _uses_std_periph
from autodebug.hardware_probe import FlashResult, HardwareProbe


class FakeTarget:
    """Minimal Cortex-M stand-in that refuses register reads while running, like pyOCD."""

    def __init__(self, halted=False, pcs=None):
        self._halted = halted
        self._pcs = list(pcs or [])
        self.resume_calls = 0

    def is_halted(self):
        return self._halted

    def halt(self):
        self._halted = True

    def resume(self):
        self._halted = False
        self.resume_calls += 1

    def reset_and_halt(self):
        self._halted = True

    def read_core_register(self, name):
        if not self._halted:
            raise RuntimeError("Core is not halted; cannot read core registers")
        return self._pcs.pop(0) if self._pcs else 0x08000000


class FakeSession:
    def __init__(self, target):
        self.target = target


def _probe_with(target):
    probe = HardwareProbe.__new__(HardwareProbe)
    probe._session = FakeSession(target)
    probe.open = lambda: True
    return probe


class TargetNotRecognisedTests(unittest.TestCase):
    def test_extracts_target_name_from_pyocd_complaint(self):
        msg = ("0001302 C Target type stm32f103c8 not recognized. "
               "Use 'pyocd list --targets' to see currently available target types.")
        self.assertEqual(_unrecognized_target(msg), "stm32f103c8")

    def test_ignores_unrelated_flash_failures(self):
        self.assertIsNone(_unrecognized_target("No connected probes"))
        self.assertIsNone(_unrecognized_target(""))

    def test_report_leads_with_the_pack_install_not_with_wiring(self):
        report = DiagnosticReporter.create_from_flash_failure(
            "Target type stm32f103c8 not recognized.", 1, "x.uvprojx", ["ST-Link"])
        first = report.next_actions[0]
        self.assertIn("stm32f103c8", first)
        self.assertTrue(any("pack install stm32f103c8" in a for a in report.next_actions),
                        "the one command that fixes it must be spelled out")
        # The wiring checklist is the wrong trail here and must not be offered at all;
        # saying "this is NOT a wiring problem" is fine and is why we match the checklist
        # item itself rather than the word.
        joined = " ".join(report.next_actions)
        self.assertNotIn("SWDIO / SWCLK / GND / 3V3", joined)
        self.assertNotIn("RDP Level 1", joined)

    def test_ordinary_flash_failure_still_gets_wiring_advice(self):
        report = DiagnosticReporter.create_from_flash_failure(
            "No connected probes", 1, "x.uvprojx", [])
        self.assertIn("接线", " ".join(report.next_actions))


class CpuLivenessTests(unittest.TestCase):
    def test_running_core_with_advancing_pc_reports_running(self):
        target = FakeTarget(halted=False, pcs=[0x08000100, 0x08000200])
        self.assertIs(_probe_with(target).is_target_running(sample_gap=0), True)

    def test_running_core_stuck_at_one_address_reports_not_running(self):
        target = FakeTarget(halted=False, pcs=[0x08000100, 0x08000100])
        self.assertIs(_probe_with(target).is_target_running(sample_gap=0), False)

    def test_halted_core_reports_not_running(self):
        self.assertIs(_probe_with(FakeTarget(halted=True)).is_target_running(0), False)

    def test_core_is_left_running_after_telemetry(self):
        target = FakeTarget(halted=False, pcs=[0x08000100, 0x08000200])
        _probe_with(target).is_target_running(sample_gap=0)
        self.assertFalse(target.is_halted(),
                         "telemetry must not park the core it was only meant to observe")


class FlashHaltGuaranteeTests(unittest.TestCase):
    def test_cli_fallback_reports_halted_only_when_it_really_re_halted(self):
        probe = HardwareProbe.__new__(HardwareProbe)
        probe.close = lambda: None
        probe._rehalt_after_cli = lambda: False
        import autodebug.hardware_probe as hp

        class R:
            returncode, stdout, stderr = 0, "programmed", ""

        original = hp.subprocess.run
        hp.subprocess.run = lambda *a, **k: R()
        try:
            res = probe._flash_pyocd_cli("fw.axf", "uid", "stm32f103c8", halt_after=True)
        finally:
            hp.subprocess.run = original

        self.assertTrue(res.success)
        self.assertFalse(res.halted, "must not claim a halt it could not perform")
        self.assertIn("WARNING", res.message,
                      "a silently voided guarantee is the bug; it has to be said out loud")

    def test_flash_result_defaults_to_not_halted(self):
        self.assertFalse(FlashResult(True, "x").halted)


class TracerHeaderTests(unittest.TestCase):
    def _project(self, tmp, define, extra_files=()):
        os.makedirs(os.path.join(tmp, "MDK-ARM"), exist_ok=True)
        with open(os.path.join(tmp, "MDK-ARM", "App.uvprojx"), "w") as fh:
            fh.write("<Project><Define>%s</Define></Project>" % define)
        for name in extra_files:
            with open(os.path.join(tmp, name), "w") as fh:
                fh.write("/* */")
        return tmp

    def test_std_periph_project_gets_the_std_periph_header(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp, "USE_STDPERIPH_DRIVER,STM32F10X_MD")
            self.assertIs(_uses_std_periph(root), True)
            self.assertEqual(_cmsis_header("f1", root), '#include "stm32f10x.h"')

    def test_hal_project_gets_the_hal_header(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp, "USE_HAL_DRIVER,STM32F103xB")
            self.assertIs(_uses_std_periph(root), False)
            self.assertEqual(_cmsis_header("f1", root), '#include "stm32f1xx.h"')

    def test_unknown_project_falls_back_to_hal(self):
        self.assertEqual(_cmsis_header("f1", None), '#include "stm32f1xx.h"')

    def test_f3_std_periph_header_is_not_derived_by_rule(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp, "USE_STDPERIPH_DRIVER")
            # f3 -> stm32f30x.h, while f4 -> stm32f4xx.h; one rule cannot produce both.
            self.assertEqual(_cmsis_header("f3", root), '#include "stm32f30x.h"')
            self.assertEqual(_cmsis_header("f4", root), '#include "stm32f4xx.h"')

    def test_family_without_std_periph_stays_on_hal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp, "USE_STDPERIPH_DRIVER")
            # ST never shipped StdPeriph for G4, so the define cannot be taken at face value.
            self.assertEqual(_cmsis_header("g4", root), '#include "stm32g4xx.h"')


if __name__ == "__main__":
    unittest.main()
