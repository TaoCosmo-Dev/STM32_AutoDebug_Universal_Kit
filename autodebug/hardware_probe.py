"""
Hardware Debug Probe Controller (PyOCD, J-Link, and GDB Server Bridge).
Provides unified flash, run, halt, register read, and SCB exception inspection.
"""
from dataclasses import dataclass
import os
import subprocess
import time
from typing import Dict, List, Optional, Tuple
from .config import DebuggerConfig


@dataclass
class TargetCoreState:
    is_halted: bool
    pc: int = 0
    lr: int = 0
    sp: int = 0
    msp: int = 0
    psp: int = 0
    xpsr: int = 0
    r0: int = 0
    r1: int = 0
    r2: int = 0
    r3: int = 0
    r12: int = 0
    cfsr: int = 0
    hfsr: int = 0
    bfar: int = 0
    mmfar: int = 0
    stack_bytes: bytes = b""


class HardwareProbe:
    """Unified hardware interface for ST-Link and J-Link."""

    def __init__(self, config: DebuggerConfig):
        self.config = config

    @property
    def probe_available(self) -> bool:
        try:
            from pyocd.core.helpers import ConnectHelper
            probes = ConnectHelper.get_all_connected_probes(blocking=False)
            return len(probes) > 0
        except Exception:
            return bool(self.config.probe_id)

    def flash(self, binary_path: str) -> bool:
        """Flashes .axf/.elf or .hex/.bin into target MCU."""
        binary_path = os.path.abspath(binary_path)
        if not os.path.exists(binary_path):
            raise FileNotFoundError(f"Binary file not found: {binary_path}")

        # Method 1: PyOCD (Preferred for universal ST-Link & J-Link support)
        if self.config.type == "pyocd":
            return self._flash_pyocd(binary_path)
        elif self.config.type == "jlink":
            return self._flash_jlink(binary_path)
        else:
            return self._flash_pyocd(binary_path)

    def _flash_pyocd(self, binary_path: str) -> bool:
        try:
            from pyocd.core.helpers import ConnectHelper
            from pyocd.flash.file_programmer import FileProgrammer

            target_type = self.config.target_override or "stm32f407zg"
            session = ConnectHelper.session_with_chosen_probe(
                target_override=target_type,
                unique_id=self.config.probe_id,
                auto_unlock=True
            )
            if session is None:
                return False

            with session:
                programmer = FileProgrammer(session)
                programmer.program(binary_path)
                session.target.reset_and_halt()
                session.target.resume()
            return True
        except Exception as e:
            # Fallback to pyocd CLI
            try:
                cmd = ["pyocd", "flash", "-t", self.config.target_override or "stm32f407zg", binary_path]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                return res.returncode == 0
            except Exception:
                return False

    def _flash_jlink(self, binary_path: str) -> bool:
        try:
            import pylink
            jlink = pylink.JLink()
            jlink.open(serial_no=self.config.probe_id)
            jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
            jlink.connect(self.config.target_override or "STM32F407ZG")
            jlink.flash_file(binary_path, 0x08000000)
            jlink.reset(halt=False)
            jlink.close()
            return True
        except Exception:
            return False

    def read_fault_registers(self) -> Optional[TargetCoreState]:
        """Halts target if not already halted, reads core registers and SCB fault registers."""
        try:
            from pyocd.core.helpers import ConnectHelper
            session = ConnectHelper.session_with_chosen_probe(
                target_override=self.config.target_override or "stm32f407zg",
                unique_id=self.config.probe_id
            )
            if not session:
                return None

            with session:
                target = session.target
                if not target.is_halted():
                    target.halt()

                # Read Core Registers
                r0 = target.read_core_register("r0")
                r1 = target.read_core_register("r1")
                r2 = target.read_core_register("r2")
                r3 = target.read_core_register("r3")
                r12 = target.read_core_register("r12")
                sp = target.read_core_register("sp")
                lr = target.read_core_register("lr")
                pc = target.read_core_register("pc")
                xpsr = target.read_core_register("xpsr")
                msp = target.read_core_register("msp")
                psp = target.read_core_register("psp")

                # Read SCB Fault Status Registers (0xE000ED28+)
                cfsr = target.read32(0xE000ED28)
                hfsr = target.read32(0xE000ED2C)
                mmfar = target.read32(0xE000ED34)
                bfar = target.read32(0xE000ED38)

                # Read Stack Bytes (top 64 bytes from SP)
                stack_bytes = b""
                try:
                    stack_data = target.read_memory_block8(sp, 64)
                    stack_bytes = bytes(stack_data)
                except Exception:
                    pass

                return TargetCoreState(
                    is_halted=True,
                    pc=pc,
                    lr=lr,
                    sp=sp,
                    msp=msp,
                    psp=psp,
                    xpsr=xpsr,
                    r0=r0,
                    r1=r1,
                    r2=r2,
                    r3=r3,
                    r12=r12,
                    cfsr=cfsr,
                    hfsr=hfsr,
                    bfar=bfar,
                    mmfar=mmfar,
                    stack_bytes=stack_bytes
                )
        except Exception:
            return None

    def reset_and_run(self) -> bool:
        try:
            from pyocd.core.helpers import ConnectHelper
            session = ConnectHelper.session_with_chosen_probe(
                target_override=self.config.target_override or "stm32f407zg",
                unique_id=self.config.probe_id
            )
            if not session:
                return False
            with session:
                session.target.reset()
                session.target.resume()
            return True
        except Exception:
            return False
