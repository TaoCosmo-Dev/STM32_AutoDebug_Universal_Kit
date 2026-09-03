"""
Keil .uvprojx editor - lets the AI change project structure without opening uVision.

Everything the uVision GUI does to a project is just XML. An agent that can write C but
cannot add that C file to the project is stuck at the first link error, so this module
covers the operations the closed loop actually needs:

    * add source files to a group        (Project -> Add Files)
    * add include paths                  (Options -> C/C++ -> Include Paths)
    * add preprocessor defines           (Options -> C/C++ -> Define)
    * turn on debug information          (Options -> Output -> Debug Information)
    * neutralise a duplicate fault handler in stm32xxxx_it.c

All edits are text-level, never an XML re-serialisation: the file stays byte-identical
outside the touched region, the declaration and formatting survive, one backup is kept,
and every operation is idempotent so repeated runs are no-ops.
"""
from dataclasses import dataclass, field
import os
import re
from typing import Iterable, List, Optional, Tuple

BACKUP_SUFFIX = ".autodebug.bak"
DEFAULT_GROUP = "AutoDebug"

# Keil FileType codes
FILETYPE_C = 1
FILETYPE_ASM = 2
FILETYPE_OBJECT = 3
FILETYPE_LIBRARY = 4
FILETYPE_CPP = 8

_EXT_FILETYPE = {
    ".c": FILETYPE_C, ".h": FILETYPE_C,
    ".s": FILETYPE_ASM, ".asm": FILETYPE_ASM,
    ".cpp": FILETYPE_CPP, ".cc": FILETYPE_CPP, ".cxx": FILETYPE_CPP,
    ".o": FILETYPE_OBJECT, ".obj": FILETYPE_OBJECT,
    ".lib": FILETYPE_LIBRARY, ".a": FILETYPE_LIBRARY,
}

_TARGET_BLOCK = re.compile(r"<Target>.*?</Target>", re.S)
_TARGET_NAME = re.compile(r"<TargetName>(.*?)</TargetName>", re.S)
_GROUP_BLOCK = re.compile(r"<Group>\s*<GroupName>(.*?)</GroupName>(.*?)</Group>", re.S)
_DEBUG_INFO_OFF = re.compile(r"(<DebugInformation>)\s*0\s*(</DebugInformation>)")
_CREATE_EXE = re.compile(r"(\s*)<CreateExecutable>")
_INCLUDE_PATH = re.compile(r"<IncludePath>(.*?)</IncludePath>", re.S)
_DEFINE = re.compile(r"<Define>(.*?)</Define>", re.S)
_VARIOUS_CONTROLS = re.compile(r"(<Cads>.*?<VariousControls>)(.*?)(</VariousControls>)", re.S)

# Handlers whose empty HAL stubs swallow a crash before cm_backtrace_lite can report it.
FAULT_HANDLERS = ("HardFault_Handler", "MemManage_Handler", "BusFault_Handler",
                  "UsageFault_Handler")


@dataclass
class EditResult:
    """What actually changed. `changed` is False when the project already satisfied everything."""
    changed: bool = False
    notes: List[str] = field(default_factory=list)
    backup_path: Optional[str] = None

    def add(self, note: str) -> None:
        self.changed = True
        self.notes.append(note)

    def merge(self, other: "EditResult") -> "EditResult":
        self.changed = self.changed or other.changed
        self.notes.extend(other.notes)
        self.backup_path = self.backup_path or other.backup_path
        return self

    def summary(self) -> str:
        return "; ".join(self.notes) if self.notes else "no change needed"


def _keil_path(project_dir: str, file_path: str) -> str:
    """Project-relative path in Keil's backslash form."""
    abs_path = os.path.abspath(file_path)
    try:
        rel = os.path.relpath(abs_path, project_dir)
    except ValueError:                      # different drive on Windows
        rel = abs_path
    return rel.replace("/", "\\")


def _norm(path: str) -> str:
    return path.replace("/", "\\").lstrip(".\\").lower()


def _detect_indent(block: str, tag: str, default: str) -> str:
    m = re.search(r"(\n[ \t]*)<" + re.escape(tag) + ">", block)
    return m.group(1) if m else default


class KeilProjectEditor:
    """Edits one .uvprojx. Load, mutate, then save() writes only if something changed."""

    def __init__(self, uvprojx_path: str):
        self.path = os.path.abspath(uvprojx_path)
        self.project_dir = os.path.dirname(self.path)
        with open(self.path, "rb") as f:
            self.original = f.read().decode("utf-8")
        self.text = self.original
        self.result = EditResult()

    # ---------------------------------------------------------------- target helpers

    def target_names(self) -> List[str]:
        names = []
        for m in _TARGET_BLOCK.finditer(self.text):
            n = _TARGET_NAME.search(m.group(0))
            if n:
                names.append(n.group(1).strip())
        return names

    def _iter_targets(self, target_name: Optional[str]):
        """Yield (start, end, block, name) for each target we should touch."""
        for m in _TARGET_BLOCK.finditer(self.text):
            block = m.group(0)
            n = _TARGET_NAME.search(block)
            name = n.group(1).strip() if n else ""
            if target_name and name != target_name:
                continue
            yield m.start(), m.end(), block, name

    def _rewrite_targets(self, target_name: Optional[str], fn) -> None:
        """Apply fn(block, name) -> (new_block, note|None) to the selected targets."""
        pieces = []
        cursor = 0
        for start, end, block, name in list(self._iter_targets(target_name)):
            new_block, note = fn(block, name)
            if new_block == block:
                continue
            pieces.append(self.text[cursor:start])
            pieces.append(new_block)
            cursor = end
            if note:
                self.result.add(note)
        if pieces:
            pieces.append(self.text[cursor:])
            self.text = "".join(pieces)

    # ---------------------------------------------------------------- operations

    def set_debug_information(self, target_name: Optional[str] = None) -> "KeilProjectEditor":
        """Output -> Debug Information. Without it the image has no DWARF line table."""
        def edit(block: str, name: str):
            patched, count = _DEBUG_INFO_OFF.subn(r"\g<1>1\g<2>", block, count=1)
            if count:
                return patched, f"已开启调试信息 [{name}]"
            if "<DebugInformation>" in block:
                return block, None                     # already on
            m = _CREATE_EXE.search(block)
            if not m:
                return block, None
            indent = m.group(1)
            tag = f"{indent}<DebugInformation>1</DebugInformation>"
            return block[:m.start()] + tag + block[m.start():], f"已补上调试信息开关 [{name}]"

        self._rewrite_targets(target_name, edit)
        return self

    def add_sources(self, files: Iterable[str], group: str = DEFAULT_GROUP,
                    target_name: Optional[str] = None) -> "KeilProjectEditor":
        """Add source files to a group, creating the group when needed.

        This is what unblocks autonomous coding: a .c the AI just wrote is invisible to
        the linker until it is listed here.
        """
        wanted = []
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext == ".h":
                continue                               # headers are found via include paths
            wanted.append((os.path.basename(f), _keil_path(self.project_dir, f),
                           _EXT_FILETYPE.get(ext, FILETYPE_C)))
        if not wanted:
            return self

        def edit(block: str, name: str):
            present = {_norm(p) for p in re.findall(r"<FilePath>(.*?)</FilePath>", block, re.S)}
            todo = [w for w in wanted if _norm(w[1]) not in present]
            if not todo:
                return block, None

            file_indent = _detect_indent(block, "File", "\n          ")
            inner = file_indent + "  "
            entries = "".join(
                f"{file_indent}<File>"
                f"{inner}<FileName>{fname}</FileName>"
                f"{inner}<FileType>{ftype}</FileType>"
                f"{inner}<FilePath>{fpath}</FilePath>"
                f"{file_indent}</File>"
                for fname, fpath, ftype in todo)
            added = ", ".join(w[0] for w in todo)

            gm = None
            for m in _GROUP_BLOCK.finditer(block):
                if m.group(1).strip() == group:
                    gm = m
                    break

            if gm is not None:
                body = gm.group(2)
                idx = body.rfind("</Files>")
                if idx < 0:
                    return block, None
                new_body = body[:idx] + entries + body[idx:]
                new_group = block[gm.start():gm.end()].replace(body, new_body, 1)
                return (block[:gm.start()] + new_group + block[gm.end():],
                        f"已加入工程组 {group} [{name}]: {added}")

            # No such group yet: append one before </Groups>
            close = block.rfind("</Groups>")
            if close < 0:
                return block, None
            group_indent = _detect_indent(block, "Group", "\n      ")
            gi = group_indent + "  "
            new_group = (f"{group_indent}<Group>"
                         f"{gi}<GroupName>{group}</GroupName>"
                         f"{gi}<Files>{entries}{gi}</Files>"
                         f"{group_indent}</Group>")
            return (block[:close] + new_group + block[close:],
                    f"已新建工程组 {group} 并加入 [{name}]: {added}")

        self._rewrite_targets(target_name, edit)
        return self

    def add_include_paths(self, paths: Iterable[str],
                          target_name: Optional[str] = None) -> "KeilProjectEditor":
        """Options -> C/C++ -> Include Paths."""
        wanted = [_keil_path(self.project_dir, p) for p in paths]
        if not wanted:
            return self

        def edit(block: str, name: str):
            m = _INCLUDE_PATH.search(block)
            if m:
                current = m.group(1)
                existing = {_norm(x) for x in current.split(";") if x.strip()}
                todo = [w for w in wanted if _norm(w) not in existing]
                if not todo:
                    return block, None
                joined = ";".join([p for p in current.split(";") if p.strip()] + todo)
                new_block = block[:m.start(1)] + joined + block[m.end(1):]
                return new_block, f"已加入包含路径 [{name}]: {', '.join(todo)}"

            vc = _VARIOUS_CONTROLS.search(block)
            if not vc:
                return block, None
            indent = _detect_indent(vc.group(2), "Define", "\n            ")
            tag = f"{indent}<IncludePath>{';'.join(wanted)}</IncludePath>"
            insert_at = vc.end(2)
            return (block[:insert_at] + tag + block[insert_at:],
                    f"已加入包含路径 [{name}]: {', '.join(wanted)}")

        self._rewrite_targets(target_name, edit)
        return self

    def add_defines(self, defines: Iterable[str],
                    target_name: Optional[str] = None) -> "KeilProjectEditor":
        """Options -> C/C++ -> Define."""
        wanted = [d.strip() for d in defines if d and d.strip()]
        if not wanted:
            return self

        def edit(block: str, name: str):
            m = _DEFINE.search(block)
            if not m:
                return block, None
            current = m.group(1)
            existing = {x.strip() for x in current.split(",") if x.strip()}
            todo = [w for w in wanted if w not in existing and w.split("=")[0] not in
                    {e.split("=")[0] for e in existing}]
            if not todo:
                return block, None
            joined = ",".join([d for d in current.split(",") if d.strip()] + todo)
            return (block[:m.start(1)] + joined + block[m.end(1):],
                    f"已加入宏定义 [{name}]: {', '.join(todo)}")

        self._rewrite_targets(target_name, edit)
        return self

    # ---------------------------------------------------------------- persistence

    def save(self) -> EditResult:
        """Write the file if anything changed, keeping one backup of the original."""
        if self.text == self.original:
            return self.result
        backup = self.path + BACKUP_SUFFIX
        if not os.path.exists(backup):
            with open(backup, "wb") as f:
                f.write(self.original.encode("utf-8"))
        with open(self.path, "wb") as f:
            f.write(self.text.encode("utf-8"))
        self.result.backup_path = backup
        return self.result


# --------------------------------------------------------------------------------------
# Source-level helper: stop the HAL stub from swallowing crashes
# --------------------------------------------------------------------------------------

def _handler_span(text: str, handler: str) -> Optional[Tuple[int, int]]:
    """Locate `void <handler>(void) { ... }` and return its span, braces matched."""
    m = re.search(r"(?:^|\n)[ \t]*(?:void|__weak\s+void)\s+" + re.escape(handler) +
                  r"\s*\(\s*void\s*\)\s*\{", text)
    if not m:
        return None
    depth = 0
    i = text.index("{", m.start())
    start = m.start() + 1 if text[m.start()] == "\n" else m.start()
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
        i += 1
    return None


def disable_conflicting_fault_handlers(project_dir: str,
                                       handlers: Iterable[str] = FAULT_HANDLERS) -> EditResult:
    """Comment out the empty fault handlers in stm32xxxx_it.c.

    The HAL template defines `void HardFault_Handler(void) { while (1) {} }`. It is not
    weak, so linking cm_backtrace_lite.c next to it is a duplicate-symbol error - and
    even without the tracer that empty loop is what turns a crash into a silent hang.
    """
    result = EditResult()
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in {".git", "Objects", "Listings", ".autodebug"}]
        for fname in files:
            if not re.match(r"^stm32.*_it\.c$", fname, re.IGNORECASE):
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, "rb") as f:
                    raw = f.read()
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                continue

            new_text = text
            disabled = []
            for handler in handlers:
                if f"AUTODEBUG disabled {handler}" in new_text:
                    continue
                span = _handler_span(new_text, handler)
                if not span:
                    continue
                start, end = span
                body = new_text[start:end]
                replacement = (
                    f"/* AUTODEBUG disabled {handler}: the empty HAL stub turns a crash into a\n"
                    f"   silent hang and clashes with cm_backtrace_lite.c. Restore this block if\n"
                    f"   you set CM_BACKTRACE_PROVIDE_HANDLER to 0.\n"
                    + body.replace("*/", "* /") +
                    "\n*/")
                new_text = new_text[:start] + replacement + new_text[end:]
                disabled.append(handler)

            if disabled:
                backup = path + BACKUP_SUFFIX
                if not os.path.exists(backup):
                    with open(backup, "wb") as f:
                        f.write(raw)
                with open(path, "wb") as f:
                    f.write(new_text.encode("utf-8"))
                result.add(f"已注释 {fname} 中的空处理函数: {', '.join(disabled)}")
                result.backup_path = result.backup_path or backup
    return result
