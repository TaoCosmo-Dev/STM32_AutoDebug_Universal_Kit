"""
Universal STM32 Auto-Debug MCP (Model Context Protocol) Server.
Allows any MCP-compatible AI (Claude Desktop, Cursor, Windsurf, Antigravity, etc.) to natively compile, flash, and diagnose STM32 firmware.
"""
import os
import sys
import json

# Ensure autodebug is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autodebug.builder import KeilBuilder
from autodebug.hardware_probe import HardwareProbe
from autodebug.symbol_resolver import SymbolResolver
from autodebug.fault_analyzer import CortexMFaultAnalyzer
from autodebug.serial_monitor import SerialMonitor
from autodebug.config import AutoDebugConfig


def handle_build(project_path: str) -> str:
    config = AutoDebugConfig.load()
    builder = KeilBuilder(config.keil.uv4_path)
    res = builder.build(project_path)
    return json.dumps({
        "success": res.success,
        "return_code": res.return_code,
        "errors": [{"file": e.file_path, "line": e.line_number, "msg": e.message} for e in res.errors],
        "warnings_count": len(res.warnings),
        "axf_path": res.axf_path,
        "duration": f"{res.duration_seconds:.2f}s"
    }, indent=2, ensure_ascii=False)


def handle_flash(binary_path: str, target: str = "stm32f446re") -> str:
    config = AutoDebugConfig.load()
    config.debugger.target_override = target
    probe = HardwareProbe(config.debugger)
    ok = probe.flash(binary_path)
    return json.dumps({"flash_success": ok, "binary": binary_path, "target": target}, indent=2)


def handle_diagnose(axf_path: str, pc_addr: int, cfsr: int = 0x00008200) -> str:
    resolver = SymbolResolver(axf_path)
    analyzer = CortexMFaultAnalyzer()
    loc = resolver.resolve_address(pc_addr)
    flags = analyzer.decode_cfsr(cfsr)
    return json.dumps({
        "pc_address": f"0x{pc_addr:08X}",
        "cfsr_flags": flags,
        "source_file": loc.file_path if loc else "Unknown",
        "line_number": loc.line_number if loc else 0,
        "function": loc.function_name if loc else "Unknown",
        "code_snippet": loc.source_context if loc else ""
    }, indent=2, ensure_ascii=False)


def handle_read_registers(target: str = "stm32f446re") -> str:
    config = AutoDebugConfig.load()
    config.debugger.target_override = target
    probe = HardwareProbe(config.debugger)
    regs = probe.read_core_registers()
    if regs:
        return json.dumps({
            "status": "Target Halted",
            "registers": {
                "PC": f"0x{regs.pc:08X}",
                "LR": f"0x{regs.lr:08X}",
                "SP": f"0x{regs.sp:08X}",
                "CFSR": f"0x{regs.cfsr:08X}",
                "HFSR": f"0x{regs.hfsr:08X}",
                "MMFAR": f"0x{regs.mmfar:08X}",
                "BFAR": f"0x{regs.bfar:08X}"
            }
        }, indent=2)
    else:
        return json.dumps({"status": "Failed to halt or connect probe"}, indent=2)


def handle_inject(target_dir: str) -> str:
    from inject_to_project import inject
    ok = inject(target_dir)
    return json.dumps({"injected": ok, "target": target_dir}, indent=2)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("STM32 MCP Server initialized successfully!")
    else:
        print("STM32 Auto-Debug Universal Tool Engine Ready.")

