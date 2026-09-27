"""The firmware contract is checked before flashing, and it decides how long to listen.

With no pass token anywhere in the source, the full serial wait cannot end in a pass;
only a crash dump can still arrive, and that comes within moments of boot. So the run
still builds, flashes and captures -- nothing is blocked -- but it stops waiting for a
line the firmware was never told to print.
"""
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autodebug.builder import BuildResult
from autodebug.config import AutoDebugConfig
from autodebug.diagnostic_report import STATUS_TIMEOUT
from autodebug.engine import AutoDebugEngine
from autodebug.fault_analyzer import CortexMFaultAnalyzer
from autodebug.firmware_setup import check_firmware_contract, firmware_precheck
from autodebug.serial_monitor import SerialTestResult

WITH_TOKEN = ('int main(void){ cm_backtrace_init(); printf("[ALL TESTS PASSED]"); }\n'
              'void cm_backtrace_putchar(char c){ (void)c; }\n')
WITHOUT_TOKEN = ('int main(void){ cm_backtrace_init(); printf("hello"); }\n'
                 'void cm_backtrace_putchar(char c){ (void)c; }\n')


class FakeBuilder:
    def build(self, uvprojx_path, target_name=None):
        return BuildResult(success=True, return_code=0, target_name="App",
                           axf_path=None, hex_path=None)


class FakeProbe:
    probe_available = True

    def open(self): pass
    def clear_fault_registers(self): pass
    def resume(self): pass
    def read_fault_registers(self): return None
    def is_target_running(self): return None
    def describe_probes(self): return ""

    def flash(self, path, halt_after=True):
        return SimpleNamespace(success=True, halted=True, probe_id="FAKE",
                               target_name="stm32f103c8", message="")


class FakeSerial:
    port = "COM9"
    open_error = None

    def __init__(self):
        self.waited = None

    def open(self): return True
    def close(self): pass

    def wait_for_result(self, **kwargs):
        self.waited = kwargs.get("timeout_seconds")
        return SerialTestResult(passed=False, timed_out=True, raw_output="", port=self.port)


class PrecheckDecidesTheWait(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "MDK-ARM"))
        os.makedirs(os.path.join(self.tmp, "User"))
        self.uvprojx = os.path.join(self.tmp, "MDK-ARM", "App.uvprojx")

        self.engine = AutoDebugEngine.__new__(AutoDebugEngine)
        self.engine.config = AutoDebugConfig.load()
        self.engine.config.serial.boot_grace_seconds = 0
        self.engine.verbose = False
        self.engine.builder = FakeBuilder()
        self.engine.probe = FakeProbe()
        self.engine.analyzer = CortexMFaultAnalyzer()
        self.engine.serial_mon = FakeSerial()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_main(self, body):
        with open(os.path.join(self.tmp, "User", "main.c"), "w", encoding="utf-8") as f:
            f.write(body)

    def test_missing_token_shortens_the_wait(self):
        self.write_main(WITHOUT_TOKEN)
        report = self.engine.run_once(self.uvprojx)
        self.assertEqual(self.engine.serial_mon.waited,
                         self.engine.config.test.no_token_wait_seconds)
        self.assertEqual(report.status, STATUS_TIMEOUT)
        self.assertIn("3s", report.summary, "the report must state the wait actually used")

    def test_token_present_keeps_the_full_wait(self):
        self.write_main(WITH_TOKEN)
        self.engine.run_once(self.uvprojx)
        self.assertEqual(self.engine.serial_mon.waited,
                         self.engine.config.serial.timeout_seconds)

    def test_switch_off_restores_the_old_behaviour(self):
        """For a token that lives outside the scanned tree, the check must be escapable."""
        self.write_main(WITHOUT_TOKEN)
        self.engine.config.test.precheck_firmware = False
        self.engine.run_once(self.uvprojx)
        self.assertEqual(self.engine.serial_mon.waited,
                         self.engine.config.serial.timeout_seconds)

    def test_one_scan_agrees_with_the_contract_check(self):
        self.write_main(WITHOUT_TOKEN)
        problems, token_found = firmware_precheck(self.tmp)
        self.assertFalse(token_found)
        self.assertEqual(problems, check_firmware_contract(self.tmp))
        self.write_main(WITH_TOKEN)
        self.assertTrue(firmware_precheck(self.tmp)[1])


if __name__ == "__main__":
    unittest.main()
