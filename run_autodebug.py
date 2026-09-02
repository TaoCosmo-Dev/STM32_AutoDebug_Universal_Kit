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
