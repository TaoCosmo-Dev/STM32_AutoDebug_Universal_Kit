"""
Serial Port Monitor & Test Output / Assertion Parser.
Captures live UART logs, assertion failures, and test status from STM32 target.
"""
from dataclasses import dataclass
import re
import threading
import time
from typing import Callable, List, Optional
import serial


@dataclass
class SerialTestResult:
    passed: bool
    timed_out: bool
    raw_output: str
    assertion_error: Optional[str] = None
    assert_file: Optional[str] = None
    assert_line: Optional[int] = None
    backtrace_addresses: List[int] = None


class SerialMonitor:
    def __init__(self, port: Optional[str] = None, baudrate: int = 115200, timeout_seconds: float = 10.0):
        self.port = port or self._auto_detect_port()
        self.baudrate = baudrate
        self.timeout_seconds = timeout_seconds
        self._buffer: List[str] = []
        self._is_running = False

    @staticmethod
    def _auto_detect_port() -> str:
        try:
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
            if not ports:
                return "COM3"
            for p in ports:
                desc = (p.description or "").lower()
                hwid = (p.hwid or "").lower()
                if any(k in desc or k in hwid for k in ["ch340", "cp210", "ft232", "dap", "stlink", "cmsis", "usb-serial", "serial"]):
                    return p.device
            return ports[0].device
        except Exception:
            return "COM3"

    def capture_run(self,
                    pass_keywords: Optional[List[str]] = None,
                    fail_keywords: Optional[List[str]] = None,
                    on_line_cb: Optional[Callable[[str], None]] = None) -> SerialTestResult:
        if pass_keywords is None:
            pass_keywords = ["[ALL TESTS PASSED]", "TESTS_PASSED", "PASS:"]
        if fail_keywords is None:
            fail_keywords = ["[TEST FAILED]", "ASSERTION_FAILED", "FAIL:"]

        self._buffer.clear()
        passed = False
        timed_out = False
        assertion_error = None
        assert_file = None
        assert_line = None
        backtrace_addrs = []

        # Regular expressions for assertions
        # standard assert: Assertion failed: (x != NULL), file main.c, line 42
        # STM32 HAL assert_param: Wrong parameters value: file main.c on line 42
        # CmBacktrace format: [Backtrace] >> 0x08001234 0x08005678
        assert_regex1 = re.compile(r'Assertion\s+failed:\s*(.+?),\s*file\s+([^,\n\r]+),\s*line\s+(\d+)', re.IGNORECASE)
        assert_regex2 = re.compile(r'(?:assert_param|assertion)\s*(?:error|failed)?.*?file\s+([^,\n\r]+).*?line\s+(\d+)', re.IGNORECASE)
        bt_regex = re.compile(r'0x[0-9a-fA-F]{8}')

        start_time = time.time()
        ser = None
        try:
            ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
            ser.reset_input_buffer()
        except Exception as e:
            # Serial port cannot be opened (e.g. no physical device plugged in)
            return SerialTestResult(
                passed=False,
                timed_out=False,
                raw_output=f"Failed to open serial port {self.port}: {e}",
                assertion_error=None
            )

        try:
            while time.time() - start_time < self.timeout_seconds:
                line_bytes = ser.readline()
                if not line_bytes:
                    continue

                line = line_bytes.decode("utf-8", errors="replace").strip()
                if line:
                    self._buffer.append(line)
                    if on_line_cb:
                        on_line_cb(line)

                    # Check for assertion match
                    m1 = assert_regex1.search(line)
                    if m1:
                        assertion_error = m1.group(1).strip()
                        assert_file = m1.group(2).strip()
                        assert_line = int(m1.group(3))

                    m2 = assert_regex2.search(line)
                    if m2 and not assert_file:
                        assert_file = m2.group(1).strip()
                        assert_line = int(m2.group(2))
                        assertion_error = line

                    # Check for backtrace hex addresses
                    if "backtrace" in line.lower():
                        addrs = bt_regex.findall(line)
                        for a in addrs:
                            backtrace_addrs.append(int(a, 16))

                    # Check pass condition
                    if any(pk in line for pk in pass_keywords):
                        passed = True
                        break

                    # Check fail condition
                    if any(fk in line for fk in fail_keywords):
                        passed = False
                        break
            else:
                timed_out = True
        finally:
            if ser and ser.is_open:
                ser.close()

        raw_output = "\n".join(self._buffer)
        return SerialTestResult(
            passed=passed,
            timed_out=timed_out,
            raw_output=raw_output,
            assertion_error=assertion_error,
            assert_file=assert_file,
            assert_line=assert_line,
            backtrace_addresses=backtrace_addrs if backtrace_addrs else None
        )
