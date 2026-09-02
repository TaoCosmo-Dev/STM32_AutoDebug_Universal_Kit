"""
STM32 Auto-Debug MCP server (Model Context Protocol, stdio transport).

A real MCP server: newline-delimited JSON-RPC 2.0 on stdin/stdout, implementing
initialize / tools/list / tools/call / ping. It has no third-party dependency beyond
what the kit already needs, so `python mcp_server.py` works the moment setup_env has run.

Register it in Claude Code / Cursor / Windsurf:

    {
      "mcpServers": {
        "stm32-copilot": {
          "command": "python",
          "args": ["<abs path>/mcp_server.py"]
        }
      }
    }

stdout carries protocol frames ONLY; every diagnostic goes to stderr.
"""
import contextlib
import io
import json
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autodebug.config import AutoDebugConfig, list_connected_probes
from autodebug.engine import AutoDebugEngine
from autodebug.fault_analyzer import CortexMFaultAnalyzer
from autodebug.hardware_probe import HardwareProbe
from autodebug.serial_monitor import SerialMonitor
from autodebug.symbol_resolver import SymbolResolver

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "stm32-autodebug", "version": "2.0.0"}


def log(msg: str) -> None:
    print(f"[mcp] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------------------

def tool_list_devices(_: Dict[str, Any]) -> Dict[str, Any]:
    probes = [{"description": getattr(p, "description", "?"), "unique_id": p.unique_id}
              for p in list_connected_probes()]
    return {"probes": probes, "serial_ports": SerialMonitor.describe_ports()}


def tool_build(args: Dict[str, Any]) -> Dict[str, Any]:
    config = AutoDebugConfig.load(args.get("config_path"))
    problems = config.preflight()
    if problems:
        return {"success": False, "errors": [], "failure_reason": "; ".join(problems)}
    engine = AutoDebugEngine(config, verbose=False)
    res = engine.builder.build(args["project_path"], args.get("target"),
                               rebuild=args.get("rebuild", False))
    return {
        "success": res.success,
        "return_code": res.return_code,
        "target": res.target_name,
        "available_targets": res.available_targets,
        "axf_path": res.axf_path,
        "warnings": len(res.warnings),
        "failure_reason": res.failure_reason,
        "errors": [{"file": e.file_path, "line": e.line_number,
                    "code": e.error_code, "message": e.message} for e in res.errors],
        "duration_seconds": round(res.duration_seconds, 2),
    }


def tool_flash(args: Dict[str, Any]) -> Dict[str, Any]:
    config = AutoDebugConfig.load(args.get("config_path"))
    if args.get("mcu"):
        config.debugger.target_override = args["mcu"]
    probe = HardwareProbe(config.debugger)
    try:
        res = probe.flash(args["image_path"], halt_after=args.get("halt_after", False))
        return {"success": res.success, "message": res.message, "halted": res.halted,
                "probe_id": res.probe_id, "target": res.target_name}
    finally:
        probe.close()


def tool_closed_loop(args: Dict[str, Any]) -> Dict[str, Any]:
    config = AutoDebugConfig.load(args.get("config_path"))
    if args.get("mcu"):
        config.debugger.target_override = args["mcu"]
    if args.get("port"):
        config.serial.port = args["port"]
    if args.get("baudrate"):
        config.serial.baudrate = int(args["baudrate"])
    if args.get("timeout_seconds"):
        config.serial.timeout_seconds = float(args["timeout_seconds"])

    engine = AutoDebugEngine(config, verbose=True)
    result = engine.run_closed_loop(args["project_path"], args.get("target"))
    report = result.last_report
    return {
        "status": result.final_status,
        "success": result.success,
        "exit_code": result.exit_code,
        "iterations_run": result.iterations_run,
        "report_path": result.report_path,
        "summary": report.summary if report else "",
        "signature": report.signature if report else "",
        "repeated_failure": report.repeated_failure if report else False,
        "next_actions": report.next_actions if report else [],
        "ai_repair_prompt": report.ai_repair_prompt if report else "",
        "serial_log_tail": report.serial_log_tail if report else "",
    }


def tool_read_registers(args: Dict[str, Any]) -> Dict[str, Any]:
    config = AutoDebugConfig.load(args.get("config_path"))
    if args.get("mcu"):
        config.debugger.target_override = args["mcu"]
    probe = HardwareProbe(config.debugger)
    try:
        state = probe.read_fault_registers()
        if not state:
            return {"halted": False, "error": "could not connect to or halt the target"}
        analyzer = CortexMFaultAnalyzer()
        out = {
            "halted": True,
            "faulted": state.faulted,
            "registers": {n: f"0x{v:08X}" for n, v in (
                ("PC", state.pc), ("LR", state.lr), ("SP", state.sp),
                ("MSP", state.msp), ("PSP", state.psp), ("xPSR", state.xpsr),
                ("CFSR", state.cfsr), ("HFSR", state.hfsr),
                ("MMFAR", state.mmfar), ("BFAR", state.bfar))},
            "bfar_valid": state.bfar_valid,
            "mmfar_valid": state.mmfar_valid,
            "flags": analyzer.decode_cfsr(state.cfsr) + analyzer.decode_hfsr(state.hfsr),
        }
        if args.get("axf_path"):
            resolver = SymbolResolver(args["axf_path"])
            diag = analyzer.from_core_state(state, resolver=resolver)
            out["root_cause"] = diag.root_cause
            out["suggested_fix"] = diag.suggested_fix
            if diag.fault_location:
                out["source"] = {
                    "file": diag.fault_location.file_path,
                    "line": diag.fault_location.line_number,
                    "function": diag.fault_location.function_name,
                    "snippet": diag.fault_location.source_context,
                }
        return out
    finally:
        probe.close()


def tool_diagnose_address(args: Dict[str, Any]) -> Dict[str, Any]:
    resolver = SymbolResolver(args["axf_path"], source_roots=args.get("source_roots") or [])
    analyzer = CortexMFaultAnalyzer()
    addr = int(str(args["address"]), 0)
    cfsr = int(str(args.get("cfsr", 0)), 0)
    hfsr = int(str(args.get("hfsr", 0)), 0)
    loc = resolver.resolve_address(addr)
    title, explanation = analyzer.classify_root_cause(cfsr, hfsr, args.get("fault_address"))
    return {
        "address": f"0x{addr:08X}",
        "dwarf_loaded": resolver.loaded,
        "file": loc.file_path if loc else None,
        "line": loc.line_number if loc else None,
        "function": loc.function_name if loc else None,
        "snippet": loc.source_context if loc else None,
        "cfsr_flags": analyzer.decode_cfsr(cfsr) + analyzer.decode_hfsr(hfsr),
        "root_cause": f"{title}: {explanation}" if cfsr or hfsr else None,
    }


def tool_inject(args: Dict[str, Any]) -> Dict[str, Any]:
    from inject_to_project import inject
    ok = inject(args["target_dir"])
    return {"injected": ok, "target": args["target_dir"]}


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "stm32_list_devices",
        "description": "List connected SWD debug probes and serial ports. Call this first when "
                       "hardware behaves unexpectedly.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_list_devices,
    },
    {
        "name": "stm32_build",
        "description": "Build a Keil MDK project with UV4 and return structured compiler and "
                       "linker errors with file/line. Does not touch hardware.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Path to the .uvprojx file"},
                "target": {"type": "string", "description": "Keil target name (multi-target projects)"},
                "rebuild": {"type": "boolean", "description": "Full rebuild instead of incremental"},
                "config_path": {"type": "string"},
            },
            "required": ["project_path"],
        },
        "handler": tool_build,
    },
    {
        "name": "stm32_flash",
        "description": "Flash an .axf/.hex/.bin to the target over SWD. Set halt_after=true to "
                       "keep the core halted so a log listener can attach without missing output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string"},
                "mcu": {"type": "string", "description": "pyOCD target name, e.g. stm32f407zg"},
                "halt_after": {"type": "boolean"},
                "config_path": {"type": "string"},
            },
            "required": ["image_path"],
        },
        "handler": tool_flash,
    },
    {
        "name": "stm32_closed_loop",
        "description": "The full loop: build -> flash (core held halted) -> open UART -> resume -> "
                       "watch for the pass token -> diagnose any HardFault down to the source line. "
                       "Returns a ready-to-act repair prompt. This is the main entry point.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"},
                "target": {"type": "string"},
                "mcu": {"type": "string"},
                "port": {"type": "string", "description": "COM port; omit to auto-detect"},
                "baudrate": {"type": "integer"},
                "timeout_seconds": {"type": "number"},
                "config_path": {"type": "string"},
            },
            "required": ["project_path"],
        },
        "handler": tool_closed_loop,
    },
    {
        "name": "stm32_read_registers",
        "description": "Halt the target and read core + SCB fault registers (CFSR/HFSR/BFAR/MMFAR). "
                       "Pass axf_path to also get the root cause and the faulting source line.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mcu": {"type": "string"},
                "axf_path": {"type": "string"},
                "config_path": {"type": "string"},
            },
        },
        "handler": tool_read_registers,
    },
    {
        "name": "stm32_diagnose_address",
        "description": "Map a raw address (PC/LR from a crash dump) to file, line and function via "
                       "DWARF, and decode CFSR/HFSR bits if supplied.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "axf_path": {"type": "string"},
                "address": {"type": "string", "description": "e.g. 0x08001234"},
                "cfsr": {"type": "string"},
                "hfsr": {"type": "string"},
                "source_roots": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["axf_path", "address"],
        },
        "handler": tool_diagnose_address,
    },
    {
        "name": "stm32_inject",
        "description": "Inject the AutoDebug toolchain (AGENTS.md, engine, crash tracer) into an "
                       "existing Keil/CubeMX project directory.",
        "inputSchema": {
            "type": "object",
            "properties": {"target_dir": {"type": "string"}},
            "required": ["target_dir"],
        },
        "handler": tool_inject,
    },
]

HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    t["name"]: t["handler"] for t in TOOLS}
TOOL_SCHEMAS = [{k: v for k, v in t.items() if k != "handler"} for t in TOOLS]


# --------------------------------------------------------------------------------------
# JSON-RPC plumbing
# --------------------------------------------------------------------------------------

def _result(msg_id: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": payload}


def _error(msg_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    handler = HANDLERS.get(name)
    if handler is None:
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
    try:
        # Engine internals log to stdout; stdout is the protocol channel, so divert it.
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            payload = handler(arguments or {})
        noise = buffer.getvalue()
        if noise:
            print(noise, file=sys.stderr, flush=True)
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        is_error = payload.get("success") is False or bool(payload.get("error"))
        return {"content": [{"type": "text", "text": text}], "isError": is_error}
    except Exception as e:
        log(traceback.format_exc())
        return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}


def handle_message(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return _result(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })
    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": TOOL_SCHEMAS})
    if method == "tools/call":
        return _result(msg_id, call_tool(params.get("name", ""), params.get("arguments") or {}))
    if method in ("resources/list", "prompts/list"):
        return _result(msg_id, {"resources": [], "prompts": []})
    if msg_id is None:
        return None
    return _error(msg_id, -32601, f"Method not found: {method}")


def serve() -> int:
    log(f"STM32 AutoDebug MCP server ready ({len(TOOLS)} tools, protocol {PROTOCOL_VERSION})")
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps(_error(None, -32700, f"Parse error: {e}")), flush=True)
            continue
        try:
            response = handle_message(msg)
        except Exception as e:
            log(traceback.format_exc())
            response = _error(msg.get("id"), -32603, f"Internal error: {e}")
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print(f"OK: {len(TOOLS)} tools registered -> {[t['name'] for t in TOOLS]}")
        sys.exit(0)
    sys.exit(serve())
