"""
Configuration loader and validator with auto-discovery for STM32 Auto-Debug pipeline.
Supports Windows Registry search, multi-drive Keil scanning, and auto probe enumeration.
"""
from dataclasses import dataclass, field
import os
import sys
import glob
from pathlib import Path
from typing import List, Optional
import yaml

try:
    import winreg
except ImportError:
    winreg = None


def find_keil_uv4() -> Optional[str]:
    """Auto-detect Keil UV4.exe installation path via Registry and common directories."""
    # 1. Search Windows Registry
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
                        # Path typically points to ARM directory (e.g. C:\Keil_v5\ARM)
                        base_dir = os.path.dirname(val.rstrip("\\/"))
                        candidate = os.path.join(base_dir, "UV4", "UV4.exe")
                        if os.path.exists(candidate):
                            return candidate
            except Exception:
                pass

    # 2. Search common disk drives and paths
    candidates = [
        r"C:\Keil_v5\UV4\UV4.exe",
        r"D:\Keil_v5\UV4\UV4.exe",
        r"E:\Keil_v5\UV4\UV4.exe",
        r"D:\keil5\UV4\UV4.exe",
        r"C:\keil5\UV4\UV4.exe",
        r"C:\Keil\UV4\UV4.exe",
        r"D:\Keil\UV4\UV4.exe",
        r"C:\Program Files (x86)\Keil_v5\UV4\UV4.exe",
        r"C:\Program Files\Keil_v5\UV4\UV4.exe",
    ]

    for c in candidates:
        if os.path.exists(c):
            return c

    # 3. Check system PATH
    for p in os.environ.get("PATH", "").split(os.pathsep):
        c = os.path.join(p.strip(' "'), "UV4.exe")
        if os.path.exists(c):
            return c

    return r"C:\Keil_v5\UV4\UV4.exe"


def find_fromelf(uv4_path: str) -> str:
    """Find fromelf.exe relative to UV4.exe or default locations."""
    if uv4_path and os.path.exists(uv4_path):
        base = os.path.dirname(os.path.dirname(uv4_path))
        # Check ARMCC / ARMCLANG
        armcc_fromelf = os.path.join(base, "ARM", "ARMCC", "bin", "fromelf.exe")
        if os.path.exists(armcc_fromelf):
            return armcc_fromelf
        armclang_fromelf = os.path.join(base, "ARM", "ARMCLANG", "bin", "fromelf.exe")
        if os.path.exists(armclang_fromelf):
            return armclang_fromelf

    return r"C:\Keil_v5\ARM\ARMCC\bin\fromelf.exe"


def get_first_connected_probe() -> Optional[str]:
    """Auto-detect the first connected CMSIS-DAP/ST-Link probe."""
    try:
        from pyocd.core.helpers import ConnectHelper
        probes = ConnectHelper.get_all_connected_probes()
        if probes:
            return probes[0].unique_id
    except Exception:
        pass
    return None


@dataclass
class KeilConfig:
    uv4_path: str = field(default_factory=find_keil_uv4)
    fromelf_path: str = ""

    def __post_init__(self):
        if not self.fromelf_path:
            self.fromelf_path = find_fromelf(self.uv4_path)


@dataclass
class DebuggerConfig:
    type: str = "pyocd"  # "pyocd", "jlink", "gdb"
    target_override: str = "stm32f446re"
    probe_id: Optional[str] = None
    jlink_path: str = r"C:\Program Files\SEGGER\JLink\JLink.exe"
    jlink_gdb_server: str = r"C:\Program Files\SEGGER\JLink\JLinkGDBServerCL.exe"

    def __post_init__(self):
        if not self.probe_id:
            self.probe_id = get_first_connected_probe()


@dataclass
class SerialConfig:
    port: str = "COM6"
    baudrate: int = 921600
    timeout_seconds: float = 10.0


@dataclass
class TestConfig:
    max_repair_iterations: int = 5
    pass_keywords: List[str] = field(default_factory=lambda: ["[ALL TESTS PASSED]", "TESTS_PASSED", "[PASS]"])
    fail_keywords: List[str] = field(default_factory=lambda: ["[TEST FAILED]", "ASSERTION_FAILED", "HardFault"])


@dataclass
class AutoDebugConfig:
    keil: KeilConfig = field(default_factory=KeilConfig)
    debugger: DebuggerConfig = field(default_factory=DebuggerConfig)
    serial: SerialConfig = field(default_factory=SerialConfig)
    test: TestConfig = field(default_factory=TestConfig)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "AutoDebugConfig":
        if config_path is None:
            # Check local directory first, then default
            local_yaml = os.path.join(os.getcwd(), "autodebug.config.yaml")
            default_yaml = os.path.join(os.path.dirname(__file__), "config.yaml")
            config_path = local_yaml if os.path.exists(local_yaml) else default_yaml

        if not os.path.exists(config_path):
            return cls()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            keil = KeilConfig(**data.get("keil", {}))
            debugger = DebuggerConfig(**data.get("debugger", {}))
            serial = SerialConfig(**data.get("serial", {}))
            test = TestConfig(**data.get("test", {}))
            return cls(keil=keil, debugger=debugger, serial=serial, test=test)
        except Exception:
            return cls()
