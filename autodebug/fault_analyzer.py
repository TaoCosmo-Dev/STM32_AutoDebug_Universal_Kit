"""
ARM Cortex-M fault analyzer: decodes CFSR / HFSR, unpacks the exception stack frame,
resolves the faulting PC to a source line and states a concrete first-principles fix.

The fault address (BFAR / MMFAR) is the single most valuable datum in a HardFault and it
is carried end to end here - from the probe or from the firmware's own UART dump - because
without it "bus fault" degenerates into a guess.
"""
from dataclasses import dataclass, field
import struct
from typing import List, Optional, Tuple

from .symbol_resolver import SourceLocation, SymbolResolver

# SCB register addresses (ARMv7-M / ARMv8-M)
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

    @property
    def valid(self) -> bool:
        return self.pc != 0 or self.xpsr != 0


@dataclass
class FaultDiagnostics:
    fault_type: str          # "HardFault" | "AssertionFailed" | "Timeout" | ...
    root_cause: str
    cfsr: int = 0
    hfsr: int = 0
    bfar: Optional[int] = None
    mmfar: Optional[int] = None
    fault_address: Optional[int] = None    # the valid one of BFAR / MMFAR
    decoded_flags: List[str] = field(default_factory=list)
    stack_frame: Optional[CPUStackFrame] = None
    active_sp: str = "MSP"
    sp_value: int = 0
    fault_location: Optional[SourceLocation] = None
    call_stack: List[SourceLocation] = field(default_factory=list)
    raw_logs: str = ""
    suggested_fix: str = ""
    source: str = "probe"                  # "probe" | "uart" | "none"

    def signature(self) -> str:
        pc = self.stack_frame.pc if self.stack_frame else 0
        return f"FAULT|{self.fault_type}|PC=0x{pc:08X}|CFSR=0x{self.cfsr:08X}"


# Root-cause table: (predicate on decoded fields) -> (title, explanation, fix hint)
_FIX_HINTS = {
    "Divide by Zero":
        "定位除法表达式，先判断分母是否为 0；若分母来自传感器/编码器采样，加零值保护与滤波。"
        "注意：只有置位 SCB->CCR 的 DIV_0_TRP 才会触发本异常。",
    "Unaligned Memory Access":
        "检查强制指针转换（如 (uint32_t*)(buf+1)）与通信协议结构体，使用 __attribute__((packed)) "
        "或逐字节 memcpy 取值，禁止对非 4 字节对齐地址做 32 位访问。",
    "FPU Not Enabled":
        "在 SystemInit/main 最前面使能 FPU：SCB->CPACR |= (0xF << 20); __DSB(); __ISB();"
        "或确认工程 Floating Point Hardware 选项与链接选项一致。",
    "Undefined Instruction":
        "PC 指向非法指令，通常是函数指针未初始化/被野指针改写，或跳转到了非 Thumb 地址"
        "（目标地址 bit0 必须为 1）。检查回调注册与函数指针数组。",
    "NULL Pointer Dereference":
        "空指针解引用。检查该地址附近的结构体指针是否在使用前完成初始化/malloc 返回值是否判空，"
        "以及 HAL 句柄（如 &htim2）是否传成了 NULL。",
    "Invalid Bus Access / Wild Pointer":
        "访问了不存在的物理地址。核对数组越界、DMA 目标缓冲区地址、外设基址宏，"
        "以及访问外设前是否已开启对应的 RCC 时钟（时钟未开时读写外设寄存器即产生总线错误）。",
    "Data Access Violation":
        "非法内存读写。优先排查数组越界与未初始化指针；若使能了 MPU，核对区域权限配置。",
    "Stack Overflow":
        "入栈时即发生错误，栈已耗尽或 SP 被改写。加大 startup 文件里的 Stack_Size，"
        "把大数组从局部变量移到静态区，检查递归深度与 ISR 内的大缓冲区。",
    "Vector Table Fault":
        "取向量表失败。核对 SCB->VTOR 与链接脚本/分散加载的起始地址是否匹配"
        "（带 Bootloader 的工程最常见）。",
    "Forced HardFault":
        "可配置异常在其分类使能位关闭时升级为 HardFault。在启动阶段调用 cm_backtrace_init() "
        "使能 MemManage/Bus/Usage Fault，即可拿到精确的分类与地址。",
    "Cortex-M HardFault":
        "未能从 CFSR 得到分类信息。请确认已调用 cm_backtrace_init()，并检查复位后最早执行的代码。",
}


class CortexMFaultAnalyzer:
    """Decodes Cortex-M hardware exceptions into structured, actionable diagnostics."""

    # ---------------------------------------------------------------- decoders

    @staticmethod
    def decode_cfsr(cfsr: int) -> List[str]:
        flags: List[str] = []
        mmfsr = cfsr & 0xFF
        bfsr = (cfsr >> 8) & 0xFF
        ufsr = (cfsr >> 16) & 0xFFFF

        for bit, text in (
            (0, "IACCVIOL: MPU instruction access violation"),
            (1, "DACCVIOL: MPU data access violation (invalid memory read/write)"),
            (3, "MUNSTKERR: MemManage fault during exception unstacking"),
            (4, "MSTKERR: MemManage fault during exception stacking (stack overflow likely)"),
            (5, "MLSPERR: MemManage fault during lazy FP state preservation"),
            (7, "MMARVALID: MMFAR holds a valid fault address"),
        ):
            if mmfsr & (1 << bit):
                flags.append(text)

        for bit, text in (
            (0, "IBUSERR: Instruction bus error"),
            (1, "PRECISERR: Precise data bus error (NULL or wild pointer)"),
            (2, "IMPRECISERR: Imprecise asynchronous data bus error (buffered write)"),
            (3, "UNSTKERR: BusFault during exception unstacking"),
            (4, "STKERR: BusFault during exception stacking"),
            (5, "LSPERR: BusFault during lazy FP state preservation"),
            (7, "BFARVALID: BFAR holds a valid fault address"),
        ):
            if bfsr & (1 << bit):
                flags.append(text)

        for bit, text in (
            (0, "UNDEFINSTR: Undefined instruction executed"),
            (1, "INVSTATE: Invalid core state (Thumb bit missing)"),
            (2, "INVPC: Invalid PC load on exception return"),
            (3, "NOCP: Coprocessor/FPU instruction with the FPU disabled"),
            (8, "UNALIGNED: Unaligned memory access"),
            (9, "DIVBYZERO: Integer division by zero"),
        ):
            if ufsr & (1 << bit):
                flags.append(text)

        return flags

    @staticmethod
    def decode_hfsr(hfsr: int) -> List[str]:
        flags = []
        if hfsr & (1 << 1):
            flags.append("VECTTBL: Vector table read fault")
        if hfsr & (1 << 30):
            flags.append("FORCED: Escalated from MemManage/BusFault/UsageFault")
        if hfsr & (1 << 31):
            flags.append("DEBUGEVT: HardFault caused by a debug event (BKPT with no debugger)")
        return flags

    @staticmethod
    def classify_root_cause(cfsr: int, hfsr: int,
                            fault_address: Optional[int] = None) -> Tuple[str, str]:
        """Return (title, explanation) for the highest-signal bit that is set."""
        ufsr = (cfsr >> 16) & 0xFFFF
        bfsr = (cfsr >> 8) & 0xFF
        mmfsr = cfsr & 0xFF

        if ufsr & (1 << 9):
            return "Divide by Zero", "Firmware executed an integer division by zero (DIVBYZERO)."
        if ufsr & (1 << 8):
            return "Unaligned Memory Access", "A 16/32-bit access was made to an unaligned address (UNALIGNED)."
        if ufsr & (1 << 3):
            return "FPU Not Enabled", "A hardware floating-point instruction ran before SCB->CPACR enabled CP10/CP11 (NOCP)."
        if ufsr & (1 << 0):
            return "Undefined Instruction", "PC reached a byte sequence that is not a valid instruction (UNDEFINSTR)."
        if ufsr & (1 << 1):
            return "Undefined Instruction", "Branch to an address without the Thumb bit set (INVSTATE)."

        if (mmfsr & (1 << 4)) or (bfsr & (1 << 4)) or (mmfsr & (1 << 3)) or (bfsr & (1 << 3)):
            return "Stack Overflow", "The fault happened while the core was stacking/unstacking the exception frame (MSTKERR/STKERR)."

        if (bfsr & (1 << 1)) or (mmfsr & (1 << 1)) or (bfsr & (1 << 0)) or (mmfsr & (1 << 0)):
            if fault_address is not None and fault_address < 0x00000100:
                return "NULL Pointer Dereference", f"Access to NULL or a near-zero offset at 0x{fault_address:08X}."
            if fault_address is not None:
                return "Invalid Bus Access / Wild Pointer", f"Illegal access to 0x{fault_address:08X} (PRECISERR/DACCVIOL)."
            return "Data Access Violation", "Illegal memory read/write; the fault address register was not valid."

        if bfsr & (1 << 2):
            return "Invalid Bus Access / Wild Pointer", "Imprecise bus error (IMPRECISERR): a buffered write to an invalid address completed late."

        if hfsr & (1 << 1):
            return "Vector Table Fault", "The core could not read the vector table (VECTTBL)."
        if hfsr & (1 << 31):
            return "Cortex-M HardFault", "A BKPT executed with no debugger attached (DEBUGEVT)."
        if hfsr & (1 << 30):
            return "Forced HardFault", "A configurable fault escalated because its handler was disabled."

        return "Cortex-M HardFault", "Unhandled hardware exception with no classification bits set."

    # ---------------------------------------------------------------- frame handling

    @staticmethod
    def unpack_frame(stack_bytes: bytes) -> CPUStackFrame:
        if len(stack_bytes) < 32:
            return CPUStackFrame()
        w = struct.unpack_from("<8I", stack_bytes, 0)
        return CPUStackFrame(r0=w[0], r1=w[1], r2=w[2], r3=w[3],
                             r12=w[4], lr=w[5], pc=w[6], xpsr=w[7])

    @staticmethod
    def select_fault_address(cfsr: int, bfar: Optional[int], mmfar: Optional[int],
                             bfar_valid: Optional[bool] = None,
                             mmfar_valid: Optional[bool] = None) -> Optional[int]:
        """Only a register flagged valid by CFSR may be reported as the fault address."""
        if bfar_valid is None:
            bfar_valid = bool(cfsr & (1 << 15))   # BFARVALID
        if mmfar_valid is None:
            mmfar_valid = bool(cfsr & (1 << 7))   # MMARVALID
        if bfar_valid and bfar is not None:
            return bfar
        if mmfar_valid and mmfar is not None:
            return mmfar
        return None

    # ---------------------------------------------------------------- main entry

    def analyze(self,
                cfsr: int,
                hfsr: int,
                sp: int = 0,
                lr: int = 0,
                stack_bytes: bytes = b"",
                resolver: Optional[SymbolResolver] = None,
                raw_logs: str = "",
                bfar: Optional[int] = None,
                mmfar: Optional[int] = None,
                bfar_valid: Optional[bool] = None,
                mmfar_valid: Optional[bool] = None,
                active_sp: Optional[str] = None,
                extra_addresses: Optional[List[int]] = None,
                source: str = "probe") -> FaultDiagnostics:
        """Turn raw fault registers into a diagnosis with a source location and a fix."""
        if active_sp is None:
            # EXC_RETURN bit 2: 0 = frame on MSP, 1 = frame on PSP
            active_sp = "PSP" if (lr & 0x4) else "MSP"

        frame = self.unpack_frame(stack_bytes)
        fault_address = self.select_fault_address(cfsr, bfar, mmfar, bfar_valid, mmfar_valid)
        title, explanation = self.classify_root_cause(cfsr, hfsr, fault_address)

        flags = self.decode_cfsr(cfsr) + self.decode_hfsr(hfsr)

        loc = None
        call_stack: List[SourceLocation] = []
        if resolver:
            candidates: List[int] = []
            if frame.pc:
                candidates.append(frame.pc)
            if frame.lr and (frame.lr & 0xFF000000) != 0xFF000000:
                candidates.append(frame.lr)
            for addr in (extra_addresses or []):
                if addr and (addr & 0xFF000000) != 0xFF000000 and addr not in candidates:
                    candidates.append(addr)
            for addr in candidates:
                resolved = resolver.resolve_address(addr)
                if resolved:
                    call_stack.append(resolved)
            loc = call_stack[0] if call_stack else None

        return FaultDiagnostics(
            fault_type="HardFault",
            root_cause=f"{title}: {explanation}",
            cfsr=cfsr,
            hfsr=hfsr,
            bfar=bfar,
            mmfar=mmfar,
            fault_address=fault_address,
            decoded_flags=flags,
            stack_frame=frame if frame.valid else None,
            active_sp=active_sp,
            sp_value=sp,
            fault_location=loc,
            call_stack=call_stack,
            raw_logs=raw_logs,
            suggested_fix=_FIX_HINTS.get(title, ""),
            source=source,
        )

    # ---------------------------------------------------------------- adapters

    def from_core_state(self, state, resolver: Optional[SymbolResolver] = None,
                        raw_logs: str = "") -> FaultDiagnostics:
        """Build a diagnosis from a TargetCoreState read over SWD."""
        return self.analyze(
            cfsr=state.cfsr, hfsr=state.hfsr, sp=state.frame_sp or state.sp, lr=state.lr,
            stack_bytes=state.stack_bytes, resolver=resolver, raw_logs=raw_logs,
            bfar=state.bfar, mmfar=state.mmfar,
            bfar_valid=state.bfar_valid, mmfar_valid=state.mmfar_valid,
            active_sp="PSP" if state.frame_is_psp else "MSP",
            extra_addresses=[state.pc],
            source="probe",
        )

    def from_crash_telemetry(self, crash, resolver: Optional[SymbolResolver] = None,
                             raw_logs: str = "") -> FaultDiagnostics:
        """Build a diagnosis from the register dump the firmware printed over UART.

        This path needs no probe at all, which makes the loop work on boards where SWD is
        occupied or the fault handler already halted the core.
        """
        frame_bytes = struct.pack(
            "<8I",
            crash.get("R0"), crash.get("R1"), crash.get("R2"), crash.get("R3"),
            crash.get("R12"), crash.get("LR"), crash.get("PC"), crash.get("XPSR"),
        )
        cfsr = crash.get("CFSR")
        diag = self.analyze(
            cfsr=cfsr, hfsr=crash.get("HFSR"), sp=0, lr=crash.get("LR_EXC"),
            stack_bytes=frame_bytes, resolver=resolver, raw_logs=raw_logs,
            bfar=crash.get("BFAR"), mmfar=crash.get("MMFAR"),
            active_sp=crash.active_sp,
            extra_addresses=list(crash.backtrace),
            source="uart",
        )
        return diag
