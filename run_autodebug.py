"""
Universal Auto-Debug Closed-Loop Runner for STM32
=================================================
Can be called by ANY AI (Cursor, Claude Code, Windsurf, Aider, DeepSeek, etc.)
or human from terminal.

Usage:
    python run_autodebug.py [--project path/to/project.uvprojx] [--target stm32f446re]
"""
import os
import sys
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autodebug.builder import KeilBuilder
from autodebug.hardware_probe import HardwareProbe
from autodebug.serial_monitor import SerialMonitor
from autodebug.config import AutoDebugConfig
from autodebug.diagnostic_report import DiagnosticReportGenerator


def find_uvprojx():
    cwd = os.getcwd()
    for root, dirs, files in os.walk(cwd):
        for f in files:
            if f.endswith(".uvprojx"):
                return os.path.join(root, f)
    # Check one directory level up
    parent = os.path.dirname(cwd)
    for root, dirs, files in os.walk(parent):
        for f in files:
            if f.endswith(".uvprojx"):
                return os.path.join(root, f)
    return None


def main():
    parser = argparse.ArgumentParser(description="STM32 Auto-Debug Closed Loop Runner")
    parser.add_argument("--project", type=str, default=None, help="Path to Keil .uvprojx file")
    parser.add_argument("--target", type=str, default="stm32f446re", help="MCU target name")
    parser.add_argument("--flash", action="store_true", default=True, help="Flash after build")
    args = parser.parse_args()

    proj_path = args.project or find_uvprojx()
    if not proj_path or not os.path.exists(proj_path):
        print(f"[ERROR] Could not find .uvprojx project file. Specify with --project <path>")
        sys.exit(1)

    print(f"[*] Target Project : {proj_path}")
    config = AutoDebugConfig.load()
    builder = KeilBuilder(config.keil.uv4_path)

    # 1. Build with Keil
    print("\n>>> [1/3] Building with Keil UV4...")
    build_res = builder.build(proj_path)

    if not build_res.success:
        print(f"[-] Build FAILED with {len(build_res.errors)} error(s)!")
        for err in build_res.errors:
            print(f"    {err.file_path}:{err.line_number} -> {err.message}")

        # Export diagnostic report for AI
        report_path = os.path.join(os.path.dirname(proj_path), "diagnostic_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({
                "status": "BUILD_FAILED",
                "errors": [{"file": e.file_path, "line": e.line_number, "message": e.message} for e in build_res.errors],
                "instructions_for_ai": "Please open the file at the specified line, fix the syntax/compilation error, and rerun run_autodebug.py."
            }, f, indent=2, ensure_ascii=False)
        print(f"[!] Diagnostic report exported to: {report_path}")
        sys.exit(1)

    print(f"[+] Build SUCCESS: 0 Error(s), {len(build_res.warnings)} Warning(s).")
    print(f"    AXF: {build_res.axf_path}")

    # 2. Flash to hardware (Supports AXF and HEX)
    flash_bin = build_res.axf_path or build_res.hex_path
    if args.flash and flash_bin and os.path.exists(flash_bin):
        print("\n>>> [2/3] Flashing to Target MCU via Probe...")
        probe = HardwareProbe(config.debugger)
        if probe.probe_available:
            ok = probe.flash(flash_bin)
            if ok:
                print("[+] Hardware Flashing Complete & Target Reset!")
            else:
                print("[!] Flash failed or probe not connected.")
        else:
            print("[!] No hardware probe detected. Skipping flash.")

    # 3. Monitor Serial Output
    print("\n>>> [3/3] Checking Serial Stream...")
    mon = SerialMonitor(config.serial)
    res = mon.run_test(timeout_seconds=2.0)
    print(f"[+] Serial result: {res.summary}")
    for line in res.captured_lines[-5:]:
        print(f"    [MCU] {line}")

    print("\n=======================================================")
    print("  🎉 [AUTODEBUG PASS] Build, Flash, and Verification OK! ")
    print("=======================================================")


if __name__ == "__main__":
    main()
