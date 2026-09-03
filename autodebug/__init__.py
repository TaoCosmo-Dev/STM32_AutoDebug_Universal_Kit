"""
STM32 Auto-Debug & Self-Healing Pipeline
========================================
Closed-loop firmware build, flash, run, diagnose and AI repair for Cortex-M targets.

    from autodebug import AutoDebugEngine, AutoDebugConfig
    engine = AutoDebugEngine(AutoDebugConfig.load())
    result = engine.run_closed_loop("MDK-ARM/Project.uvprojx")
    print(result.final_status, result.exit_code)
"""
__version__ = "2.0.0"

from .config import AutoDebugConfig
from .builder import BuildResult, CompilerMessage, KeilBuilder
from .diagnostic_report import DiagnosticReport, DiagnosticReporter
from .engine import AutoDebugEngine, LoopResult
from .fault_analyzer import CortexMFaultAnalyzer, FaultDiagnostics
from .firmware_setup import check_firmware_contract, install_crash_tracer
from .hardware_probe import HardwareProbe, TargetCoreState
from .project_editor import KeilProjectEditor, disable_conflicting_fault_handlers
from .serial_monitor import CrashTelemetry, SerialMonitor, SerialTestResult
from .symbol_resolver import SourceLocation, SymbolResolver

__all__ = [
    "__version__",
    "AutoDebugConfig", "AutoDebugEngine", "LoopResult",
    "KeilBuilder", "BuildResult", "CompilerMessage",
    "HardwareProbe", "TargetCoreState",
    "KeilProjectEditor", "disable_conflicting_fault_handlers",
    "install_crash_tracer", "check_firmware_contract",
    "SerialMonitor", "SerialTestResult", "CrashTelemetry",
    "CortexMFaultAnalyzer", "FaultDiagnostics",
    "SymbolResolver", "SourceLocation",
    "DiagnosticReport", "DiagnosticReporter",
]
