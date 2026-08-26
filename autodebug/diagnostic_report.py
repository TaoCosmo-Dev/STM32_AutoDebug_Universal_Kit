"""
Structured Diagnostic Report Generator.
Packages compilation, hardware fault, stack trace, and source code context into a standardized JSON payload for AI self-healing.
"""
from dataclasses import asdict, dataclass
import json
import os
import time
from typing import Any, Dict, List, Optional
from .builder import BuildResult, CompilerMessage
from .fault_analyzer import FaultDiagnostics


@dataclass
class DiagnosticReport:
    timestamp: str
    iteration: int
    project_path: str
    status: str  # "BUILD_FAILED", "TEST_PASSED", "ASSERTION_FAILED", "HARD_FAULT", "TIMEOUT"
    summary: str
    compiler_errors: List[Dict[str, Any]]
    fault_diagnostics: Optional[Dict[str, Any]]
    source_context: Optional[Dict[str, Any]]
    ai_repair_prompt: str

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent, ensure_ascii=False)

    def save(self, output_path: str) -> None:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self.to_json())


class DiagnosticReporter:
    @staticmethod
    def create_from_build_failure(build_result: BuildResult, iteration: int, proj_path: str) -> DiagnosticReport:
        errors = [asdict(e) for e in build_result.errors]
        summary = f"Keil UV4 compilation failed with {len(build_result.errors)} errors."

        prompt_lines = [
            f"# STM32 固件编译失败诊断报告 (迭代 {iteration})",
            f"**项目路径**: `{proj_path}`",
            f"**错误数量**: {len(build_result.errors)}",
            "",
            "## 编译器错误明细:",
        ]
        for err in build_result.errors:
            prompt_lines.append(f"- **文件**: `{err.file_path}:{err.line_number}`")
            prompt_lines.append(f"  **级别**: {err.severity.upper()} {err.error_code}")
            prompt_lines.append(f"  **信息**: {err.message}")

        prompt_lines.append("")
        prompt_lines.append("## 修复目标:")
        prompt_lines.append("请分析上述编译错误，修改对应的 C 源码文件，修复类型/未定义标识符/语法错误，确保 `0 Error(s)`。")

        return DiagnosticReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            iteration=iteration,
            project_path=proj_path,
            status="BUILD_FAILED",
            summary=summary,
            compiler_errors=errors,
            fault_diagnostics=None,
            source_context=None,
            ai_repair_prompt="\n".join(prompt_lines)
        )

    @staticmethod
    def create_from_fault(diagnostics: FaultDiagnostics, iteration: int, proj_path: str) -> DiagnosticReport:
        loc = diagnostics.fault_location
        src_ctx = None
        if loc:
            src_ctx = {
                "file_path": loc.file_path,
                "line_number": loc.line_number,
                "function": loc.function_name,
                "code_snippet": loc.source_context
            }

        prompt_lines = [
            f"# STM32 固件运行时硬件故障深度诊断报告 (迭代 {iteration})",
            f"**故障类型**: `{diagnostics.fault_type}`",
            f"**根本原因**: `{diagnostics.root_cause}`",
            f"**堆栈类型**: `{diagnostics.active_sp}` (SP=0x{diagnostics.sp_value:08X})",
            "",
            "## 1. 核心寄存器快照 (Core Registers):",
        ]
        if diagnostics.stack_frame:
            f = diagnostics.stack_frame
            prompt_lines.extend([
                f"- **PC (崩溃指令地址)**: `0x{f.pc:08X}`",
                f"- **LR (调用返回地址)**: `0x{f.lr:08X}`",
                f"- **R0~R3**: `R0=0x{f.r0:08X}, R1=0x{f.r1:08X}, R2=0x{f.r2:08X}, R3=0x{f.r3:08X}`",
                f"- **R12 / xPSR**: `R12=0x{f.r12:08X}, xPSR=0x{f.xpsr:08X}`"
            ])

        prompt_lines.extend([
            "",
            "## 2. SCB 故障状态寄存器 (SCB Fault Status):",
            f"- **CFSR**: `0x{diagnostics.cfsr:08X}`",
            f"- **HFSR**: `0x{diagnostics.hfsr:08X}`"
        ])
        if diagnostics.bfar:
            prompt_lines.append(f"- **BFAR (总线故障地址)**: `0x{diagnostics.bfar:08X}`")

        if loc:
            prompt_lines.extend([
                "",
                "## 3. 源码定位与代码片段 (Source Location):",
                f"**文件**: `{loc.file_path}`",
                f"**行号**: 第 {loc.line_number} 行",
                f"**函数**: `{loc.function_name or 'Unknown'}`",
                "",
                "```c",
                loc.source_context or "// No source context available",
                "```"
            ])

        prompt_lines.extend([
            "",
            "## 4. 修复指令:",
            f"请修复位于 `{loc.file_path if loc else '源码'}` 的缺陷，消除 {diagnostics.root_cause}，使固件稳定运行并通过测试。"
        ])

        return DiagnosticReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            iteration=iteration,
            project_path=proj_path,
            status="HARD_FAULT",
            summary=diagnostics.root_cause,
            compiler_errors=[],
            fault_diagnostics=asdict(diagnostics) if hasattr(diagnostics, "__dataclass_fields__") else {},
            source_context=src_ctx,
            ai_repair_prompt="\n".join(prompt_lines)
        )

    @staticmethod
    def create_from_assertion(assert_err: str, assert_file: str, assert_line: int, iteration: int, proj_path: str, raw_output: str) -> DiagnosticReport:
        prompt_lines = [
            f"# STM32 固件测试断言失败报告 (迭代 {iteration})",
            f"**断言信息**: `{assert_err}`",
            f"**文件位置**: `{assert_file}:{assert_line}`",
            "",
            "## 串口测试输出日志:",
            "```",
            raw_output[-500:] if len(raw_output) > 500 else raw_output,
            "```",
            "",
            "## 修复指令:",
            f"请检查 `{assert_file}` 第 {assert_line} 行断言条件，修复逻辑错误使其满足测试期望。"
        ]

        return DiagnosticReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            iteration=iteration,
            project_path=proj_path,
            status="ASSERTION_FAILED",
            summary=f"Assertion failed in {assert_file}:{assert_line}: {assert_err}",
            compiler_errors=[],
            fault_diagnostics={"assertion": assert_err, "file": assert_file, "line": assert_line},
            source_context={"file_path": assert_file, "line_number": assert_line},
            ai_repair_prompt="\n".join(prompt_lines)
        )
