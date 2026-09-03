"""
Universal auto-debug closed-loop runner for STM32.

Callable by any AI agent (Claude Code, Cursor, Windsurf, Aider, ...) or by a human.
The exit code is the contract - it is never 0 unless the firmware actually built,
flashed and passed on real hardware.

    0  TEST_PASSED           build 0 Error + flashed + pass token seen on UART
    1  BUILD_FAILED          compiler / linker errors  -> patch the source
    2  FLASH_FAILED          probe or wiring problem   -> human action, not a code fix
    3  HARD_FAULT / ASSERT   runtime fault located     -> patch the source
    4  TIMEOUT / NO UART     no verdict token          -> check the test harness
    5  STALLED               identical failure repeated -> escalate to a human
    6  CONFIG_ERROR          toolchain not found

Usage:
    python run_autodebug.py --project MDK-ARM/Project.uvprojx
    python run_autodebug.py --project ... --json          # machine-readable summary
    python run_autodebug.py --list-devices                # probes + COM ports
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autodebug.config import AutoDebugConfig, list_connected_probes
from autodebug.engine import AutoDebugEngine, EXIT_CODES, STATUS_CONFIG_ERROR
from autodebug.serial_monitor import SerialMonitor

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".autodebug", "Objects",
             "Listings", "build", "Debug", "Release", ".vs", ".venv"}


def find_uvprojx(start_dir: str) -> list:
    """Find Keil projects under start_dir. Never walks upward into unrelated projects."""
    found = []
    for root, dirs, files in os.walk(start_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".uvprojx"):
                found.append(os.path.join(root, f))
    # Prefer the conventional MDK-ARM location, then the shallowest path.
    found.sort(key=lambda p: (0 if "MDK-ARM" in p else 1, p.count(os.sep), p))
    return found


def cmd_list_devices() -> int:
    probes = list_connected_probes()
    print("下载器（调试探针）：")
    if probes:
        for p in probes:
            print(f"  - {getattr(p, 'description', '?')}  [{p.unique_id}]")
    else:
        print("  （未检测到，请检查 USB 是否插好）")
    print("\n串口：")
    ports = SerialMonitor.describe_ports()
    for p in ports or ["  (none detected)"]:
        print(f"  - {p}" if ports else p)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="STM32 auto-debug closed-loop runner",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", help="Path to the Keil .uvprojx file")
    parser.add_argument("--target", help="Keil build target name (multi-target projects)")
    parser.add_argument("--mcu", help="pyOCD target name override (default: from .uvprojx)")
    parser.add_argument("--config", help="Path to autodebug.config.yaml")
    parser.add_argument("--port", help="Serial port (default: auto-detect)")
    parser.add_argument("--baud", type=int, help="Serial baudrate (default: 115200)")
    parser.add_argument("--timeout", type=float, help="Seconds to wait for the verdict token")
    parser.add_argument("--iterations", type=int, help="Max repair iterations for --auto")
    parser.add_argument("--rebuild", action="store_true", help="Full rebuild instead of incremental")
    parser.add_argument("--no-flash", action="store_true", help="Build only, do not touch hardware")
    parser.add_argument("--auto", action="store_true",
                        help="Keep looping in-process (requires a patch callback; "
                             "for AI agents the default single-pass mode is correct)")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable summary")
    parser.add_argument("--quiet", action="store_true", help="Suppress the streaming log")
    parser.add_argument("--list-devices", action="store_true", help="List probes and COM ports")

    project_edits = parser.add_argument_group(
        "project edits", "Change the Keil project from the command line, so nothing needs "
                         "the uVision GUI")
    project_edits.add_argument("--add-source", nargs="+", metavar="FILE",
                               help="Add source file(s) to the project (a .c the AI just wrote "
                                    "is invisible to the linker until this runs)")
    project_edits.add_argument("--add-include", nargs="+", metavar="DIR",
                               help="Add include path(s)")
    project_edits.add_argument("--add-define", nargs="+", metavar="NAME",
                               help="Add preprocessor define(s)")
    project_edits.add_argument("--group", default="AutoDebug",
                               help="Group name for --add-source (default: AutoDebug)")
    project_edits.add_argument("--install-tracer", action="store_true",
                               help="Install the crash tracer: copy it in, register it with "
                                    "Keil, add the include path, and neutralise the HAL fault stub")
    project_edits.add_argument("--uart", metavar="USARTx",
                               help="With --install-tracer: generate a blocking putchar on this port")
    project_edits.add_argument("--family", metavar="f1|f4|g0|g4|h7|...",
                               help="With --install-tracer: chip family (default: from the .uvprojx)")
    project_edits.add_argument("--check-firmware", action="store_true",
                               help="Report which firmware-side obligations are still unmet")
    args = parser.parse_args()

    if args.list_devices:
        return cmd_list_devices()

    # ---- locate the project ----------------------------------------------------------
    proj_path = args.project
    if not proj_path:
        candidates = find_uvprojx(os.getcwd())
        if not candidates:
            print("[错误] 当前目录下找不到 Keil 工程（.uvprojx）。"
                  "请用 --project <路径> 指定。", file=sys.stderr)
            return EXIT_CODES[STATUS_CONFIG_ERROR]
        proj_path = candidates[0]
        if len(candidates) > 1:
            print(f"[!] 找到 {len(candidates)} 个 Keil 工程，使用 {proj_path}。"
                  f"要换一个请用 --project 指定。", file=sys.stderr)
    if not os.path.exists(proj_path):
        print(f"[错误] 工程文件不存在：{proj_path}", file=sys.stderr)
        return EXIT_CODES[STATUS_CONFIG_ERROR]

    # ---- project edits (no uVision needed) -------------------------------------------
    edited = False
    if args.add_source or args.add_include or args.add_define:
        from autodebug.project_editor import KeilProjectEditor
        editor = KeilProjectEditor(proj_path)
        if args.add_source:
            editor.add_sources(args.add_source, group=args.group, target_name=args.target)
        if args.add_include:
            editor.add_include_paths(args.add_include, target_name=args.target)
        if args.add_define:
            editor.add_defines(args.add_define, target_name=args.target)
        result = editor.save()
        print(f"[project] {result.summary()}")
        edited = True

    if args.install_tracer:
        from autodebug.builder import KeilBuilder
        from autodebug.firmware_setup import install_crash_tracer
        mcu = args.mcu or KeilBuilder(None).get_device_name(proj_path)
        result = install_crash_tracer(proj_path, target_name=args.target,
                                      uart=args.uart, family=args.family, mcu=mcu)
        for note in result.notes:
            print(f"[tracer] {note}")
        edited = True

    if args.check_firmware:
        from autodebug.firmware_setup import check_firmware_contract
        problems = check_firmware_contract(os.path.dirname(os.path.dirname(
            os.path.abspath(proj_path))))
        if problems:
            print("[firmware] 还差这些，闭环才能给出根因：")
            for i, problem in enumerate(problems, 1):
                print(f"  {i}. {problem}")
        else:
            print("[firmware] 固件侧契约已满足：通过令牌 + 崩溃自述 + 输出通道")
        edited = True

    if edited:
        # Project edits are a standalone action - they never implicitly start a build.
        return 0

    # ---- config with CLI overrides ---------------------------------------------------
    config = AutoDebugConfig.load(args.config)
    if args.mcu:
        config.debugger.target_override = args.mcu
    if args.port:
        config.serial.port = args.port
    if args.baud:
        config.serial.baudrate = args.baud
    if args.timeout is not None:
        config.serial.timeout_seconds = args.timeout
    if args.iterations:
        config.test.max_repair_iterations = args.iterations
    if args.rebuild:
        config.build.rebuild = True

    engine = AutoDebugEngine(config, verbose=not args.quiet)

    # ---- build-only mode -------------------------------------------------------------
    if args.no_flash:
        problems = config.preflight()
        if problems:
            print("[ERROR] " + "; ".join(problems), file=sys.stderr)
            return EXIT_CODES[STATUS_CONFIG_ERROR]
        res = engine.builder.build(proj_path, args.target)
        if args.json:
            print(json.dumps({
                "status": "BUILD_OK" if res.success else "BUILD_FAILED",
                "errors": [{"file": e.file_path, "line": e.line_number,
                            "code": e.error_code, "message": e.message} for e in res.errors],
                "warnings": len(res.warnings),
                "axf": res.axf_path,
                "seconds": round(res.duration_seconds, 2),
                "failure_reason": res.failure_reason,
            }, indent=2, ensure_ascii=False))
        else:
            if res.success:
                print(f"[+] 编译通过  0 Error，{len(res.warnings)} Warning  -> {res.axf_path}")
            else:
                print(f"[-] 编译失败：{res.failure_reason}")
                for e in res.errors[:20]:
                    print(f"    {e.file_path}:{e.line_number} {e.error_code} {e.message}")
        return 0 if res.success else 1

    # ---- full closed loop ------------------------------------------------------------
    result = engine.run_closed_loop(proj_path, args.target)
    report = result.last_report

    if args.json:
        print(json.dumps({
            "status": result.final_status,
            "success": result.success,
            "iterations_run": result.iterations_run,
            "exit_code": result.exit_code,
            "report_path": result.report_path,
            "summary": report.summary if report else "",
            "signature": report.signature if report else "",
            "repeated_failure": report.repeated_failure if report else False,
            "next_actions": report.next_actions if report else [],
            "messages": result.messages,
        }, indent=2, ensure_ascii=False))
        return result.exit_code

    print("\n" + "=" * 63)
    if result.success:
        print("  [AUTODEBUG PASS] 编译 + 烧录 + 实机验收 全部通过")
    else:
        print(f"  [AUTODEBUG FAIL] 状态={result.final_status}（退出码 {result.exit_code}）")
        if report:
            print(f"  原因: {report.summary}")
            if report.repeated_failure:
                print("  ⚠ 与上一轮完全相同的失败，上一次修改没有起效，请换思路。")
            print(f"  完整诊断报告：{result.report_path}")
            print("\n" + report.ai_repair_prompt)
    print("=" * 63)
    return result.exit_code


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    sys.exit(main())
