"""
Master orchestrator for the STM32 build -> flash -> run -> diagnose -> repair loop.

Ordering is the whole trick. The sequence is:

    build -> verify a FRESH image -> open probe -> clear stale fault bits ->
    flash and HOLD THE CORE HALTED -> open the serial port -> resume ->
    watch for the verdict -> diagnose from UART, else from SWD -> report

Flashing with the core halted and only resuming after the monitor is listening is what
makes the pass token reliable; the previous design resumed inside flash() and lost the
firmware's whole startup banner before pyserial had the port open.

The loop also survives being driven from outside: when no ai_patch_callback is given it
runs exactly one pass, persists its state to .autodebug/state.json, and the next
invocation picks the iteration counter and stall detection back up.
"""
from dataclasses import dataclass, field
import json
import os
import subprocess
import time
from typing import Callable, List, Optional

from .builder import BuildResult, KeilBuilder
from .config import AutoDebugConfig
from .diagnostic_report import (
    DiagnosticReport, DiagnosticReporter,
    STATUS_BUILD_FAILED, STATUS_FLASH_FAILED, STATUS_HARD_FAULT,
    STATUS_ASSERTION_FAILED, STATUS_PASSED, STATUS_SERIAL_UNAVAILABLE, STATUS_TIMEOUT,
)
from .fault_analyzer import CortexMFaultAnalyzer
from .hardware_probe import HardwareProbe
from .serial_monitor import SerialMonitor
from .symbol_resolver import SymbolResolver

STATUS_STALLED = "STALLED"
STATUS_CONFIG_ERROR = "CONFIG_ERROR"

EXIT_CODES = {
    STATUS_PASSED: 0,
    STATUS_BUILD_FAILED: 1,
    STATUS_FLASH_FAILED: 2,
    STATUS_HARD_FAULT: 3,
    STATUS_ASSERTION_FAILED: 3,
    STATUS_TIMEOUT: 4,
    STATUS_SERIAL_UNAVAILABLE: 4,
    STATUS_STALLED: 5,
    STATUS_CONFIG_ERROR: 6,
}


@dataclass
class LoopResult:
    success: bool
    iterations_run: int
    final_status: str
    last_report: Optional[DiagnosticReport] = None
    report_path: Optional[str] = None
    messages: List[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.final_status, 1)


class AutoDebugEngine:
    def __init__(self, config: Optional[AutoDebugConfig] = None, verbose: bool = True):
        self.config = config or AutoDebugConfig.load()
        self.verbose = verbose
        self.builder = KeilBuilder(self.config.keil.uv4_path, self.config.build)
        self.probe = HardwareProbe(self.config.debugger)
        self.analyzer = CortexMFaultAnalyzer()
        self.serial_mon = SerialMonitor(self.config.serial)

    # ------------------------------------------------------------------ output helpers

    def _log(self, msg: str = "") -> None:
        if self.verbose:
            print(msg, flush=True)

    def _banner(self, text: str) -> None:
        self._log("\n" + "=" * 63)
        self._log(text)
        self._log("=" * 63)

    # ------------------------------------------------------------------ persistent state

    def _state_dir(self, proj_dir: str) -> str:
        path = os.path.join(proj_dir, self.config.loop.archive_dir)
        os.makedirs(path, exist_ok=True)
        return path

    def _load_state(self, proj_dir: str) -> dict:
        path = os.path.join(proj_dir, self.config.loop.archive_dir, "state.json")
        if not os.path.exists(path):
            return {"iteration": 0, "last_signature": None, "repeat_count": 0}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "iteration": int(data.get("iteration", 0)),
                "last_signature": data.get("last_signature"),
                "repeat_count": int(data.get("repeat_count", 0)),
            }
        except Exception:
            return {"iteration": 0, "last_signature": None, "repeat_count": 0}

    def _save_state(self, proj_dir: str, state: dict) -> None:
        try:
            path = os.path.join(self._state_dir(proj_dir), "state.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _persist_report(self, proj_dir: str, report: DiagnosticReport) -> str:
        """Latest report at the project root (the AI contract) + an immutable archive copy."""
        latest = os.path.join(proj_dir, "diagnostic_report.json")
        report.save(latest)
        if self.config.loop.archive_reports:
            try:
                archive = os.path.join(
                    self._state_dir(proj_dir),
                    f"iter_{report.iteration:02d}_{report.status}.json")
                report.save(archive)
                with open(os.path.join(self._state_dir(proj_dir), "history.jsonl"),
                          "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "timestamp": report.timestamp,
                        "iteration": report.iteration,
                        "status": report.status,
                        "summary": report.summary,
                        "signature": report.signature,
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
        return latest

    # ------------------------------------------------------------------ git restore point

    def _git_snapshot(self, proj_dir: str, iteration: int) -> Optional[str]:
        """Capture a non-destructive restore point before the AI edits anything.

        `git stash create` records the working tree in a dangling commit without touching
        the index, the working tree, or the branch. A tag keeps it from being GC'd.
        """
        if not self.config.loop.git_snapshot:
            return None

        def git(*args) -> Optional[str]:
            try:
                res = subprocess.run(["git", "-C", proj_dir, *args],
                                     capture_output=True, text=True, timeout=30)
                return res.stdout.strip() if res.returncode == 0 else None
            except Exception:
                return None

        if git("rev-parse", "--is-inside-work-tree") != "true":
            return None
        sha = git("stash", "create") or git("rev-parse", "HEAD")
        if not sha:
            return None
        git("tag", "-f", f"autodebug/iter-{iteration:02d}", sha)
        self._log(f"[存档] 已创建还原点 autodebug/iter-{iteration:02d} -> {sha[:10]} "
                  f"（回退命令：git checkout {sha[:10]} -- .）")
        return sha

    # ------------------------------------------------------------------ one pass

    def run_once(self, uvprojx_path: str, target_name: Optional[str] = None,
                 iteration: int = 1) -> DiagnosticReport:
        """Build, flash, run and diagnose exactly once. Never raises for expected failures."""
        uvprojx_path = os.path.abspath(uvprojx_path)
        proj_dir = os.path.dirname(uvprojx_path)

        # ---- Phase 1: compile -------------------------------------------------------
        self._log(f"\n>>> [第 {iteration} 轮] 步骤 1/4  正在用 Keil 编译 ...")
        build_res: BuildResult = self.builder.build(uvprojx_path, target_name)
        if not build_res.success:
            self._log(f"[-] 编译失败：{build_res.failure_reason}")
            for err in build_res.errors[:12]:
                self._log(f"    {err.file_path}:{err.line_number} {err.error_code} {err.message}")
            return DiagnosticReporter.create_from_build_failure(build_res, iteration, uvprojx_path)

        self._log(f"[+] 编译通过  0 Error，{len(build_res.warnings)} Warning，"
                  f"耗时 {build_res.duration_seconds:.1f}s")
        self._log(f"    固件文件：{build_res.axf_path}")

        resolver = SymbolResolver(build_res.axf_path, source_roots=[proj_dir]) \
            if build_res.axf_path else None
        if resolver and not resolver.loaded:
            self._log("[!] 固件里没有调试信息，无法把崩溃地址映射到源码行"
                       "（Keil: Options -> Output -> 勾选 Debug Information）。")

        # ---- Phase 2: flash, core held halted ---------------------------------------
        self._log(f"\n>>> [第 {iteration} 轮] 步骤 2/4  正在烧录到板子（烧完先让 CPU 停住不跑）...")
        if not self.probe.probe_available:
            msg = "没有检测到下载器（ST-Link / DAP-Link / CMSIS-DAP）"
            self._log(f"[-] 无法烧录：{msg}")
            return DiagnosticReporter.create_from_flash_failure(
                msg, iteration, uvprojx_path, self.probe.describe_probes())

        self.probe.open()
        self.probe.clear_fault_registers()   # never inherit last iteration's crash bits
        flash_res = self.probe.flash(build_res.axf_path, halt_after=True)
        if not flash_res.success:
            self._log(f"[-] 烧录失败：{flash_res.message}")
            return DiagnosticReporter.create_from_flash_failure(
                flash_res.message, iteration, uvprojx_path, self.probe.describe_probes())
        self._log(f"[+] 烧录成功（下载器 {flash_res.probe_id}，芯片 {flash_res.target_name}），"
                  f"CPU 已停在复位入口等待放行。")

        # ---- Phase 3: listen first, then release the core ---------------------------
        self._log(f"\n>>> [第 {iteration} 轮] 步骤 3/4  先打开串口监听，再放 CPU 运行 ...")
        serial_ok = self.serial_mon.open()
        if serial_ok:
            self._log(f"[+] 已监听串口 {self.serial_mon.port} @ {self.config.serial.baudrate}")
        else:
            self._log(f"[!] 串口不可用：{self.serial_mon.open_error} "
                      f"（改为只靠下载器读芯片来诊断）")

        if flash_res.halted:
            self.probe.resume()
        time.sleep(self.config.serial.boot_grace_seconds)

        test_res = self.serial_mon.wait_for_result(
            pass_keywords=self.config.test.pass_keywords,
            fail_keywords=self.config.test.fail_keywords,
            crash_begin=self.config.test.crash_begin_marker,
            crash_end=self.config.test.crash_end_marker,
            on_line_cb=lambda line: self._log(f"  [MCU] {line}"),
        )
        self.serial_mon.close()

        # ---- Phase 4: verdict and root cause ----------------------------------------
        self._log(f"\n>>> [第 {iteration} 轮] 步骤 4/4  判定结果并分析根本原因 ...")

        if test_res.passed:
            self._banner(f"[+] 实机测试通过！（收到通过信号：{test_res.matched_keyword}）")
            if self.config.loop.halt_target_on_finish:
                self.probe.read_fault_registers()
            return DiagnosticReporter.create_success(
                iteration, uvprojx_path, test_res.raw_output,
                build_res.axf_path, len(build_res.warnings))

        # 4a. The firmware described its own crash over UART - no probe needed.
        if test_res.crash:
            self._log("[-] 板子崩溃了（固件通过串口自报了故障现场）")
            diag = self.analyzer.from_crash_telemetry(
                test_res.crash, resolver=resolver, raw_logs=test_res.raw_output)
            self._log(f"    根本原因：{diag.root_cause}")
            return DiagnosticReporter.create_from_fault(diag, iteration, uvprojx_path)

        # 4b. An assertion fired.
        if test_res.assert_file:
            self._log(f"[-] 断言失败：{test_res.assert_file} 第 {test_res.assert_line} 行")
            snippet = None
            if resolver:
                _, snippet = resolver._extract_source_context(
                    test_res.assert_file, test_res.assert_line or 0)
            return DiagnosticReporter.create_from_assertion(
                test_res.assertion_error or "assertion failed",
                test_res.assert_file, test_res.assert_line or 0,
                iteration, uvprojx_path, test_res.raw_output, snippet)

        # 4c. Silent death: interrogate the core over SWD.
        core_state = self.probe.read_fault_registers()
        if core_state and core_state.faulted:
            self._log(f"[-] 芯片故障寄存器已置位（CFSR=0x{core_state.cfsr:08X}，"
                      f"HFSR=0x{core_state.hfsr:08X}），正在还原崩溃现场 ...")
            diag = self.analyzer.from_core_state(
                core_state, resolver=resolver, raw_logs=test_res.raw_output)
            self._log(f"    根本原因：{diag.root_cause}")
            return DiagnosticReporter.create_from_fault(diag, iteration, uvprojx_path)

        # 4d. No fault, no token: report honestly, with CPU liveness telemetry.
        cpu_running = self.probe.is_target_running()
        self._log(f"[-] 等了 {self.config.serial.timeout_seconds:.0f}s 没等到通过信号"
                  f"（CPU 是否在跑：{ {True: '是', False: '否', None: '未知'}[cpu_running] }）。")
        return DiagnosticReporter.create_from_timeout(
            iteration, uvprojx_path, test_res.raw_output,
            self.config.serial.timeout_seconds, test_res.port, cpu_running,
            self.config.test.pass_keywords,
            serial_ok=test_res.opened, open_error=test_res.open_error)

    # ------------------------------------------------------------------ the loop

    def run_closed_loop(self,
                        uvprojx_path: str,
                        target_name: Optional[str] = None,
                        ai_patch_callback: Optional[Callable[[DiagnosticReport], bool]] = None
                        ) -> LoopResult:
        """Run the loop.

        With `ai_patch_callback` the loop iterates in-process until it passes, stalls, or
        exhausts max_repair_iterations. Without one it performs a single pass and persists
        state, so an AI agent driving the script from outside still gets iteration
        numbering and stall detection across separate invocations.
        """
        uvprojx_path = os.path.abspath(uvprojx_path)
        proj_dir = os.path.dirname(uvprojx_path)
        messages: List[str] = []

        problems = self.config.preflight()
        if problems:
            for p in problems:
                self._log(f"[x] {p}")
            report = DiagnosticReporter.create_from_build_failure(
                BuildResult(success=False, return_code=-1, target_name="", axf_path=None,
                            hex_path=None, failure_reason="; ".join(problems)),
                1, uvprojx_path)
            path = self._persist_report(proj_dir, report)
            return LoopResult(False, 0, STATUS_CONFIG_ERROR, report, path, problems)

        detected = self.builder.get_device_name(uvprojx_path)
        if detected and not self.config.debugger.target_override:
            self.config.debugger.target_override = detected

        state = self._load_state(proj_dir)
        max_iters = self.config.test.max_repair_iterations
        mode = "全自主循环" if ai_patch_callback else "单轮（由 AI 编辑器驱动）"

        self._banner(
            f"STM32 全自动开发闭环\n"
            f"  工程：{uvprojx_path}\n"
            f"  芯片：{self.config.debugger.target_override or 'cortex_m'}\n"
            f"  模式：{mode}\n"
            f"  预算：最多自动修复 {max_iters} 轮")

        last_report: Optional[DiagnosticReport] = None
        report_path: Optional[str] = None
        iterations_run = 0

        try:
            while True:
                state["iteration"] += 1
                iteration = state["iteration"]
                iterations_run += 1

                report = self.run_once(uvprojx_path, target_name, iteration)
                last_report = report

                # ---- stall detection ------------------------------------------------
                if report.signature == state.get("last_signature") and report.status != STATUS_PASSED:
                    state["repeat_count"] = state.get("repeat_count", 0) + 1
                else:
                    state["repeat_count"] = 1
                state["last_signature"] = report.signature
                report.repeated_failure = state["repeat_count"] >= 2

                if report.status == STATUS_PASSED:
                    state = {"iteration": 0, "last_signature": None, "repeat_count": 0}
                    self._save_state(proj_dir, state)
                    report_path = self._persist_report(proj_dir, report)
                    return LoopResult(True, iterations_run, STATUS_PASSED, report, report_path, messages)

                report_path = self._persist_report(proj_dir, report)
                self._save_state(proj_dir, state)
                self._log(f"[!] 诊断报告已写入：{report_path}")

                stalled = state["repeat_count"] >= self.config.loop.stall_threshold
                if stalled:
                    msg = (f"同一个失败已连续出现 {state['repeat_count']} 次"
                           f"（{report.signature}）。停止自动修复，交由人工判断，"
                           f"避免继续消耗迭代次数做无效改动。")
                    messages.append(msg)
                    self._log(f"[x] 卡住了：{msg}")
                    return LoopResult(False, iterations_run, STATUS_STALLED,
                                      report, report_path, messages)

                # Flash / config problems are environmental: patching source cannot fix them.
                if report.status == STATUS_FLASH_FAILED:
                    return LoopResult(False, iterations_run, STATUS_FLASH_FAILED,
                                      report, report_path, messages)

                if ai_patch_callback is None:
                    return LoopResult(False, iterations_run, report.status,
                                      report, report_path, messages)

                if iteration >= max_iters:
                    self._log(f"[x] 已用完 {max_iters} 轮自动修复次数。")
                    return LoopResult(False, iterations_run, report.status,
                                      report, report_path, messages)

                self._git_snapshot(proj_dir, iteration)
                self._log(f"\n>>> [第 {iteration} 轮] AI 正在自动修复代码 ...")
                if not ai_patch_callback(report):
                    self._log("[-] AI 修复失败或被拒绝，停止。")
                    return LoopResult(False, iterations_run, report.status,
                                      report, report_path, messages)
        finally:
            self.serial_mon.close()
            self.probe.close()
