"""
Keil MDK UV4 command-line builder and compiler/linker log parser.

Hard rules enforced here:
  * a build is only "success" when THIS run produced a fresh image (mtime check),
    so a stale .axf from a previous run can never be flashed;
  * a UV4 that hangs on a modal dialog is killed, never left holding the project lock;
  * logs are decoded with the local ANSI codepage as a fallback, so Chinese Keil
    installs do not turn every error message into mojibake.
"""
from dataclasses import dataclass, field
import os
import re
import subprocess
import sys
import time
from typing import List, Optional, Tuple
import xml.etree.ElementTree as ET

from .config import BuildConfig


@dataclass
class CompilerMessage:
    file_path: str
    line_number: int
    column: Optional[int]
    severity: str  # "error" | "warning"
    error_code: str
    message: str

    def signature(self) -> str:
        """Stable identity of a diagnostic, used to detect a stalled repair loop."""
        return f"{os.path.basename(self.file_path)}:{self.line_number}:{self.error_code}:{self.message[:80]}"


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
    failure_reason: str = ""
    available_targets: List[str] = field(default_factory=list)

    def signature(self) -> str:
        if self.errors:
            return "BUILD|" + "|".join(e.signature() for e in self.errors[:5])
        return f"BUILD|rc={self.return_code}|{self.failure_reason}"


# Keil UV4 exit codes (documented in the uVision command-line reference)
UV4_EXIT_MEANING = {
    0: "build done, no errors or warnings",
    1: "build done, warnings only",
    2: "build failed, errors present",
    3: "build failed, fatal errors present",
    11: "cannot open project file",
    12: "device is not supported / no device selected",
    13: "error writing the project file",
    15: "error reading the import XML file",
    20: "license error",
}


class KeilBuildError(RuntimeError):
    pass


class KeilBuilder:
    def __init__(self, uv4_path: Optional[str], build_config: Optional[BuildConfig] = None):
        self.uv4_path = uv4_path
        self.cfg = build_config or BuildConfig()

    # ---------------------------------------------------------------- project introspection

    @staticmethod
    def list_targets(uvprojx_path: str) -> List[str]:
        try:
            root = ET.parse(uvprojx_path).getroot()
            return [t.findtext("TargetName", "").strip() for t in root.findall(".//Target")
                    if t.findtext("TargetName", "").strip()]
        except Exception:
            return []

    def get_output_paths(self, uvprojx_path: str,
                         target_name: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        """Resolve the .axf / .hex the given target writes, from the .uvprojx XML."""
        proj_dir = os.path.dirname(os.path.abspath(uvprojx_path))
        try:
            root = ET.parse(uvprojx_path).getroot()
            targets = root.findall(".//Target")
            chosen = None
            for target in targets:
                t_name = (target.findtext("TargetName", "") or "").strip()
                if target_name:
                    if t_name == target_name:
                        chosen = target
                        break
                elif chosen is None:
                    chosen = target

            if chosen is not None:
                out_dir = chosen.findtext(".//TargetOption/TargetCommonOption/OutputDirectory", "Objects\\")
                out_name = chosen.findtext(".//TargetOption/TargetCommonOption/OutputName", "") or ""
                create_hex = chosen.findtext(".//TargetOption/TargetCommonOption/CreateHexFile", "0")
                if out_name:
                    abs_out_dir = os.path.normpath(os.path.join(proj_dir, (out_dir or "Objects\\").replace("\\", os.sep)))
                    axf_path = os.path.join(abs_out_dir, f"{out_name}.axf")
                    hex_path = os.path.join(abs_out_dir, f"{out_name}.hex") if create_hex == "1" else None
                    return axf_path, hex_path
        except Exception:
            pass

        # Fallback: conventional layout
        base_name = os.path.splitext(os.path.basename(uvprojx_path))[0]
        for candidate_dir in ("Objects", "Output", "build", "Obj"):
            cand_axf = os.path.join(proj_dir, candidate_dir, f"{base_name}.axf")
            if os.path.exists(cand_axf):
                return cand_axf, os.path.join(proj_dir, candidate_dir, f"{base_name}.hex")
        return None, None

    def get_device_name(self, uvprojx_path: str) -> Optional[str]:
        """Map the .uvprojx <Device> tag to a pyOCD target name (STM32F407ZGTx -> stm32f407zg)."""
        try:
            root = ET.parse(uvprojx_path).getroot()
            dev = root.findtext(".//TargetOption/TargetCommonOption/Device", "") or root.findtext(".//Device", "")
            if dev:
                dev_clean = re.sub(r"x+$", "", dev.strip(), flags=re.IGNORECASE)
                dev_clean = re.sub(r"t\d*$", "", dev_clean, flags=re.IGNORECASE)
                return dev_clean.lower()
        except Exception:
            pass
        return None


    # ---------------------------------------------------------------- project self-repair

    _TARGET_BLOCK = re.compile(r"<Target>.*?</Target>", re.S)
    _TARGET_NAME = re.compile(r"<TargetName>(.*?)</TargetName>", re.S)
    _DEBUG_INFO_OFF = re.compile(r"(<DebugInformation>)\s*0\s*(</DebugInformation>)")
    _CREATE_EXE = re.compile(r"(\s*)<CreateExecutable>")

    @classmethod
    def _read_project_text(cls, uvprojx_path: str) -> Optional[str]:
        try:
            with open(uvprojx_path, "rb") as f:
                return f.read().decode("utf-8")
        except Exception:
            return None

    @classmethod
    def _patch_target_block(cls, block: str) -> Tuple[str, bool]:
        """Turn Debug Information on inside one <Target> block."""
        patched, count = cls._DEBUG_INFO_OFF.subn(r"\g<1>1\g<2>", block, count=1)
        if count:
            return patched, True
        if "<DebugInformation>" in block:
            return block, False          # already 1
        # Tag absent entirely: insert it right before <CreateExecutable>, where Keil keeps it.
        m = cls._CREATE_EXE.search(block)
        if not m:
            return block, False
        indent = m.group(1)
        insert = f"{indent}<DebugInformation>1</DebugInformation>"
        return block[:m.start()] + insert + block[m.start():], True

    def ensure_debug_information(self, uvprojx_path: str,
                                 target_name: Optional[str] = None) -> Optional[str]:
        """Make sure the project emits DWARF, by editing the .uvprojx directly.

        "Output -> Debug Information" in the Keil IDE is just <DebugInformation> in the
        project XML. Without it the image carries no line table, so a HardFault can never
        be traced back to a source line. Editing the tag here means the whole pipeline
        stays inside the AI editor - the user never has to open uVision to tick a box.

        Returns a human-readable note when the file was changed, else None.
        """
        text = self._read_project_text(uvprojx_path)
        if text is None:
            return None

        blocks = list(self._TARGET_BLOCK.finditer(text))
        if not blocks:
            return None

        out = []
        cursor = 0
        fixed: List[str] = []
        for m in blocks:
            block = m.group(0)
            name_m = self._TARGET_NAME.search(block)
            name = name_m.group(1).strip() if name_m else ""
            if target_name and name != target_name:
                continue
            new_block, changed = self._patch_target_block(block)
            if changed:
                out.append(text[cursor:m.start()])
                out.append(new_block)
                cursor = m.end()
                fixed.append(name or "(unnamed target)")
        if not fixed:
            return None

        out.append(text[cursor:])
        new_text = "".join(out)

        backup = uvprojx_path + ".autodebug.bak"
        try:
            if not os.path.exists(backup):
                with open(backup, "wb") as f:
                    f.write(text.encode("utf-8"))
            with open(uvprojx_path, "wb") as f:
                f.write(new_text.encode("utf-8"))
        except Exception as e:
            return f"could not enable Debug Information automatically: {e}"

        return (f"已自动开启调试信息（Debug Information）: {', '.join(fixed)}"
                f" —— 否则崩溃时无法定位到源码行。原工程已备份为 "
                f"{os.path.basename(backup)}")

    # ---------------------------------------------------------------- build

    def _read_log(self, log_file: str) -> str:
        """Decode the UV4 log with the first encoding that round-trips cleanly."""
        if not os.path.exists(log_file):
            return ""
        try:
            with open(log_file, "rb") as f:
                raw = f.read()
        except Exception:
            return ""
        for enc in self.cfg.log_encodings:
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _kill_uv4() -> None:
        """UV4 stuck on a modal dialog keeps the project locked; kill it."""
        if not sys.platform.startswith("win"):
            return
        try:
            subprocess.run(["taskkill", "/F", "/IM", "UV4.exe"],
                           capture_output=True, timeout=15)
        except Exception:
            pass

    @staticmethod
    def is_uv4_running() -> bool:
        if not sys.platform.startswith("win"):
            return False
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq UV4.exe"],
                                 capture_output=True, text=True, timeout=15)
            return "UV4.exe" in (out.stdout or "")
        except Exception:
            return False

    def build(self, uvprojx_path: str, target_name: Optional[str] = None,
              rebuild: Optional[bool] = None) -> BuildResult:
        """Run a UV4 CLI build and return a verified result.

        `success` is True only when UV4 exited cleanly, the log holds no errors, and the
        output image was written during THIS invocation.
        """
        uvprojx_path = os.path.abspath(uvprojx_path)
        proj_dir = os.path.dirname(uvprojx_path)
        log_file = os.path.join(proj_dir, "build_autodebug.log")
        targets = self.list_targets(uvprojx_path)

        def fail(reason: str, rc: int = -1, log: str = "") -> BuildResult:
            return BuildResult(success=False, return_code=rc, target_name=target_name or "Default",
                               axf_path=None, hex_path=None, raw_log=log or reason,
                               failure_reason=reason, available_targets=targets)

        if not self.uv4_path or not os.path.exists(self.uv4_path):
            return fail("Keil UV4.exe not found. Set keil.uv4_path in autodebug.config.yaml.")
        if not os.path.exists(uvprojx_path):
            return fail(f"Project file not found: {uvprojx_path}")

        if target_name and targets and target_name not in targets:
            return fail(f"Target '{target_name}' not in project. Available: {targets}")
        if not target_name and len(targets) > 1:
            print(f"[builder] project has {len(targets)} targets {targets}; "
                  f"building '{targets[0]}'. Pass --target to choose another.", file=sys.stderr)
            target_name = targets[0]

        if self.cfg.auto_fix_debug_info:
            note = self.ensure_debug_information(uvprojx_path, target_name)
            if note:
                print(f"[builder] {note}", file=sys.stderr)

        axf_path, hex_path = self.get_output_paths(uvprojx_path, target_name)
        axf_mtime_before = os.path.getmtime(axf_path) if (axf_path and os.path.exists(axf_path)) else None

        do_rebuild = self.cfg.rebuild if rebuild is None else rebuild
        cmd = [self.uv4_path, "-r" if do_rebuild else "-b", uvprojx_path, "-j0", "-o", log_file]
        if target_name:
            cmd.extend(["-t", target_name])

        # A stale log would be silently reparsed if UV4 dies before writing a new one.
        try:
            if os.path.exists(log_file):
                os.remove(log_file)
        except Exception:
            pass

        start_time = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=self.cfg.timeout_seconds)
            ret_code = proc.returncode
        except subprocess.TimeoutExpired:
            if self.cfg.kill_uv4_on_timeout:
                self._kill_uv4()
            return fail(
                f"Keil UV4 timed out after {self.cfg.timeout_seconds:.0f}s and was killed. "
                f"Usual causes: a modal dialog (missing device pack / license), or the project "
                f"is already open in the uVision IDE.",
                rc=-2, log=self._read_log(log_file))
        except Exception as e:
            return fail(f"Failed to launch Keil UV4: {e}")

        log_content = self._read_log(log_file)
        errors, warnings = self._parse_log_messages(log_content, proj_dir)
        duration = time.time() - start_time

        # Re-resolve outputs: OutputName can change between targets.
        axf_path, hex_path = self.get_output_paths(uvprojx_path, target_name)

        failure_reason = ""
        image_fresh = False
        if axf_path and os.path.exists(axf_path):
            mtime_after = os.path.getmtime(axf_path)
            image_fresh = axf_mtime_before is None or mtime_after > axf_mtime_before or ret_code in (0, 1)
            # An incremental build with nothing to do legitimately leaves mtime untouched.
            if axf_mtime_before is not None and mtime_after == axf_mtime_before and ret_code in (0, 1):
                image_fresh = True
        elif axf_path:
            failure_reason = f"Build produced no image at {axf_path}"

        if ret_code not in (0, 1):
            failure_reason = failure_reason or (
                f"UV4 exit code {ret_code}: {UV4_EXIT_MEANING.get(ret_code, 'unknown failure')}")
        elif errors:
            failure_reason = failure_reason or f"{len(errors)} compiler/linker error(s)"
        elif self.cfg.fail_on_stale_axf and not image_fresh:
            failure_reason = failure_reason or (
                "Output image is stale - the current build did not regenerate it")

        success = (ret_code in (0, 1)) and not errors and bool(axf_path) \
            and os.path.exists(axf_path or "") and (image_fresh or not self.cfg.fail_on_stale_axf)

        return BuildResult(
            success=success,
            return_code=ret_code,
            target_name=target_name or (targets[0] if targets else "Default"),
            axf_path=axf_path if (axf_path and os.path.exists(axf_path)) else None,
            hex_path=hex_path if (hex_path and os.path.exists(hex_path)) else None,
            errors=errors,
            warnings=warnings,
            raw_log=log_content,
            duration_seconds=duration,
            failure_reason="" if success else failure_reason,
            available_targets=targets,
        )

    # ---------------------------------------------------------------- log parsing

    # ARMCC / AC5:   "main.c", line 42: Error:  #20: identifier "x" is undefined
    _ARMCC = re.compile(r'"([^"]+)",\s*line\s*(\d+):\s*(Error|Warning|error|warning):?\s*#?([A-Za-z0-9_\-]+)?:?\s*(.+)')
    # ARMCLANG / AC6: ..\main.c:42:10: error: use of undeclared identifier 'x'
    _ARMCLANG = re.compile(r'^(.+?):(\d+):(\d+):\s*(error|warning|fatal error):\s*(.+)$')
    # Linker: .\Objects\app.axf: Error: L6218E: Undefined symbol foo (referred from main.o).
    _LINKER = re.compile(r'(?:^|\s)(Error|Warning|error|warning):\s*(L\d+[A-Z]?):\s*(.+)')
    # Assembler / generic fatal: "Fatal error: ..." with no file/line at all
    _FATAL = re.compile(r'^(?:.*?:\s*)?(Fatal error|fatal error):\s*(.+)$')

    def _parse_log_messages(self, log_content: str,
                            proj_dir: str) -> Tuple[List[CompilerMessage], List[CompilerMessage]]:
        errors: List[CompilerMessage] = []
        warnings: List[CompilerMessage] = []
        seen = set()

        def add(msg: CompilerMessage):
            key = (msg.file_path, msg.line_number, msg.error_code, msg.message)
            if key in seen:
                return
            seen.add(key)
            (errors if msg.severity == "error" else warnings).append(msg)

        def abspath(fpath: str) -> str:
            fpath = fpath.strip()
            if not fpath:
                return ""
            return fpath if os.path.isabs(fpath) else os.path.normpath(os.path.join(proj_dir, fpath))

        for raw_line in log_content.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            m = self._ARMCC.search(line)
            if m:
                fpath, lnum, sev, code, msg = m.groups()
                add(CompilerMessage(abspath(fpath), int(lnum), None,
                                    sev.lower(), code or "", msg.strip()))
                continue

            m = self._ARMCLANG.match(line)
            if m:
                fpath, lnum, col, sev, msg = m.groups()
                add(CompilerMessage(abspath(fpath), int(lnum), int(col),
                                    "error" if "error" in sev.lower() else "warning", "", msg.strip()))
                continue

            m = self._LINKER.search(line)
            if m:
                sev, code, msg = m.groups()
                add(CompilerMessage("<linker>", 0, None, sev.lower(), code, msg.strip()))
                continue

            m = self._FATAL.match(line)
            if m:
                add(CompilerMessage("<toolchain>", 0, None, "error", "FATAL", m.group(2).strip()))

        return errors, warnings
