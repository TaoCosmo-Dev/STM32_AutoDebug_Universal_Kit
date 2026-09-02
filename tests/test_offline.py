"""
Offline regression tests - no Keil, no probe, no board required.

    python -m unittest discover -s tests -v

Everything covered here is a pure function on the critical path of the closed loop:
log parsing, fault decoding, crash-dump parsing and port selection. These are exactly
the places where a silent regression would make the pipeline lie about success.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autodebug.builder import KeilBuilder
from autodebug.config import AutoDebugConfig, BuildConfig, SerialConfig
from autodebug.fault_analyzer import CortexMFaultAnalyzer
from autodebug.serial_monitor import parse_assertion, parse_crash_block, score_port


class TestBuildLogParsing(unittest.TestCase):
    def setUp(self):
        self.builder = KeilBuilder(uv4_path=None, build_config=BuildConfig())

    def parse(self, log):
        return self.builder._parse_log_messages(log, r"C:\proj")

    def test_armcc_error(self):
        log = '..\\User\\main.c(12): error:  #20: identifier "gpio" is undefined\n' \
              '"..\\User\\main.c", line 42: Error:  #20: identifier "foo" is undefined'
        errors, warnings = self.parse(log)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].line_number, 42)
        self.assertEqual(errors[0].error_code, "20")
        self.assertIn("foo", errors[0].message)
        self.assertEqual(warnings, [])

    def test_armcc_warning_is_not_an_error(self):
        log = '"main.c", line 7: Warning:  #177-D: variable "x" was declared but never referenced'
        errors, warnings = self.parse(log)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].line_number, 7)

    def test_armclang_error(self):
        log = "../Core/Src/main.c:88:5: error: use of undeclared identifier 'htim2'"
        errors, _ = self.parse(log)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].line_number, 88)
        self.assertEqual(errors[0].column, 5)

    def test_linker_error_is_captured(self):
        """A linker error has no file:line; the old parser dropped it entirely."""
        log = ".\\Objects\\app.axf: Error: L6218E: Undefined symbol delay_ms (referred from main.o)."
        errors, _ = self.parse(log)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].error_code, "L6218E")
        self.assertIn("Undefined symbol", errors[0].message)

    def test_duplicate_messages_are_collapsed(self):
        line = '"main.c", line 42: Error:  #20: identifier "foo" is undefined'
        errors, _ = self.parse("\n".join([line, line, line]))
        self.assertEqual(len(errors), 1)

    def test_clean_log_yields_nothing(self):
        errors, warnings = self.parse('Build target \'App\'\n"app.axf" - 0 Error(s), 0 Warning(s).')
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])


class TestFaultDecoding(unittest.TestCase):
    def setUp(self):
        self.a = CortexMFaultAnalyzer()

    def test_divide_by_zero(self):
        title, _ = self.a.classify_root_cause(cfsr=1 << 25, hfsr=0)
        self.assertEqual(title, "Divide by Zero")

    def test_null_pointer_needs_the_fault_address(self):
        cfsr = (1 << 9) | (1 << 15)   # PRECISERR + BFARVALID
        title, detail = self.a.classify_root_cause(cfsr, 0, fault_address=0x00000004)
        self.assertEqual(title, "NULL Pointer Dereference")
        self.assertIn("0x00000004", detail)

    def test_wild_pointer_reports_the_address(self):
        cfsr = (1 << 9) | (1 << 15)
        title, detail = self.a.classify_root_cause(cfsr, 0, fault_address=0xDEADBEEF)
        self.assertEqual(title, "Invalid Bus Access / Wild Pointer")
        self.assertIn("0xDEADBEEF", detail)

    def test_without_a_valid_address_it_does_not_guess_null(self):
        title, _ = self.a.classify_root_cause((1 << 9), 0, fault_address=None)
        self.assertEqual(title, "Data Access Violation")

    def test_fault_address_selection_honours_validity_bits(self):
        # BFAR content is meaningless unless BFARVALID is set.
        self.assertIsNone(self.a.select_fault_address(0, bfar=0x1234, mmfar=None))
        self.assertEqual(self.a.select_fault_address(1 << 15, bfar=0x1234, mmfar=None), 0x1234)
        self.assertEqual(self.a.select_fault_address(1 << 7, bfar=None, mmfar=0x2000), 0x2000)

    def test_stack_overflow_beats_bus_error(self):
        title, _ = self.a.classify_root_cause((1 << 12), 0)   # STKERR
        self.assertEqual(title, "Stack Overflow")

    def test_cfsr_flag_decoding(self):
        flags = self.a.decode_cfsr((1 << 25) | (1 << 15) | (1 << 9))
        joined = " ".join(flags)
        self.assertIn("DIVBYZERO", joined)
        self.assertIn("BFARVALID", joined)
        self.assertIn("PRECISERR", joined)

    def test_hfsr_forced_flag(self):
        self.assertIn("FORCED", " ".join(self.a.decode_hfsr(1 << 30)))

    def test_every_classification_has_a_fix_hint(self):
        for cfsr in (1 << 25, 1 << 24, 1 << 19, 1 << 16, 1 << 12, (1 << 9) | (1 << 15)):
            diag = self.a.analyze(cfsr=cfsr, hfsr=0, bfar=0x4, bfar_valid=True)
            self.assertTrue(diag.suggested_fix, f"no fix hint for CFSR=0x{cfsr:08X}")


class TestCrashBlockParsing(unittest.TestCase):
    BLOCK = (
        "boot ok\r\n"
        "[AUTODEBUG_CRASH_START]\r\n"
        "LR_EXC = 0xFFFFFFF9 (MSP)\r\n"
        "R0 = 0x00000000, R1 = 0x20000100, R2 = 0x00000002, R3 = 0x00000003\r\n"
        "R12 = 0x0000000C, LR = 0x08000AA5, PC = 0x08000B12, XPSR = 0x61000000\r\n"
        "CFSR = 0x00008200, HFSR = 0x40000000, BFAR = 0x00000004, MMFAR = 0xE000ED34\r\n"
        "[Backtrace] >> 0x08000B12 0x08000AA5\r\n"
        "[AUTODEBUG_CRASH_END]\r\n"
    )

    def test_registers_and_backtrace(self):
        crash = parse_crash_block(self.BLOCK)
        self.assertIsNotNone(crash)
        self.assertEqual(crash.get("PC"), 0x08000B12)
        self.assertEqual(crash.get("CFSR"), 0x00008200)
        self.assertEqual(crash.get("BFAR"), 0x00000004)
        self.assertEqual(crash.active_sp, "MSP")
        self.assertEqual(crash.backtrace, [0x08000B12, 0x08000AA5])

    def test_psp_frame_detected(self):
        crash = parse_crash_block(self.BLOCK.replace("(MSP)", "(PSP)"))
        self.assertEqual(crash.active_sp, "PSP")

    def test_truncated_dump_still_parses(self):
        truncated = self.BLOCK.split("[Backtrace]")[0]
        crash = parse_crash_block(truncated)
        self.assertIsNotNone(crash)
        self.assertEqual(crash.get("PC"), 0x08000B12)

    def test_no_crash_returns_none(self):
        self.assertIsNone(parse_crash_block("hello\n[ALL TESTS PASSED]\n"))

    def test_uart_dump_reaches_a_full_diagnosis(self):
        crash = parse_crash_block(self.BLOCK)
        diag = CortexMFaultAnalyzer().from_crash_telemetry(crash)
        self.assertEqual(diag.source, "uart")
        self.assertEqual(diag.fault_address, 0x00000004)
        self.assertIn("NULL Pointer", diag.root_cause)
        self.assertEqual(diag.stack_frame.pc, 0x08000B12)


class TestAssertionParsing(unittest.TestCase):
    def test_kit_format(self):
        got = parse_assertion("[ASSERTION_FAILED] ptr != NULL at file main.c, line 42")
        self.assertEqual(got, ("ptr != NULL", "main.c", 42))

    def test_c99_format(self):
        got = parse_assertion("Assertion failed: (x > 0), file ../Src/app.c, line 7")
        self.assertEqual(got, ("(x > 0)", "../Src/app.c", 7))

    def test_hal_assert_param(self):
        got = parse_assertion("Wrong parameters value: file stm32f4xx_hal_tim.c on line 312")
        self.assertIsNotNone(got)
        self.assertEqual(got[1], "stm32f4xx_hal_tim.c")
        self.assertEqual(got[2], 312)

    def test_plain_line_is_not_an_assertion(self):
        self.assertIsNone(parse_assertion("system clock 168MHz ready"))


class TestPortSelection(unittest.TestCase):
    def setUp(self):
        self.cfg = SerialConfig()

    def test_bluetooth_is_never_selected(self):
        self.assertLess(score_port("Standard Serial over Bluetooth link", "BTHENUM", self.cfg), 0)

    def test_usb_bridge_beats_generic(self):
        ch340 = score_port("USB-SERIAL CH340", "USB VID:PID=1A86:7523", self.cfg)
        generic = score_port("Communications Port", "ACPI\\PNP0501", self.cfg)
        self.assertGreater(ch340, generic)

    def test_stlink_vcp_is_preferred(self):
        self.assertGreater(score_port("STMicroelectronics STLink Virtual COM Port", "", self.cfg), 0)


class TestConfigResilience(unittest.TestCase):
    def test_missing_path_falls_back_to_autodetect(self):
        cfg = AutoDebugConfig._section(
            type(AutoDebugConfig().keil), {"uv4_path": r"Z:\definitely\missing\UV4.exe"}, "keil")
        self.assertNotEqual(cfg.uv4_path, r"Z:\definitely\missing\UV4.exe")

    def test_unknown_keys_do_not_wipe_the_section(self):
        section = AutoDebugConfig._section(
            SerialConfig, {"baudrate": 9600, "totally_unknown": 1}, "serial")
        self.assertEqual(section.baudrate, 9600)

    def test_defaults_load_without_a_file(self):
        cfg = AutoDebugConfig.load(os.path.join(os.path.dirname(__file__), "no_such.yaml"))
        self.assertEqual(cfg.serial.baudrate, 115200)
        self.assertGreaterEqual(cfg.test.max_repair_iterations, 1)

    def test_shipped_yaml_parses_into_every_section(self):
        packaged = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "autodebug", "config.yaml")
        cfg = AutoDebugConfig.load(packaged)
        self.assertIn("[AUTODEBUG_CRASH_START]", cfg.test.fail_keywords)
        self.assertTrue(cfg.build.fail_on_stale_axf)
        self.assertEqual(cfg.loop.archive_dir, ".autodebug")


if __name__ == "__main__":
    unittest.main(verbosity=2)
