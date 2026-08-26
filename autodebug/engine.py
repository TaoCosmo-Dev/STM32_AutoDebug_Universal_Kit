"""
Master Orchestrator Engine for STM32 Automated Debug & Repair Loop.
"""
from dataclasses import dataclass
import os
import time
from typing import Callable, Optional
from .builder import BuildResult, KeilBuilder
from .config import AutoDebugConfig
from .diagnostic_report import DiagnosticReport, DiagnosticReporter
from .fault_analyzer import CortexMFaultAnalyzer, FaultDiagnostics
from .hardware_probe import HardwareProbe
from .serial_monitor import SerialMonitor, SerialTestResult
from .symbol_resolver import SymbolResolver


@dataclass
class LoopResult:
    success: bool
    iterations_run: int
    final_status: str
    last_report: Optional[DiagnosticReport] = None


class AutoDebugEngine:
    def __init__(self, config: Optional[AutoDebugConfig] = None):
        self.config = config or AutoDebugConfig.load()
        self.builder = KeilBuilder(self.config.keil.uv4_path)
        self.probe = HardwareProbe(self.config.debugger)
        self.serial_mon = SerialMonitor(
            port=self.config.serial.port,
            baudrate=self.config.serial.baudrate,
            timeout_seconds=self.config.serial.timeout_seconds
        )
        self.analyzer = CortexMFaultAnalyzer()

    def run_closed_loop(self,
                         uvprojx_path: str,
                         target_name: Optional[str] = None,
                         ai_patch_callback: Optional[Callable[[DiagnosticReport], bool]] = None) -> LoopResult:
        """
        Executes the autonomous loop:
        Compile -> Flash -> Run/Monitor -> Diagnose -> AI Patch -> Rebuild -> Repeat.
        """
        uvprojx_path = os.path.abspath(uvprojx_path)
        proj_dir = os.path.dirname(uvprojx_path)
        max_iters = self.config.test.max_repair_iterations
        last_report = None

        print(f"\n=======================================================")
        print(f"[*] Starting STM32 Auto-Debug Closed Loop for:")
        print(f"    Project: {uvprojx_path}")
        print(f"    Max Iterations: {max_iters}")
        print(f"=======================================================\n")

        for iteration in range(1, max_iters + 1):
            print(f"\n>>> [Iteration {iteration}/{max_iters}] Phase 1: Keil UV4 Compilation...")
            build_res = self.builder.build(uvprojx_path, target_name)

            if not build_res.success:
                print(f"[-] Compilation FAILED with {len(build_res.errors)} errors.")
                report = DiagnosticReporter.create_from_build_failure(build_res, iteration, uvprojx_path)
                last_report = report
                report_path = os.path.join(proj_dir, "diagnostic_report.json")
                report.save(report_path)
                print(f"[!] Saved diagnostic report to: {report_path}")

                if ai_patch_callback:
                    patched = ai_patch_callback(report)
                    if not patched:
                        print("[-] AI patch failed or was rejected. Terminating loop.")
                        return LoopResult(False, iteration, "AI_PATCH_FAILED", report)
                    continue
                else:
                    print("[!] AI patch callback not configured. Stopping at build error.")
                    return LoopResult(False, iteration, "BUILD_FAILED", report)

            print(f"[+] Compilation SUCCESS (0 Errors, {len(build_res.warnings)} Warnings).")
            print(f"[+] Output AXF: {build_res.axf_path}")

            # Phase 2: Symbol loading
            resolver = SymbolResolver(build_res.axf_path) if build_res.axf_path else None

            # Phase 3: Hardware Flash & Target Launch
            print(f"\n>>> [Iteration {iteration}/{max_iters}] Phase 2: Hardware Flashing & Reset...")
            flash_ok = self.probe.flash(build_res.axf_path)
            if not flash_ok:
                print("[-] Flashing failed or no hardware probe detected.")

            # Phase 4: Serial Test Monitoring
            print(f"\n>>> [Iteration {iteration}/{max_iters}] Phase 3: Runtime Test & Assertion Monitoring...")
            test_res = self.serial_mon.capture_run(
                pass_keywords=self.config.test.pass_keywords,
                fail_keywords=self.config.test.fail_keywords,
                on_line_cb=lambda line: print(f"  [MCU UART] {line}")
            )

            if test_res.passed:
                print(f"\n=======================================================")
                print(f"[+] ALL TESTS PASSED! Target firmware is healthy and verified.")
                print(f"=======================================================\n")
                return LoopResult(True, iteration, "TEST_PASSED", None)

            # Phase 5: Fault Detection & Root Cause Analysis
            print(f"\n>>> [Iteration {iteration}/{max_iters}] Phase 4: Exception Diagnosis & Stack Unwinding...")
            report = None
            if test_res.assertion_error and test_res.assert_file:
                print(f"[-] Assertion Failure detected: {test_res.assertion_error}")
                report = DiagnosticReporter.create_from_assertion(
                    test_res.assertion_error,
                    test_res.assert_file,
                    test_res.assert_line or 0,
                    iteration,
                    uvprojx_path,
                    test_res.raw_output
                )
            else:
                # Interrogate hardware probe for HardFault / SCB registers
                core_state = self.probe.read_fault_registers()
                if core_state and (core_state.cfsr != 0 or core_state.hfsr != 0):
                    diagnostics = self.analyzer.analyze(
                        cfsr=core_state.cfsr,
                        hfsr=core_state.hfsr,
                        sp=core_state.sp,
                        lr=core_state.lr,
                        stack_bytes=core_state.stack_bytes,
                        resolver=resolver,
                        raw_logs=test_res.raw_output
                    )
                    report = DiagnosticReporter.create_from_fault(diagnostics, iteration, uvprojx_path)
                else:
                    # Generic runtime failure or timeout
                    diag = FaultDiagnostics(
                        fault_type="Timeout / Test Failure",
                        root_cause="Test execution did not output pass token within timeout.",
                        raw_logs=test_res.raw_output
                    )
                    report = DiagnosticReporter.create_from_fault(diag, iteration, uvprojx_path)

            last_report = report
            report_path = os.path.join(proj_dir, "diagnostic_report.json")
            report.save(report_path)
            print(f"[!] Saved diagnostic report to: {report_path}")

            if ai_patch_callback:
                print(f"\n>>> [Iteration {iteration}/{max_iters}] Phase 5: Executing AI Code Self-Healing...")
                patched = ai_patch_callback(report)
                if not patched:
                    print("[-] AI patch failed. Terminating loop.")
                    return LoopResult(False, iteration, "AI_PATCH_FAILED", report)
            else:
                print("[!] Ready for AI repair. Waiting for source code modification.")
                return LoopResult(False, iteration, "FAULT_CAPTURED", report)

        return LoopResult(False, max_iters, "MAX_ITERATIONS_REACHED", last_report)
