"""
Keil MDK UV4 command-line builder and compiler error parser.
"""
from dataclasses import dataclass, field
import os
import re
import subprocess
import time
from typing import List, Optional
import xml.etree.ElementTree as ET


@dataclass
class CompilerMessage:
    file_path: str
    line_number: int
    column: Optional[int]
    severity: str  # "error", "warning"
    error_code: str
    message: str


@dataclass
class BuildResult:
    success: bool
    return_code: int
    target_name: str
    axf_path: Optional[str]
    hex_path: Optional[str]
    errors: List[CompilerMessage] = field(default_factory=list)
    warnings: List[CompilerMessage] = field(default_factory=list)
    raw_log: str = ""
    duration_seconds: float = 0.0


class KeilBuilder:
    def __init__(self, uv4_path: str = r"D:\keil5\UV4\UV4.exe"):
        self.uv4_path = uv4_path
        if not os.path.exists(self.uv4_path):
            # Fallback search
            for fallback in [r"C:\Keil_v5\UV4\UV4.exe", r"D:\keil5\UV4\UV4.exe"]:
                if os.path.exists(fallback):
                    self.uv4_path = fallback
                    break

    def get_output_paths(self, uvprojx_path: str, target_name: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        """Parses .uvprojx XML to locate the output directory and executable filename."""
        try:
            tree = ET.parse(uvprojx_path)
            root = tree.getroot()
            proj_dir = os.path.dirname(os.path.abspath(uvprojx_path))

            # Look through Targets
            for target in root.findall(".//Target"):
                t_name = target.findtext("TargetName", "")
                if target_name and t_name != target_name:
                    continue

                out_dir = target.findtext(".//TargetOption/TargetCommonOption/OutputDirectory", "Objects\\")
                out_name = target.findtext(".//TargetOption/TargetCommonOption/OutputName", "")
                create_hex = target.findtext(".//TargetOption/TargetCommonOption/CreateHexFile", "0")

                abs_out_dir = os.path.normpath(os.path.join(proj_dir, out_dir))
                axf_path = os.path.join(abs_out_dir, f"{out_name}.axf")
                hex_path = os.path.join(abs_out_dir, f"{out_name}.hex") if create_hex == "1" else None

                return (axf_path if os.path.exists(axf_path) else axf_path,
                        hex_path if hex_path and os.path.exists(hex_path) else None)
        except Exception:
            pass

        # Fallback to standard convention
        proj_dir = os.path.dirname(os.path.abspath(uvprojx_path))
        base_name = os.path.splitext(os.path.basename(uvprojx_path))[0]
        for candidate_dir in ["Objects", "Output", "build"]:
            cand_axf = os.path.join(proj_dir, candidate_dir, f"{base_name}.axf")
            if os.path.exists(cand_axf):
                return cand_axf, os.path.join(proj_dir, candidate_dir, f"{base_name}.hex")

        return None, None

    def build(self, uvprojx_path: str, target_name: Optional[str] = None, rebuild: bool = False) -> BuildResult:
        """
        Executes Keil UV4 CLI build.
        Command syntax: UV4.exe -b <project.uvprojx> -j0 -t <target> -o <build.log>
        Keil return codes:
          0: No errors or warnings
          1: Warnings only
          2: Errors occurred
          3+: Fatal fatal error / UV4 crash
        """
        uvprojx_path = os.path.abspath(uvprojx_path)
        proj_dir = os.path.dirname(uvprojx_path)
        log_file = os.path.join(proj_dir, "build_autodebug.log")

        flag = "-r" if rebuild else "-b"
        cmd = [self.uv4_path, flag, uvprojx_path, "-j0", "-o", log_file]
        if target_name:
            cmd.extend(["-t", target_name])

        start_time = time.time()
        try:
            # UV4 writes log to -o file
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            ret_code = proc.returncode
        except Exception as e:
            return BuildResult(
                success=False,
                return_code=-1,
                target_name=target_name or "Default",
                axf_path=None,
                hex_path=None,
                raw_log=f"Execution error invoking Keil UV4: {e}",
                duration_seconds=time.time() - start_time
            )

        # Read the generated build log
        log_content = ""
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    log_content = f.read()
            except Exception:
                with open(log_file, "r", encoding="gbk", errors="replace") as f:
                    log_content = f.read()

        errors, warnings = self._parse_log_messages(log_content, proj_dir)
        axf_path, hex_path = self.get_output_paths(uvprojx_path, target_name)
        duration = time.time() - start_time

        # Keil returns 0 (Clean) or 1 (Warnings only) for successful build
        success = (ret_code in [0, 1]) and (len(errors) == 0) and (axf_path is not None and os.path.exists(axf_path))

        return BuildResult(
            success=success,
            return_code=ret_code,
            target_name=target_name or "Default",
            axf_path=axf_path,
            hex_path=hex_path,
            errors=errors,
            warnings=warnings,
            raw_log=log_content,
            duration_seconds=duration
        )

    def _parse_log_messages(self, log_content: str, proj_dir: str) -> tuple[List[CompilerMessage], List[CompilerMessage]]:
        """Parses ARMCC and ARMCLANG compiler error and warning formats."""
        errors: List[CompilerMessage] = []
        warnings: List[CompilerMessage] = []

        # ARMCC format: "file.c", line 123: Error: #20: identifier "x" is undefined
        # ARMCLANG format: file.c:123:10: error: use of undeclared identifier 'x'
        armcc_pattern = re.compile(r'\"([^\"]+)\",\s*line\s*(\d+):\s*(Error|Warning):\s*#?([A-Za-z0-9_\-]+):\s*(.+)')
        armclang_pattern = re.compile(r'([^:\n\r]+):(\d+):(\d+):\s*(error|warning):\s*(.+)')

        for line in log_content.splitlines():
            line = line.strip()
            # Try ARMCC
            m1 = armcc_pattern.search(line)
            if m1:
                fpath, lnum, sev, code, msg = m1.groups()
                abs_fpath = os.path.normpath(os.path.join(proj_dir, fpath)) if not os.path.isabs(fpath) else fpath
                c_msg = CompilerMessage(
                    file_path=abs_fpath,
                    line_number=int(lnum),
                    column=None,
                    severity=sev.lower(),
                    error_code=code,
                    message=msg.strip()
                )
                if sev.lower() == "error":
                    errors.append(c_msg)
                else:
                    warnings.append(c_msg)
                continue

            # Try ARMCLANG
            m2 = armclang_pattern.search(line)
            if m2:
                fpath, lnum, col, sev, msg = m2.groups()
                abs_fpath = os.path.normpath(os.path.join(proj_dir, fpath)) if not os.path.isabs(fpath) else fpath
                c_msg = CompilerMessage(
                    file_path=abs_fpath,
                    line_number=int(lnum),
                    column=int(col),
                    severity=sev.lower(),
                    error_code="",
                    message=msg.strip()
                )
                if sev.lower() == "error":
                    errors.append(c_msg)
                else:
                    warnings.append(c_msg)

        return errors, warnings
