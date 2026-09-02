"""
Serial monitor, test-token watcher, assertion parser and on-target crash decoder.

The monitor is deliberately split into open() / wait_for_result() / close(). The engine
opens the port while the CPU is still halted after flashing and only then resumes it, so
the firmware's very first banner line cannot be missed. A background reader thread drains
the port continuously, so nothing is lost while the caller is busy.
"""
from dataclasses import dataclass, field
import re
import sys
import threading
import time
from typing import Callable, List, Optional

import serial
import serial.tools.list_ports

from .config import SerialConfig


# --------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------

@dataclass
class CrashTelemetry:
    """Fault state the firmware itself printed over UART (cm_backtrace_lite)."""
    registers: dict = field(default_factory=dict)   # upper-case name -> int
    backtrace: List[int] = field(default_factory=list)
    active_sp: str = "MSP"
    raw_block: str = ""

    def get(self, name: str, default: int = 0) -> int:
        return self.registers.get(name.upper(), default)


@dataclass
class SerialTestResult:
    passed: bool
    timed_out: bool
    raw_output: str
    port: Optional[str] = None
    opened: bool = True
    open_error: Optional[str] = None
    matched_keyword: Optional[str] = None
    assertion_error: Optional[str] = None
    assert_file: Optional[str] = None
    assert_line: Optional[int] = None
    crash: Optional[CrashTelemetry] = None

    def signature(self) -> str:
        """Stable identity of a runtime failure, for stall detection."""
        if self.assert_file:
            return f"ASSERT|{self.assert_file}:{self.assert_line}|{(self.assertion_error or '')[:60]}"
        if self.crash:
            return (f"CRASH|PC=0x{self.crash.get('PC'):08X}|"
                    f"CFSR=0x{self.crash.get('CFSR'):08X}")
        if not self.opened:
            return f"SERIAL_UNAVAILABLE|{self.open_error}"
        if self.timed_out:
            return "TIMEOUT|no pass token"
        return f"FAIL|{self.matched_keyword}"


# --------------------------------------------------------------------------------------
# Pure parsers (unit-testable without hardware)
# --------------------------------------------------------------------------------------

_HEX_KV = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*0x([0-9A-Fa-f]+)")
_BT_LINE = re.compile(r"\[Backtrace\][^\n\r]*", re.IGNORECASE)
_HEX_ADDR = re.compile(r"0x([0-9A-Fa-f]{8})")

# "Assertion failed: (x != NULL), file main.c, line 42"
_ASSERT_C99 = re.compile(
    r"Assertion\s+failed:\s*(.+?),\s*file\s+([^,\n\r]+),\s*line\s+(\d+)", re.IGNORECASE)
# "[ASSERTION_FAILED] x != NULL at file main.c, line 42"   (cm_backtrace_lite)
_ASSERT_KIT = re.compile(
    r"\[ASSERTION_FAILED\]\s*(.*?)\s*at\s+file\s+([^,\n\r]+),\s*line\s+(\d+)", re.IGNORECASE)
# HAL assert_param: "Wrong parameters value: file main.c on line 42"
_ASSERT_HAL = re.compile(
    r"Wrong\s+parameters?\s+value:\s*file\s+([^\s]+)\s+on\s+line\s+(\d+)", re.IGNORECASE)


def parse_crash_block(text: str,
                      begin_marker: str = "[AUTODEBUG_CRASH_START]",
                      end_marker: str = "[AUTODEBUG_CRASH_END]") -> Optional[CrashTelemetry]:
    """Decode the register dump the firmware printed between the crash markers."""
    start = text.find(begin_marker)
    if start < 0:
        return None
    end = text.find(end_marker, start)
    block = text[start:end + len(end_marker)] if end >= 0 else text[start:]

    regs = {}
    for name, value in _HEX_KV.findall(block):
        try:
            regs[name.upper()] = int(value, 16)
        except ValueError:
            continue
    if not regs:
        return None

    backtrace: List[int] = []
    for bt_line in _BT_LINE.findall(block):
        backtrace.extend(int(a, 16) for a in _HEX_ADDR.findall(bt_line))

    active_sp = "PSP" if re.search(r"\(PSP\)", block) else "MSP"
    return CrashTelemetry(registers=regs, backtrace=backtrace,
                          active_sp=active_sp, raw_block=block.strip())


def parse_assertion(line: str):
    """Return (expression, file, line) for any supported assert format, else None."""
    m = _ASSERT_KIT.search(line)
    if m:
        return m.group(1).strip() or "assertion failed", m.group(2).strip(), int(m.group(3))
    m = _ASSERT_C99.search(line)
    if m:
        return m.group(1).strip(), m.group(2).strip(), int(m.group(3))
    m = _ASSERT_HAL.search(line)
    if m:
        return "HAL assert_param failed", m.group(1).strip(), int(m.group(2))
    return None


def score_port(description: str, hwid: str, cfg: SerialConfig) -> int:
    """Rank a COM port as a firmware log source. Higher is better; <0 means never pick."""
    blob = f"{description} {hwid}".lower()
    for bad in cfg.exclude_keywords:
        if bad.lower() in blob:
            return -1
    score = 0
    for i, good in enumerate(cfg.prefer_keywords):
        if good.lower() in blob:
            score = max(score, len(cfg.prefer_keywords) - i)
    if "usb" in blob:
        score += 1
    return score


def auto_detect_port(cfg: Optional[SerialConfig] = None) -> Optional[str]:
    """Pick the most likely USB-UART port. Returns None when there is nothing to pick."""
    cfg = cfg or SerialConfig()
    try:
        ports = list(serial.tools.list_ports.comports())
    except Exception:
        return None
    if not ports:
        return None
    ranked = []
    for p in ports:
        s = score_port(p.description or "", p.hwid or "", cfg)
        if s >= 0:
            ranked.append((s, p.device))
    if not ranked:
        return None
    ranked.sort(key=lambda t: (-t[0], t[1]))
    return ranked[0][1]


# --------------------------------------------------------------------------------------
# Monitor
# --------------------------------------------------------------------------------------

class SerialMonitor:
    def __init__(self, config: Optional[SerialConfig] = None,
                 port: Optional[str] = None,
                 baudrate: Optional[int] = None,
                 timeout_seconds: Optional[float] = None):
        self.cfg = config or SerialConfig()
        if port is not None:
            self.cfg.port = port
        if baudrate is not None:
            self.cfg.baudrate = baudrate
        if timeout_seconds is not None:
            self.cfg.timeout_seconds = timeout_seconds

        self.port: Optional[str] = None
        self._ser: Optional[serial.Serial] = None
        self._lines: List[str] = []
        self._pending = b""
        self._lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.open_error: Optional[str] = None

    # ---------------------------------------------------------------- lifetime

    def open(self) -> bool:
        """Open the port and start draining it. Call this BEFORE the CPU is resumed."""
        self.close()
        self._stop.clear()
        self._lines = []
        self._pending = b""
        self.open_error = None

        # Re-detect every run: a board that re-enumerates over USB can change COM number.
        self.port = self.cfg.port or auto_detect_port(self.cfg)
        if not self.port:
            self.open_error = "no serial port found (is the USB-UART bridge plugged in?)"
            return False

        try:
            self._ser = serial.Serial(self.port, self.cfg.baudrate, timeout=0.05)
        except Exception as e:
            self.open_error = f"cannot open {self.port}: {e}"
            self._ser = None
            return False

        self._reader = threading.Thread(target=self._read_loop, name="autodebug-serial", daemon=True)
        self._reader.start()
        return True

    def close(self) -> None:
        self._stop.set()
        if self._reader is not None:
            self._reader.join(timeout=2.0)
            self._reader = None
        if self._ser is not None:
            try:
                if self._ser.is_open:
                    self._ser.close()
            except Exception:
                pass
            self._ser = None

    def __enter__(self) -> "SerialMonitor":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------------------------------------------------------- reading

    def _read_loop(self) -> None:
        while not self._stop.is_set() and self._ser is not None:
            try:
                chunk = self._ser.read(4096) or b""
                if not chunk:
                    continue
            except Exception:
                break
            with self._lock:
                self._pending += chunk
                *complete, self._pending = self._pending.split(b"\n")
                for raw in complete:
                    text = raw.decode("utf-8", errors="replace").replace("\r", "").rstrip()
                    if text:
                        self._lines.append(text)

    def _drain_new(self, cursor: int) -> List[str]:
        with self._lock:
            return self._lines[cursor:]

    def _flush_partial(self) -> None:
        """Promote a trailing line that never got its newline (common on a crash dump)."""
        with self._lock:
            if self._pending:
                text = self._pending.decode("utf-8", errors="replace").replace("\r", "").rstrip()
                if text:
                    self._lines.append(text)
                self._pending = b""

    # ---------------------------------------------------------------- test window

    def wait_for_result(self,
                        pass_keywords: List[str],
                        fail_keywords: List[str],
                        timeout_seconds: Optional[float] = None,
                        on_line_cb: Optional[Callable[[str], None]] = None,
                        crash_begin: str = "[AUTODEBUG_CRASH_START]",
                        crash_end: str = "[AUTODEBUG_CRASH_END]") -> SerialTestResult:
        """Watch the already-open port until a verdict token, a crash block, or timeout."""
        if self._ser is None:
            return SerialTestResult(passed=False, timed_out=False, raw_output="",
                                    port=self.port, opened=False, open_error=self.open_error)

        timeout = self.cfg.timeout_seconds if timeout_seconds is None else timeout_seconds
        deadline = time.time() + timeout
        cursor = 0
        passed = False
        matched = None
        assertion_error = assert_file = None
        assert_line = None
        saw_crash_begin = False
        verdict = False

        while time.time() < deadline and not verdict:
            new_lines = self._drain_new(cursor)
            if not new_lines:
                time.sleep(0.02)
                continue
            cursor += len(new_lines)

            for line in new_lines:
                if on_line_cb:
                    on_line_cb(line)

                parsed = parse_assertion(line)
                if parsed and not assert_file:
                    assertion_error, assert_file, assert_line = parsed

                if crash_begin in line:
                    saw_crash_begin = True
                    continue  # keep reading until the block is complete
                if saw_crash_begin:
                    if crash_end in line:
                        verdict = True
                        matched = crash_begin
                        break
                    continue

                if any(pk in line for pk in pass_keywords):
                    passed, matched, verdict = True, next(pk for pk in pass_keywords if pk in line), True
                    break
                if any(fk in line for fk in fail_keywords):
                    passed, matched, verdict = False, next(fk for fk in fail_keywords if fk in line), True
                    break

        # Give a crash dump that started right at the deadline a moment to finish.
        if saw_crash_begin and not verdict:
            time.sleep(0.3)
        self._flush_partial()
        with self._lock:
            raw_output = "\n".join(self._lines)

        crash = parse_crash_block(raw_output, crash_begin, crash_end)
        if crash and not assert_file:
            matched = matched or crash_begin

        return SerialTestResult(
            passed=passed,
            timed_out=not verdict and not crash,
            raw_output=raw_output,
            port=self.port,
            opened=True,
            matched_keyword=matched,
            assertion_error=assertion_error,
            assert_file=assert_file,
            assert_line=assert_line,
            crash=crash,
        )

    # ---------------------------------------------------------------- convenience

    def capture_run(self,
                    pass_keywords: Optional[List[str]] = None,
                    fail_keywords: Optional[List[str]] = None,
                    on_line_cb: Optional[Callable[[str], None]] = None) -> SerialTestResult:
        """One-shot open + watch + close, for callers that do not control the CPU."""
        opened = self.open()
        if not opened:
            return SerialTestResult(passed=False, timed_out=False,
                                    raw_output=self.open_error or "",
                                    port=self.port, opened=False, open_error=self.open_error)
        try:
            return self.wait_for_result(
                pass_keywords or ["[ALL TESTS PASSED]", "TESTS_PASSED", "[PASS]"],
                fail_keywords or ["[TEST FAILED]", "ASSERTION_FAILED", "[AUTODEBUG_CRASH_START]"],
                on_line_cb=on_line_cb)
        finally:
            self.close()

    @staticmethod
    def describe_ports() -> List[str]:
        try:
            return [f"{p.device} - {p.description}" for p in serial.tools.list_ports.comports()]
        except Exception as e:
            print(f"[serial] port enumeration failed: {e}", file=sys.stderr)
            return []
