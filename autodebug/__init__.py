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
from .hardware_probe import HardwareProbe, TargetCoreState
from .serial_monitor import CrashTelemetry, SerialMonitor, SerialTestResult
from .symbol_resolver import SourceLocation, SymbolResolver

__all__ = [
    "__version__",
    "AutoDebugConfig", "AutoDebugEngine", "LoopResult",
    "KeilBuilder", "BuildResult", "CompilerMessage",
    "HardwareProbe", "TargetCoreState",
    "SerialMonitor", "SerialTestResult", "CrashTelemetry",
    "CortexMFaultAnalyzer", "FaultDiagnostics",
    "SymbolResolver", "SourceLocation",
    "DiagnosticReport", "DiagnosticReporter",
]
