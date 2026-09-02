"""
Hardware debug probe controller (pyOCD primary, J-Link fallback).

Two properties matter for an unattended loop and both are enforced here:

  1. Zero interaction. Every pyOCD entry point is called with blocking=False and an
     explicitly resolved probe id, so a second probe on the desk can never pop the
     "choose a probe" prompt that would hang the pipeline forever.

  2. One session for the whole run. Reconnecting between flash and fault-read would
     re-run connect_mode (under-reset) and wipe the very CFSR/BFAR registers we came
     to read. The session is opened once and reused.
"""
from dataclasses import dataclass, field
import os
import struct
import subprocess
import sys
import time
from typing import List, Optional, Tuple

from .config import DebuggerConfig, list_connected_probes

# System Control Block fault registers
SCB_SHCSR = 0xE000ED24
SCB_CFSR = 0xE000ED28
SCB_HFSR = 0xE000ED2C
SCB_DFSR = 0xE000ED30
SCB_MMFAR = 0xE000ED34
SCB_BFAR = 0xE000ED38

CFSR_MMARVALID = 1 << 7
CFSR_BFARVALID = 1 << 15


@dataclass
class TargetCoreState:
    is_halted: bool
    pc: int = 0
    lr: int = 0
    sp: int = 0
    msp: int = 0
    psp: int = 0
    xpsr: int = 0
    ipsr: int = 0
    control: int = 0
    r0: int = 0
    r1: int = 0
    r2: int = 0
    r3: int = 0
    r12: int = 0
    cfsr: int = 0
    hfsr: int = 0
    bfar: int = 0
    mmfar: int = 0
    bfar_valid: bool = False
    mmfar_valid: bool = False
    frame_sp: int = 0            # stack address the exception frame was found at
    frame_is_psp: bool = False
    stack_bytes: bytes = b""     # 32 bytes of the exception frame (or b"")
    stack_dump: bytes = b""      # wider raw dump around the stack pointer

    @property
    def faulted(self) -> bool:
        return self.cfsr != 0 or self.hfsr != 0


@dataclass
class FlashResult:
    success: bool
    message: str = ""
    halted: bool = False
    probe_id: Optional[str] = None
    target_name: Optional[str] = None


def _is_plausible_code_addr(addr: int) -> bool:
    """Cortex-M code lives in flash, SRAM, or the CCM/ITCM aliases."""
    if addr == 0 or addr & 1:
        return False
    return (0x00000000 < addr < 0x00200000 or      # boot alias / internal flash alias
            0x08000000 <= addr < 0x08200000 or     # STM32 internal flash
            0x10000000 <= addr < 0x10100000 or     # CCM
            0x1FFF0000 <= addr < 0x20000000 or     # system memory
            0x20000000 <= addr < 0x20100000)       # SRAM (RAM-executed code)


class HardwareProbe:
    """Unified hardware interface for CMSIS-DAP / ST-Link / J-Link."""

    def __init__(self, config: DebuggerConfig):
        self.config = config
        self._session = None
        self._probe_id: Optional[str] = None

    # ------------------------------------------------------------------ discovery

    @property
    def probe_available(self) -> bool:
        return bool(list_connected_probes()) or bool(self.config.probe_id)

    def describe_probes(self) -> List[str]:
        out = []
        for p in list_connected_probes():
            try:
                out.append(f"{p.description} [{p.unique_id}]")
            except Exception:
                out.append(str(p))
        return out

    def _resolve_probe_id(self) -> Optional[str]:
        if self._probe_id:
            return self._probe_id
        self._probe_id = self.config.resolve_probe_id()
        return self._probe_id

    # ------------------------------------------------------------------ session lifetime

    def _session_options(self) -> dict:
        return {
            "connect_mode": self.config.connect_mode,
            "frequency": self.config.frequency_hz,
            "resume_on_disconnect": False,   # we decide when the core runs
            "warning.cortex_m_default": False,
        }

    def open(self) -> bool:
        """Open one pyOCD session and keep it for the whole run. Never prompts."""
        if self._session is not None:
            return True
        if self.config.type == "jlink":
            return True  # pylink manages its own handle per call
        try:
            from pyocd.core.helpers import ConnectHelper
        except Exception as e:
            print(f"[probe] pyocd is not installed: {e}", file=sys.stderr)
            return False

        probe_uid = self._resolve_probe_id()
        if not probe_uid:
            print("[probe] no debug probe detected (CMSIS-DAP / ST-Link / DAPLink).", file=sys.stderr)
            return False

        try:
            session = ConnectHelper.session_with_chosen_probe(
                unique_id=probe_uid,
                target_override=self.config.target_override or "cortex_m",
                blocking=False,
                auto_unlock=True,
                options=self._session_options(),
            )
            if session is None:
                print(f"[probe] could not open a session on probe {probe_uid}.", file=sys.stderr)
                return False
            session.open()
            self._session = session
            return True
        except Exception as e:
            print(f"[probe] session open failed: {e}", file=sys.stderr)
            return False

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    def __enter__(self) -> "HardwareProbe":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def target(self):
        return self._session.target if self._session is not None else None

    # ------------------------------------------------------------------ flash

    def flash(self, binary_path: str, halt_after: bool = True) -> FlashResult:
        """Program the image and leave the core HALTED at the reset vector by default.

        Halting after flash is what removes the boot-output race: the caller opens the
        serial port while the CPU is frozen, then calls resume(), so not one byte of the
        firmware's startup banner is lost.
        """
        if not binary_path or not os.path.exists(binary_path):
            return FlashResult(False, f"Image not found: {binary_path}")

        if self.config.type == "jlink":
            return self._flash_jlink(binary_path, halt_after)
        return self._flash_pyocd(binary_path, halt_after)

    def _flash_pyocd(self, binary_path: str, halt_after: bool) -> FlashResult:
        probe_uid = self._resolve_probe_id()
        target_type = self.config.target_override or "cortex_m"

        if not self.open():
            return self._flash_pyocd_cli(binary_path, probe_uid, target_type)

        try:
            from pyocd.flash.file_programmer import FileProgrammer
            programmer = FileProgrammer(self._session)
            programmer.program(binary_path)
            target = self._session.target
            target.reset_and_halt()
            if not halt_after:
                target.resume()
            return FlashResult(True, "programmed", halted=halt_after,
                               probe_id=probe_uid, target_name=target_type)
        except Exception as e:
            self.close()
            cli = self._flash_pyocd_cli(binary_path, probe_uid, target_type)
            if not cli.success:
                cli.message = f"pyocd API failed ({e}); CLI fallback failed ({cli.message})"
            return cli

    def _flash_pyocd_cli(self, binary_path: str, probe_uid: Optional[str],
                         target_type: str) -> FlashResult:
        """Last-resort CLI flash. Always passes -u so it can never prompt."""
        cmd = [sys.executable, "-m", "pyocd", "flash", "-t", target_type]
        if probe_uid:
            cmd.extend(["-u", probe_uid])
        cmd.append(binary_path)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            ok = res.returncode == 0
            msg = (res.stderr or res.stdout or "").strip()[-400:]
            # The CLI resets and runs; we cannot hold the core halted through it.
            return FlashResult(ok, msg or "pyocd CLI flash", halted=False,
                               probe_id=probe_uid, target_name=target_type)
        except Exception as e:
            return FlashResult(False, f"pyocd CLI flash failed: {e}")

    def _flash_jlink(self, binary_path: str, halt_after: bool) -> FlashResult:
        try:
            import pylink
        except Exception as e:
            return FlashResult(False, f"pylink-square not installed: {e}")
        try:
            jlink = pylink.JLink()
            jlink.open(serial_no=self._resolve_probe_id())
            jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
            jlink.connect(self.config.target_override or "Cortex-M4")
            jlink.flash_file(binary_path, self.config.flash_address)
            jlink.reset(halt=halt_after)
            jlink.close()
            return FlashResult(True, "programmed via J-Link", halted=halt_after,
                               target_name=self.config.target_override)
        except Exception as e:
            return FlashResult(False, f"J-Link flash failed: {e}")

    # ------------------------------------------------------------------ run control

    def resume(self) -> bool:
        """Release a halted core. Called right after the serial monitor is listening."""
        if self.config.type == "jlink":
            try:
                import pylink
                jlink = pylink.JLink()
                jlink.open(serial_no=self._resolve_probe_id())
                jlink.connect(self.config.target_override or "Cortex-M4")
                jlink.restart()
                jlink.close()
                return True
            except Exception:
                return False
        if not self.open():
            return False
        try:
            if self._session.target.is_halted():
                self._session.target.resume()
            return True
        except Exception as e:
            print(f"[probe] resume failed: {e}", file=sys.stderr)
            return False

    def reset_and_run(self) -> bool:
        if not self.open():
            return False
        try:
            self._session.target.reset_and_halt()
            self._session.target.resume()
            return True
        except Exception:
            return False

    def is_target_running(self, sample_gap: float = 0.05) -> Optional[bool]:
        """CPU liveness telemetry: sample the PC twice without halting the core.

        Returns True (PC advanced), False (halted or stuck at one address), or None
        when the probe cannot answer.
        """
        if not self.open():
            return None
        try:
            target = self._session.target
            if target.is_halted():
                return False
            pc1 = target.read_core_register("pc")
            time.sleep(sample_gap)
            pc2 = target.read_core_register("pc")
            return pc1 != pc2
        except Exception:
            return None

    # ------------------------------------------------------------------ fault telemetry

    def _find_exception_frame(self, target, msp: int, psp: int) -> Tuple[int, bool, bytes]:
        """Locate the 8-word exception frame pushed by the core.

        The handler that trapped the fault has usually pushed its own registers, so the
        frame is not necessarily at the current SP. Both stacks are scanned for the
        signature of a real frame (thumb bit set in the stacked xPSR and a stacked PC
        that points at executable memory).
        """
        for sp_base, is_psp in ((msp, False), (psp, True)):
            if not sp_base or sp_base < 0x20000000:
                continue
            try:
                blob = bytes(target.read_memory_block8(sp_base, 256))
            except Exception:
                continue
            for off in range(0, len(blob) - 32 + 1, 4):
                words = struct.unpack_from("<8I", blob, off)
                stacked_pc, stacked_xpsr = words[6], words[7]
                if (stacked_xpsr & (1 << 24)) and _is_plausible_code_addr(stacked_pc):
                    return sp_base + off, is_psp, blob[off:off + 32]
        # Nothing convincing: hand back the raw top of MSP so the report is not empty.
        try:
            return msp, False, bytes(target.read_memory_block8(msp, 32))
        except Exception:
            return msp, False, b""

    def read_fault_registers(self, halt_if_running: bool = True) -> Optional[TargetCoreState]:
        """Read core + SCB fault registers from the (already open) session."""
        if not self.open():
            return None
        try:
            target = self._session.target
            if not target.is_halted():
                if not halt_if_running:
                    return None
                target.halt()

            def reg(name: str) -> int:
                try:
                    return int(target.read_core_register(name)) & 0xFFFFFFFF
                except Exception:
                    return 0

            pc, lr, sp = reg("pc"), reg("lr"), reg("sp")
            msp, psp, xpsr = reg("msp"), reg("psp"), reg("xpsr")
            control = reg("control")

            cfsr = target.read32(SCB_CFSR)
            hfsr = target.read32(SCB_HFSR)
            mmfar = target.read32(SCB_MMFAR)
            bfar = target.read32(SCB_BFAR)

            frame_sp, frame_is_psp, frame_bytes = self._find_exception_frame(target, msp, psp)

            stack_dump = b""
            try:
                stack_dump = bytes(target.read_memory_block8(frame_sp, 128))
            except Exception:
                pass

            return TargetCoreState(
                is_halted=True, pc=pc, lr=lr, sp=sp, msp=msp, psp=psp,
                xpsr=xpsr, ipsr=xpsr & 0x1FF, control=control,
                r0=reg("r0"), r1=reg("r1"), r2=reg("r2"), r3=reg("r3"), r12=reg("r12"),
                cfsr=cfsr, hfsr=hfsr, bfar=bfar, mmfar=mmfar,
                bfar_valid=bool(cfsr & CFSR_BFARVALID),
                mmfar_valid=bool(cfsr & CFSR_MMARVALID),
                frame_sp=frame_sp, frame_is_psp=frame_is_psp,
                stack_bytes=frame_bytes, stack_dump=stack_dump,
            )
        except Exception as e:
            print(f"[probe] reading fault registers failed: {e}", file=sys.stderr)
            return None

    def clear_fault_registers(self) -> bool:
        """CFSR/HFSR bits are write-1-to-clear and survive a warm reset: clear before a run
        so the next diagnosis cannot inherit the previous iteration's crash."""
        if not self.open():
            return False
        try:
            target = self._session.target
            target.write32(SCB_CFSR, 0xFFFFFFFF)
            target.write32(SCB_HFSR, 0xFFFFFFFF)
            return True
        except Exception:
            return False
