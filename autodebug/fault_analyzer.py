"""
ARM Cortex-M Fault Analyzer and SCB Register Decoder.
Decodes CFSR, HFSR, BFAR, MMAR, unrolls exception stack frame, and pinpoints root causes.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from .symbol_resolver import SourceLocation, SymbolResolver


# SCB Register Addresses (ARMv7-M / ARMv8-M)
SCB_CFSR_ADDR = 0xE000ED28
SCB_HFSR_ADDR = 0xE000ED2C
SCB_DFSR_ADDR = 0xE000ED30
SCB_MMFAR_ADDR = 0xE000ED34
SCB_BFAR_ADDR = 0xE000ED38


@dataclass
class CPUStackFrame:
    r0: int = 0
    r1: int = 0
    r2: int = 0
    r3: int = 0
    r12: int = 0
    lr: int = 0
    pc: int = 0
    xpsr: int = 0


@dataclass
class FaultDiagnostics:
    fault_type: str  # e.g., "HardFault", "AssertionFailed", "StackOverflow", "Timeout"
    root_cause: str  # Human-readable root cause explanation
    cfsr: int = 0
    hfsr: int = 0
    bfar: Optional[int] = None
    mmfar: Optional[int] = None
    stack_frame: Optional[CPUStackFrame] = None
    active_sp: str = "MSP"  # "MSP" or "PSP"
    sp_value: int = 0
    fault_location: Optional[SourceLocation] = None
    call_stack: List[SourceLocation] = field(default_factory=list)
    raw_logs: str = ""
    suggested_fix: str = ""


class CortexMFaultAnalyzer:
    """Decodes ARM Cortex-M hardware exceptions and constructs structured diagnostics."""

    @staticmethod
    def decode_cfsr(cfsr: int) -> List[str]:
        flags = []
        mmfsr = cfsr & 0xFF
        bfsr = (cfsr >> 8) & 0xFF
        ufsr = (cfsr >> 16) & 0xFFFF

        # MemManage Faults
        if mmfsr & (1 << 0):
            flags.append("IACCVIOL: MPU instruction access violation")
        if mmfsr & (1 << 1):
            flags.append("DACCVIOL: MPU data access violation (invalid memory read/write)")
        if mmfsr & (1 << 3):
            flags.append("MUNSTKERR: MemManage fault during exception unstacking")
        if mmfsr & (1 << 4):
            flags.append("MSTKERR: MemManage fault during exception stacking (Stack Overflow likely)")
        if mmfsr & (1 << 7):
            flags.append("MMARVALID: MMFAR holds valid memory fault address")

        # Bus Faults
        if bfsr & (1 << 0):
            flags.append("IBUSERR: Instruction bus error")
        if bfsr & (1 << 1):
            flags.append("PRECISERR: Precise data bus access error (NULL pointer or bad memory address)")
        if bfsr & (1 << 2):
            flags.append("IMPRECISERR: Imprecise asynchronous data bus error")
        if bfsr & (1 << 3):
            flags.append("UNSTKERR: BusFault during exception unstacking")
        if bfsr & (1 << 4):
            flags.append("STKERR: BusFault during exception stacking")
        if bfsr & (1 << 7):
            flags.append("BFARVALID: BFAR holds valid bus fault address")

        # Usage Faults
        if ufsr & (1 << 0):
            flags.append("UNDEFINSTR: Undefined instruction executed")
        if ufsr & (1 << 1):
            flags.append("INVSTATE: Invalid core state (Thumb bit missing / ARM state requested)")
        if ufsr & (1 << 2):
            flags.append("INVPC: Invalid PC load on exception return")
        if ufsr & (1 << 3):
            flags.append("NOCP: Coprocessor / FPU instruction executed without FPU clock enabled")
        if ufsr & (1 << 8):
            flags.append("UNALIGNED: Unaligned memory access on unaligned-fault-enabled core")
        if ufsr & (1 << 9):
            flags.append("DIVBYZERO: Division by zero executed")

        return flags

    @staticmethod
    def decode_hfsr(hfsr: int) -> List[str]:
        flags = []
        if hfsr & (1 << 1):
            flags.append("VECTTBL: Vector table read fault on exception handling")
        if hfsr & (1 << 30):
            flags.append("FORCED: Forced HardFault (Escalated from MemManage, BusFault, or UsageFault)")
        if hfsr & (1 << 31):
            flags.append("DEBUGEVT: HardFault triggered by debug event")
        return flags

    @staticmethod
    def classify_root_cause(cfsr: int, hfsr: int, bfar: Optional[int], frame: Optional[CPUStackFrame]) -> Tuple[str, str]:
        """Returns (SummaryTitle, DetailedExplanation)."""
        ufsr = (cfsr >> 16) & 0xFFFF
        bfsr = (cfsr >> 8) & 0xFF
        mmfsr = cfsr & 0xFF

        if ufsr & (1 << 9):
            return "Divide by Zero", "Firmware attempted an integer division by zero (DIVBYZERO)."
        if ufsr & (1 << 8):
            return "Unaligned Memory Access", "32-bit or 16-bit word accessed at an unaligned memory address (UNALIGNED)."
        if ufsr & (1 << 3):
            return "FPU Not Enabled", "Hardware floating-point instruction executed before SCB->CPACR enabled CP10/CP11 (NOCP)."
        if ufsr & (1 << 0):
            return "Undefined Instruction", "Target attempted to execute an invalid or corrupted instruction byte sequence (UNDEFINSTR)."

        if (bfsr & (1 << 1)) or (mmfsr & (1 << 1)):
            if bfar is not None and bfar < 0x00000100:
                return "NULL Pointer Dereference", f"Attempted to read/write memory at NULL or near-zero offset address 0x{bfar:08X}."
            elif bfar is not None:
                return "Invalid Bus Access / Wild Pointer", f"Illegal memory access at invalid address 0x{bfar:08X} (PRECISERR)."
            return "Data Access Violation", "Illegal memory read/write operation (PRECISERR/DACCVIOL)."

        if (mmfsr & (1 << 4)) or (bfsr & (1 << 4)):
            return "Stack Overflow", "Stack limit reached or stack pointer corrupted during interrupt stacking (MSTKERR/STKERR)."

        if hfsr & (1 << 30):
            return "Forced HardFault", "Configurable fault occurred while its handler was disabled, escalating to HardFault."

        return "Cortex-M HardFault", "Unhandled hardware exception occurred."

    def analyze(self,
                cfsr: int,
                hfsr: int,
                sp: int,
                lr: int,
                stack_bytes: bytes,
                resolver: Optional[SymbolResolver],
                raw_logs: str = "") -> FaultDiagnostics:
        """
        Unpacks stack frame, decodes registers, and maps to source code.
        """
        # Determine stack pointer type from EXC_RETURN (LR)
        # EXC_RETURN bit 2: 0 = MSP, 1 = PSP
        is_psp = bool(lr & 0x4)
        sp_name = "PSP" if is_psp else "MSP"

        # Unpack 8 words (32 bytes) from stack: R0, R1, R2, R3, R12, LR, PC, xPSR
        frame = CPUStackFrame()
        if len(stack_bytes) >= 32:
            import struct
            words = struct.unpack("<8I", stack_bytes[:32])
            frame = CPUStackFrame(
                r0=words[0],
                r1=words[1],
                r2=words[2],
                r3=words[3],
                r12=words[4],
                lr=words[5],
                pc=words[6],
                xpsr=words[7]
            )

        # BFAR / MMAR validity
        bfar = None
        if (cfsr >> 8) & (1 << 7):  # BFARVALID
            # Caller can supply or we assume from registers
            pass

        title, explanation = self.classify_root_cause(cfsr, hfsr, bfar, frame)

        # Source code mapping via DWARF
        loc = None
        call_stack = []
        if resolver and frame.pc:
            loc = resolver.resolve_address(frame.pc)
            if loc:
                call_stack.append(loc)
            if frame.lr and (frame.lr & 0xFF000000) != 0xFF000000:  # Not EXC_RETURN
                lr_loc = resolver.resolve_address(frame.lr)
                if lr_loc:
                    call_stack.append(lr_loc)

        return FaultDiagnostics(
            fault_type="HardFault",
            root_cause=f"{title}: {explanation}",
            cfsr=cfsr,
            hfsr=hfsr,
            bfar=bfar,
            stack_frame=frame,
            active_sp=sp_name,
            sp_value=sp,
            fault_location=loc,
            call_stack=call_stack,
            raw_logs=raw_logs,
            suggested_fix=""
        )
