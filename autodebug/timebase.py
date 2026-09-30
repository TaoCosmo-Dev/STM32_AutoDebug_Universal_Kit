"""
Timebase self-check: is the firmware's millisecond actually a millisecond?

A pass token proves the tests ran, not that time runs at the right speed. A SysTick
clocked from HCLK/8 while its reload value was computed for HCLK -- one stray
`configSYSTICK_CLOCK_HZ` in FreeRTOSConfig.h does exactly this -- stretches every delay
eightfold, and the firmware still prints its token. The loop already holds an open SWD
session and the image's symbol table, so it reads the tick counter twice and compares
the count against the host clock.

Memory reads go through the AHB access port and never halt the core, so the check does
not disturb the timing it measures. Everything here takes the reader and the clock as
arguments, which keeps it testable without a board.
"""
from dataclasses import dataclass
import os
import re
import time
from typing import Callable, Dict, List, Optional

SYST_CSR = 0xE000E010          # bit 2 CLKSOURCE: 1 = processor clock, 0 = external (HCLK/8 on STM32)
SYST_RVR = 0xE000E014

# HAL_TickFreqTypeDef: the enum value is the tick period in ms.
_HAL_TICK_FREQ_HZ = {1: 1000.0, 10: 100.0, 100: 10.0}

# Fewer ticks than this in the window and a one-tick quantisation error alone could
# exceed the tolerance; the window is stretched (up to a cap) to collect enough.
_MIN_TICKS = 50
_MAX_WINDOW_S = 2.0

Reader = Callable[[int, int], Optional[int]]          # (address, width_bits) -> value
SymbolLookup = Callable[[str], Optional[int]]


@dataclass
class TickCounter:
    name: str
    address: int
    expected_hz: float


@dataclass
class TimebaseFinding:
    name: str
    measured_hz: float
    expected_hz: float
    ticks: int
    seconds: float

    @property
    def ratio(self) -> float:
        return self.measured_hz / self.expected_hz if self.expected_hz else 0.0


def freertos_settings(source_root: Optional[str]) -> Dict[str, int]:
    """configTICK_RATE_HZ / configUSE_TICKLESS_IDLE from the project's FreeRTOSConfig.h."""
    if not source_root or not os.path.isdir(source_root):
        return {}
    for root, dirs, files in os.walk(source_root):
        dirs[:] = [d for d in dirs if d.lower() not in (".git", ".autodebug", "objects", "listings")]
        if "FreeRTOSConfig.h" not in files:
            continue
        try:
            with open(os.path.join(root, "FreeRTOSConfig.h"), encoding="utf-8",
                      errors="replace") as f:
                text = f.read()
        except OSError:
            return {}
        text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
        out: Dict[str, int] = {}
        for key, name in (("tick_rate", "configTICK_RATE_HZ"),
                          ("tickless", "configUSE_TICKLESS_IDLE")):
            # The last definition wins, as for the preprocessor after an #undef.
            values = re.findall(r"#\s*define\s+" + name + r"\s+([^\n]+)", text)
            numbers = re.findall(r"\d+", values[-1]) if values else []
            if numbers:
                out[key] = int(numbers[-1])
        return out
    return {}


def find_counters(symbol: SymbolLookup, read: Reader,
                  source_root: Optional[str] = None) -> List[TickCounter]:
    """The tick counters this image has, each with the rate it is supposed to run at."""
    counters: List[TickCounter] = []

    addr = symbol("uwTick")                         # HAL's 1 ms tick
    if addr:
        freq_addr = symbol("uwTickFreq")
        raw = read(freq_addr, 8) if freq_addr else None
        counters.append(TickCounter("uwTick", addr, _HAL_TICK_FREQ_HZ.get(raw, 1000.0)))

    addr = symbol("xTickCount")                     # FreeRTOS kernel tick
    if addr:
        rtos = freertos_settings(source_root)
        # Tickless idle advances the count in jumps on wake-up; a short window would
        # read that as skew. Unknown tick rate: nothing to compare against.
        if rtos.get("tick_rate") and not rtos.get("tickless"):
            counters.append(TickCounter("xTickCount", addr, float(rtos["tick_rate"])))
    return counters


def measure(counters: List[TickCounter], read: Reader, window_s: float,
            clock: Callable[[], float] = time.perf_counter,
            sleep: Callable[[float], None] = time.sleep) -> List[TimebaseFinding]:
    """Sample every counter twice, `window_s` apart (stretched for slow ticks)."""
    if not counters:
        return []
    slowest = min(c.expected_hz for c in counters)
    if slowest > 0:
        window_s = min(max(window_s, _MIN_TICKS / slowest), _MAX_WINDOW_S)

    def snapshot():
        t0 = clock()
        values = [read(c.address, 32) for c in counters]
        t1 = clock()
        return (t0 + t1) / 2.0, values          # USB latency halves out at the midpoint

    ta, first = snapshot()
    sleep(window_s)
    tb, second = snapshot()
    elapsed = tb - ta

    findings: List[TimebaseFinding] = []
    for c, a, b in zip(counters, first, second):
        if a is None or b is None or elapsed <= 0:
            continue
        ticks = (b - a) & 0xFFFFFFFF
        findings.append(TimebaseFinding(c.name, ticks / elapsed, c.expected_hz, ticks, elapsed))
    return findings


def skewed(findings: List[TimebaseFinding], tolerance: float) -> List[TimebaseFinding]:
    """Counters running measurably too fast or too slow.

    A counter that did not move at all is not reported: firmware may legitimately park
    with interrupts off once its tests are done, and a false failure on a passing board
    would cost more than this check saves.
    """
    return [f for f in findings if f.ticks > 0 and abs(f.ratio - 1.0) > tolerance]


def systick_context(read: Reader, symbol: SymbolLookup) -> Dict[str, object]:
    """SysTick registers and SystemCoreClock, plus the rate they imply."""
    ctx: Dict[str, object] = {}
    csr = read(SYST_CSR, 32)
    rvr = read(SYST_RVR, 32)
    addr = symbol("SystemCoreClock")
    core = read(addr, 32) if addr else None
    if csr is not None:
        ctx["SYST_CSR"] = f"0x{csr:08X}"
        ctx["clock_source"] = "HCLK" if csr & 0x4 else "HCLK/8"
    if rvr is not None:
        ctx["SYST_RVR"] = rvr & 0xFFFFFF
    if core:
        ctx["SystemCoreClock"] = core
    if csr is not None and rvr is not None and core:
        source = core if csr & 0x4 else core / 8.0
        ctx["systick_hz_from_registers"] = round(source / ((rvr & 0xFFFFFF) + 1), 1)
    return ctx
