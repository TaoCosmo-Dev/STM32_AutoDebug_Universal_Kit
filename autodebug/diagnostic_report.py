"""
Structured diagnostic report generator.

One JSON file is the entire contract between the pipeline and the AI doing the repair:
what failed, where, why (from silicon), what to change, and whether this is the same
failure as last iteration. Every report carries a `signature` so the loop can detect that
a patch changed nothing and escalate instead of burning the remaining iterations.
"""
from dataclasses import asdict, dataclass, field, is_dataclass
import json
import os
import time
from typing import Any, Dict, List, Optional

from .builder import BuildResult
from .fault_analyzer import FaultDiagnostics

STATUS_BUILD_FAILED = "BUILD_FAILED"
STATUS_FLASH_FAILED = "FLASH_FAILED"
STATUS_HARD_FAULT = "HARD_FAULT"
STATUS_ASSERTION_FAILED = "ASSERTION_FAILED"
STATUS_TEST_FAILED = "TEST_FAILED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_SERIAL_UNAVAILABLE = "SERIAL_UNAVAILABLE"
STATUS_PASSED = "TEST_PASSED"


def _jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


@dataclass
class DiagnosticReport:
    timestamp: str
    iteration: int
    project_path: str
    status: str
    summary: str
    signature: str
    compiler_errors: List[Dict[str, Any]] = field(default_factory=list)
    fault_diagnostics: Optional[Dict[str, Any]] = None
    source_context: Optional[Dict[str, Any]] = None
    serial_log_tail: str = ""
    next_actions: List[str] = field(default_factory=list)
    repeated_failure: bool = False
    ai_repair_prompt: str = ""

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(_jsonable(self), indent=indent, ensure_ascii=False)

    def save(self, output_path: str) -> str:
        parent = os.path.dirname(os.path.abspath(output_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        return output_path


def _tail(text: str, limit: int = 3000) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else "...\n" + text[-limit:]


class DiagnosticReporter:
    """Builds the report and, crucially, the Chinese repair prompt the AI acts on."""

    # ------------------------------------------------------------------ build failures

    @staticmethod
    def create_from_build_failure(build_result: BuildResult, iteration: int,
                                  proj_path: str) -> DiagnosticReport:
        errors = [_jsonable(e) for e in build_result.errors]
        if build_result.errors:
            summary = f"Keil 编译失败，{len(build_result.errors)} 个错误。"
        else:
            summary = f"Keil 构建失败：{build_result.failure_reason or '未知原因'}"

        lines = [
            f"# STM32 固件编译失败诊断报告（迭代 {iteration}）",
            f"**项目**: `{proj_path}`",
            f"**Target**: `{build_result.target_name}`",
            f"**UV4 退出码**: `{build_result.return_code}`",
            f"**失败原因**: {build_result.failure_reason or '编译错误'}",
            "",
        ]

        if build_result.errors:
            lines.append("## 编译器 / 链接器错误明细")
            for err in build_result.errors:
                where = (f"`{err.file_path}:{err.line_number}`"
                         if err.line_number else f"`{err.file_path}`")
                code = f" `{err.error_code}`" if err.error_code else ""
                lines.append(f"- {where}{code}\n  - {err.message}")
        else:
            lines.append("## 构建日志尾部")
            lines.append("```")
            lines.append(_tail(build_result.raw_log, 1500))
            lines.append("```")

        actions = [
            "打开报错文件的对应行，按错误码修复语法 / 未定义标识符 / 类型不匹配。",
            "链接错误（L6xxx）通常是缺少 .c 文件未加入工程、函数只声明未实现，或启动文件与芯片型号不匹配。",
            "修复后重新运行 `python run_autodebug.py --project <工程>`，目标是 0 Error(s)。",
        ]
        if build_result.return_code not in (0, 1, 2, 3):
            actions.insert(0, "UV4 退出码异常：确认工程未被 uVision IDE 占用、器件支持包已安装、License 有效。")

        lines += ["", "## 修复目标", *[f"{i+1}. {a}" for i, a in enumerate(actions)]]

        return DiagnosticReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            iteration=iteration,
            project_path=proj_path,
            status=STATUS_BUILD_FAILED,
            summary=summary,
            signature=build_result.signature(),
            compiler_errors=errors,
            serial_log_tail=_tail(build_result.raw_log, 1200),
            next_actions=actions,
            ai_repair_prompt="\n".join(lines),
        )

    # ------------------------------------------------------------------ flash failures

    @staticmethod
    def create_from_flash_failure(message: str, iteration: int, proj_path: str,
                                  probes: List[str]) -> DiagnosticReport:
        actions = [
            "确认调试探针（CMSIS-DAP / ST-Link / DAPLink）已插好，且未被 Keil IDE、STM32CubeProgrammer 等占用。",
            "确认 SWDIO / SWCLK / GND / 3V3 四线接线正确，目标板已独立供电。",
            "若固件把 SWD 引脚复用成了普通 IO，请保持 connect_mode: under-reset，或按住复位再烧录。",
            "芯片被读保护（RDP Level 1）时需先整片擦除解锁。",
        ]
        lines = [
            f"# STM32 烧录失败报告（迭代 {iteration}）",
            f"**项目**: `{proj_path}`",
            f"**失败信息**: `{message}`",
            f"**当前可见探针**: {probes or '无'}",
            "",
            "## 处理建议",
            *[f"{i+1}. {a}" for i, a in enumerate(actions)],
            "",
            "> 注意：烧录未成功时本轮不产生任何运行时结论，**严禁**把上一版固件的行为当作本次修改的验证结果。",
        ]
        return DiagnosticReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            iteration=iteration,
            project_path=proj_path,
            status=STATUS_FLASH_FAILED,
            summary=f"烧录失败：{message}",
            signature=f"FLASH|{message[:80]}",
            next_actions=actions,
            ai_repair_prompt="\n".join(lines),
        )

    # ------------------------------------------------------------------ runtime faults

    @staticmethod
    def create_from_fault(diagnostics: FaultDiagnostics, iteration: int, proj_path: str,
                          status: str = STATUS_HARD_FAULT) -> DiagnosticReport:
        loc = diagnostics.fault_location
        src_ctx = None
        if loc:
            src_ctx = {
                "file_path": loc.file_path,
                "resolved_path": loc.resolved_path,
                "line_number": loc.line_number,
                "function": loc.function_name,
                "code_snippet": loc.source_context,
            }

        origin = "探针 SWD 读取" if diagnostics.source == "probe" else "固件 UART 自述"
        lines = [
            f"# STM32 运行时硬件故障深度诊断报告（迭代 {iteration}）",
            f"**故障类型**: `{diagnostics.fault_type}`",
            f"**数据来源**: {origin}",
            f"**根本原因**: {diagnostics.root_cause}",
            f"**堆栈**: `{diagnostics.active_sp}` (SP=0x{diagnostics.sp_value:08X})",
            "",
            "## 1. 异常栈帧（进入异常时被自动压栈的现场）",
        ]
        if diagnostics.stack_frame:
            fr = diagnostics.stack_frame
            lines += [
                f"- **PC（出错指令地址）**: `0x{fr.pc:08X}`",
                f"- **LR（返回地址）**: `0x{fr.lr:08X}`",
                f"- **R0~R3**: `0x{fr.r0:08X} 0x{fr.r1:08X} 0x{fr.r2:08X} 0x{fr.r3:08X}`",
                f"- **R12 / xPSR**: `0x{fr.r12:08X} / 0x{fr.xpsr:08X}`",
            ]
        else:
            lines.append("- 未能定位有效的异常栈帧（栈可能已被破坏，优先怀疑栈溢出）。")

        lines += [
            "",
            "## 2. SCB 故障状态寄存器",
            f"- **CFSR**: `0x{diagnostics.cfsr:08X}`",
            f"- **HFSR**: `0x{diagnostics.hfsr:08X}`",
        ]
        if diagnostics.fault_address is not None:
            lines.append(f"- **故障地址（有效）**: `0x{diagnostics.fault_address:08X}`")
        else:
            lines.append("- **故障地址**: 无效（CFSR 未置 BFARVALID/MMARVALID，多为 imprecise 错误）")
        if diagnostics.decoded_flags:
            lines.append("- **置位标志**:")
            lines += [f"  - {f}" for f in diagnostics.decoded_flags]

        if diagnostics.call_stack:
            lines += ["", "## 3. 源码定位"]
            for i, item in enumerate(diagnostics.call_stack):
                tag = "崩溃点" if i == 0 else f"调用栈 #{i}"
                lines.append(f"**{tag}**: `{item.file_path}:{item.line_number}` "
                             f"（函数 `{item.function_name or 'Unknown'}`）")
                if item.source_context:
                    lines += ["```c", item.source_context, "```"]
        else:
            lines += ["", "## 3. 源码定位",
                      "未能把 PC 映射到源码行。请确认 Keil 已开启调试信息（Output -> Debug Information）。"]

        actions = []
        if diagnostics.suggested_fix:
            actions.append(diagnostics.suggested_fix)
        actions += [
            "修复后重新运行闭环，直到串口输出通过令牌。",
            "禁止靠改参数碰运气：先从寄存器位定义与时钟树推导根因，再动代码。",
        ]

        lines += ["", "## 4. 修复指令", *[f"{i+1}. {a}" for i, a in enumerate(actions)]]
        if diagnostics.raw_logs:
            lines += ["", "## 5. 串口原始日志（尾部）", "```", _tail(diagnostics.raw_logs, 1500), "```"]

        return DiagnosticReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            iteration=iteration,
            project_path=proj_path,
            status=status,
            summary=diagnostics.root_cause,
            signature=diagnostics.signature(),
            fault_diagnostics=_jsonable(diagnostics),
            source_context=src_ctx,
            serial_log_tail=_tail(diagnostics.raw_logs),
            next_actions=actions,
            ai_repair_prompt="\n".join(lines),
        )

    # ------------------------------------------------------------------ assertions

    @staticmethod
    def create_from_assertion(assert_err: str, assert_file: str, assert_line: int,
                              iteration: int, proj_path: str, raw_output: str,
                              source_snippet: Optional[str] = None) -> DiagnosticReport:
        actions = [
            f"检查 `{assert_file}` 第 {assert_line} 行的断言条件，判断是被测逻辑错了还是断言写错了。",
            "若断言来自 HAL assert_param，说明传给 HAL 的参数非法：核对外设句柄、通道号与分频值。",
            "修好后重新运行闭环验证。",
        ]
        lines = [
            f"# STM32 断言失败报告（迭代 {iteration}）",
            f"**断言**: `{assert_err}`",
            f"**位置**: `{assert_file}:{assert_line}`",
            "",
        ]
        if source_snippet:
            lines += ["## 源码上下文", "```c", source_snippet, "```", ""]
        lines += [
            "## 串口日志（尾部）", "```", _tail(raw_output, 1500), "```",
            "", "## 修复指令", *[f"{i+1}. {a}" for i, a in enumerate(actions)],
        ]

        return DiagnosticReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            iteration=iteration,
            project_path=proj_path,
            status=STATUS_ASSERTION_FAILED,
            summary=f"断言失败 {assert_file}:{assert_line} -> {assert_err}",
            signature=f"ASSERT|{os.path.basename(assert_file)}:{assert_line}",
            fault_diagnostics={"assertion": assert_err, "file": assert_file, "line": assert_line},
            source_context={"file_path": assert_file, "line_number": assert_line,
                            "code_snippet": source_snippet},
            serial_log_tail=_tail(raw_output),
            next_actions=actions,
            ai_repair_prompt="\n".join(lines),
        )

    # ------------------------------------------------------------------ timeout / no output

    @staticmethod
    def create_from_timeout(iteration: int, proj_path: str, raw_output: str,
                            timeout_seconds: float, port: Optional[str],
                            cpu_running: Optional[bool],
                            pass_keywords: List[str],
                            serial_ok: bool = True,
                            open_error: Optional[str] = None,
                            firmware_problems: Optional[List[str]] = None) -> DiagnosticReport:
        if not serial_ok:
            status = STATUS_SERIAL_UNAVAILABLE
            summary = f"串口不可用：{open_error}"
            actions = [
                "插好 USB-TTL / 板载 USB-UART，并在设备管理器确认 COM 口存在。",
                "关闭占用该串口的其他程序（Keil 串口助手、SSCOM、PuTTY 等）。",
                "或在 autodebug.config.yaml 的 serial.port 里显式指定端口。",
            ]
            signature = f"SERIAL|{open_error}"
        else:
            status = STATUS_TIMEOUT
            summary = f"{timeout_seconds:.0f}s 内未收到通过令牌 {pass_keywords}"
            actions = [
                f"在固件测试通过路径上 printf 输出通过令牌之一：{pass_keywords}。",
                "确认串口重定向（fputc/_write）已实现且波特率与配置一致（默认 115200）。",
                "确认 main 循环真的跑到了输出点：CPU 存活遥测见下方结论。",
                "若程序卡死在某个 while 等待，按规范给所有硬件等待循环加超时退出计数器。",
            ]
            signature = "TIMEOUT|no pass token"

        if firmware_problems:
            # Nine times out of ten a silent run is not a bug in the firmware logic, it is
            # the firmware never having been told to say anything. Lead with that.
            actions = firmware_problems + actions

        alive = {True: "CPU 正在执行（PC 有变化）",
                 False: "CPU 已停住（halt 或死循环在同一地址）",
                 None: "无探针，无法判断"}[cpu_running]

        lines = [
            f"# STM32 运行时无结论报告（迭代 {iteration}）",
            f"**状态**: `{status}`",
            f"**串口**: `{port or '未找到'}`",
            f"**CPU 存活遥测**: {alive}",
            "",
            "## 串口原始输出（尾部）",
            "```",
            _tail(raw_output, 2000) or "(整个窗口期内没有收到任何字节)",
            "```",
            "",
            "## 处理建议",
            *[f"{i+1}. {a}" for i, a in enumerate(actions)],
        ]
        if firmware_problems:
            lines[-len(actions) - 1:-len(actions) - 1] = [
                "> 以下固件侧约定尚未满足，它们比业务逻辑更可能是本次无输出的原因。", ""]

        return DiagnosticReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            iteration=iteration,
            project_path=proj_path,
            status=status,
            summary=summary,
            signature=signature,
            serial_log_tail=_tail(raw_output),
            next_actions=actions,
            ai_repair_prompt="\n".join(lines),
        )

    # ------------------------------------------------------------------ success

    @staticmethod
    def create_success(iteration: int, proj_path: str, raw_output: str,
                       axf_path: Optional[str], warnings: int) -> DiagnosticReport:
        return DiagnosticReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            iteration=iteration,
            project_path=proj_path,
            status=STATUS_PASSED,
            summary=f"编译 0 Error（{warnings} Warning）+ 烧录成功 + 实机测试通过。",
            signature="PASS",
            serial_log_tail=_tail(raw_output),
            next_actions=["达到黄金发布标准，可以封版交付。"],
            ai_repair_prompt=(
                f"# 闭环通过（迭代 {iteration}）\n"
                f"固件 `{axf_path}` 已通过 Keil 0 Error 构建、探针烧录与实机串口验收，无需继续修改。"
            ),
        )
