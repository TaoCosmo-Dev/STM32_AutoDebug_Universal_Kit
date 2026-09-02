"""
Configuration loader and validator with auto-discovery for the STM32 Auto-Debug pipeline.

Design rule: a value written in YAML is a *hint*, never a hard override. If a configured
path does not exist on this machine, auto-discovery takes over, so one config.yaml works
unchanged on any PC.
"""
from dataclasses import dataclass, field, fields as dataclass_fields
import os
import sys
from typing import Any, List, Optional
import yaml

try:
    import winreg
except ImportError:
    winreg = None


def _warn(msg: str) -> None:
    print(f"[config] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------------------
# Toolchain auto-discovery
# --------------------------------------------------------------------------------------

KEIL_CANDIDATES = [
    r"C:\Keil_v5\UV4\UV4.exe",
    r"D:\Keil_v5\UV4\UV4.exe",
    r"E:\Keil_v5\UV4\UV4.exe",
    r"D:\keil5\UV4\UV4.exe",
    r"C:\keil5\UV4\UV4.exe",
    r"E:\keil5\UV4\UV4.exe",
    r"C:\Keil\UV4\UV4.exe",
    r"D:\Keil\UV4\UV4.exe",
    r"C:\Program Files (x86)\Keil_v5\UV4\UV4.exe",
    r"C:\Program Files\Keil_v5\UV4\UV4.exe",
]


def find_keil_uv4() -> Optional[str]:
    """Auto-detect Keil UV4.exe via Registry, common install dirs, then PATH.

    Returns None when Keil genuinely is not installed, so callers can print a clear
    error instead of launching a path that does not exist.
    """
    if winreg:
        reg_keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Keil\ARM"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Keil\ARM"),
            (winreg.HKEY_CURRENT_USER, r"Software\Keil\UV4"),
        ]
        for root, key_path in reg_keys:
            try:
                with winreg.OpenKey(root, key_path) as k:
                    val, _ = winreg.QueryValueEx(k, "PATH")
                    if val:
                        # Registry PATH usually points at the ARM directory (C:\Keil_v5\ARM)
                        base_dir = os.path.dirname(val.rstrip("\\/"))
                        candidate = os.path.join(base_dir, "UV4", "UV4.exe")
                        if os.path.exists(candidate):
                            return candidate
            except Exception:
                pass

    for c in KEIL_CANDIDATES:
        if os.path.exists(c):
            return c

    for p in os.environ.get("PATH", "").split(os.pathsep):
        c = os.path.join(p.strip(' "'), "UV4.exe")
        if os.path.exists(c):
            return c

    return None


def find_fromelf(uv4_path: Optional[str]) -> Optional[str]:
    """Find fromelf.exe next to a known UV4.exe."""
    if uv4_path and os.path.exists(uv4_path):
        base = os.path.dirname(os.path.dirname(uv4_path))
        for sub in ("ARMCC", "ARMCLANG"):
            cand = os.path.join(base, "ARM", sub, "bin", "fromelf.exe")
            if os.path.exists(cand):
                return cand
    return None


def list_connected_probes() -> List[Any]:
    """Enumerate connected CMSIS-DAP / ST-Link probes without ever blocking on a prompt."""
    try:
        from pyocd.core.helpers import ConnectHelper
    except Exception:
        return []
    for kwargs in ({"blocking": False, "print_wait_message": False}, {"blocking": False}, {}):
        try:
            return list(ConnectHelper.get_all_connected_probes(**kwargs))
        except TypeError:
            continue
        except Exception:
            return []
    return []


def get_first_connected_probe() -> Optional[str]:
    """Unique id of the first connected probe, or None when nothing is plugged in."""
    probes = list_connected_probes()
    return probes[0].unique_id if probes else None


# --------------------------------------------------------------------------------------
# Config sections
# --------------------------------------------------------------------------------------

@dataclass
class KeilConfig:
    uv4_path: Optional[str] = None
    fromelf_path: Optional[str] = None

    def __post_init__(self):
        # A configured path that does not exist here falls back to discovery.
        if self.uv4_path and not os.path.exists(self.uv4_path):
            _warn(f"configured uv4_path not found: {self.uv4_path} -> auto-detecting")
            self.uv4_path = None
        if not self.uv4_path:
            self.uv4_path = find_keil_uv4()
        if self.fromelf_path and not os.path.exists(self.fromelf_path):
            self.fromelf_path = None
        if not self.fromelf_path:
            self.fromelf_path = find_fromelf(self.uv4_path)


@dataclass
class DebuggerConfig:
    type: str = "pyocd"                  # "pyocd" | "jlink"
    target_override: Optional[str] = None
    probe_id: Optional[str] = None       # None = first connected probe, never prompt
    frequency_hz: int = 4000000
    connect_mode: str = "under-reset"    # survives firmware that reconfigures the SWD pins
    jlink_path: str = r"C:\Program Files\SEGGER\JLink\JLink.exe"
    jlink_gdb_server: str = r"C:\Program Files\SEGGER\JLink\JLinkGDBServerCL.exe"
    flash_address: int = 0x08000000      # J-Link raw flash base

    def resolve_probe_id(self) -> Optional[str]:
        """Resolved lazily: probes get plugged in after the config is loaded."""
        if self.probe_id:
            return self.probe_id
        return get_first_connected_probe()


@dataclass
class BuildConfig:
    timeout_seconds: float = 600.0       # a cold full rebuild of a HAL project blows past 120s
    rebuild: bool = False                # False = incremental (-b), True = full rebuild (-r)
    log_encodings: List[str] = field(default_factory=lambda: ["utf-8", "gbk", "cp936", "latin-1"])
    kill_uv4_on_timeout: bool = True     # a modal Keil dialog would otherwise lock the project
    fail_on_stale_axf: bool = True       # never flash an image this build did not produce


@dataclass
class SerialConfig:
    port: Optional[str] = None           # None = auto-sniff the USB-UART COM port
    baudrate: int = 115200
    timeout_seconds: float = 15.0
    boot_grace_seconds: float = 0.2      # settle time after resume before the capture window
    exclude_keywords: List[str] = field(default_factory=lambda: ["bluetooth", "\u84dd\u7259"])
    prefer_keywords: List[str] = field(default_factory=lambda: [
        "ch340", "ch343", "cp210", "ft232", "ftdi", "pl2303",
        "usb-serial", "usb serial", "usb-enhanced-serial",
        "stlink", "st-link", "daplink", "cmsis-dap",
    ])


@dataclass
class TestConfig:
    max_repair_iterations: int = 5
    pass_keywords: List[str] = field(default_factory=lambda: [
        "[ALL TESTS PASSED]", "TESTS_PASSED", "[PASS]",
    ])
    fail_keywords: List[str] = field(default_factory=lambda: [
        "[TEST FAILED]", "ASSERTION_FAILED", "[AUTODEBUG_CRASH_START]",
    ])
    crash_begin_marker: str = "[AUTODEBUG_CRASH_START]"
    crash_end_marker: str = "[AUTODEBUG_CRASH_END]"


@dataclass
class LoopConfig:
    """Guard rails that stop the self-healing loop from burning iterations or the repo."""
    git_snapshot: bool = True            # restore point before each AI patch
    archive_reports: bool = True         # keep every iteration, not just the last
    archive_dir: str = ".autodebug"
    stall_threshold: int = 2             # identical failure signature N times -> escalate
    halt_target_on_finish: bool = False  # leave the board running after a green run


@dataclass
class AutoDebugConfig:
    keil: KeilConfig = field(default_factory=KeilConfig)
    debugger: DebuggerConfig = field(default_factory=DebuggerConfig)
    build: BuildConfig = field(default_factory=BuildConfig)
    serial: SerialConfig = field(default_factory=SerialConfig)
    test: TestConfig = field(default_factory=TestConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)
    source_path: Optional[str] = None

    @staticmethod
    def _section(cls_, data: Any, name: str):
        """Build one section, ignoring unknown keys loudly instead of silently dying."""
        if not isinstance(data, dict):
            _warn(f"section '{name}' is not a mapping, using defaults")
            return cls_()
        known = {f.name for f in dataclass_fields(cls_)}
        unknown = set(data) - known
        if unknown:
            _warn(f"section '{name}': unknown keys ignored {sorted(unknown)}")
        clean = {k: v for k, v in data.items() if k in known and v is not None}
        try:
            return cls_(**clean)
        except Exception as e:
            _warn(f"section '{name}' rejected ({e}), using defaults")
            return cls_()

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "AutoDebugConfig":
        """Explicit path > ./autodebug.config.yaml > packaged autodebug/config.yaml."""
        if config_path is None:
            local_yaml = os.path.join(os.getcwd(), "autodebug.config.yaml")
            default_yaml = os.path.join(os.path.dirname(__file__), "config.yaml")
            config_path = local_yaml if os.path.exists(local_yaml) else default_yaml

        if not os.path.exists(config_path):
            return cls()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            _warn(f"failed to parse {config_path}: {e} -> using defaults")
            return cls()

        if not isinstance(data, dict):
            _warn(f"{config_path} is not a YAML mapping -> using defaults")
            return cls()

        return cls(
            keil=cls._section(KeilConfig, data.get("keil") or {}, "keil"),
            debugger=cls._section(DebuggerConfig, data.get("debugger") or {}, "debugger"),
            build=cls._section(BuildConfig, data.get("build") or {}, "build"),
            serial=cls._section(SerialConfig, data.get("serial") or {}, "serial"),
            test=cls._section(TestConfig, data.get("test") or {}, "test"),
            loop=cls._section(LoopConfig, data.get("loop") or {}, "loop"),
            source_path=config_path,
        )

    def preflight(self) -> List[str]:
        """Blocking problems; an empty list means the pipeline can run."""
        problems = []
        if not self.keil.uv4_path or not os.path.exists(self.keil.uv4_path):
            problems.append(
                "Keil UV4.exe not found. Install Keil MDK, or set keil.uv4_path in autodebug.config.yaml."
            )
        return problems
