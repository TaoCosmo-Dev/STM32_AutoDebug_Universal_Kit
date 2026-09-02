"""
ELF / AXF symbol and DWARF line resolver for ARM Cortex-M.

The whole line table is flattened into one sorted array at load time and looked up with
bisect, so resolving a backtrace costs microseconds instead of re-parsing the ELF once per
address. Sequence boundaries are honoured, so an address that belongs to no code range
returns None instead of silently snapping to a nearby unrelated line.
"""
from bisect import bisect_right
from dataclasses import dataclass
import os
from typing import Dict, List, Optional, Tuple

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection


@dataclass
class SourceLocation:
    address: int
    file_path: str
    line_number: int
    function_name: Optional[str] = None
    source_context: Optional[str] = None
    resolved_path: Optional[str] = None   # the file actually found on disk, if any


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class SymbolResolver:
    def __init__(self, axf_path: str, source_roots: Optional[List[str]] = None):
        self.axf_path = os.path.abspath(axf_path)
        self.symbols: Dict[str, int] = {}
        self._sym_addrs: List[int] = []       # sorted function start addresses
        self._sym_names: List[str] = []
        self._sym_sizes: List[int] = []
        self._line_addrs: List[int] = []      # sorted line-table addresses
        self._line_rows: List[Tuple[int, Optional[str]]] = []  # (line, file) or (0, None) at a sequence end
        self.source_roots: List[str] = [os.path.dirname(self.axf_path)]
        for root in (source_roots or []):
            if root and root not in self.source_roots:
                self.source_roots.append(os.path.abspath(root))
        self.loaded = False
        self._load_elf()

    # ---------------------------------------------------------------- loading

    def _load_elf(self) -> None:
        if not os.path.exists(self.axf_path):
            return
        try:
            with open(self.axf_path, "rb") as f:
                elffile = ELFFile(f)
                self._load_symbols(elffile)
                self._load_lines(elffile)
            self.loaded = True
        except Exception:
            self.loaded = False

    def _load_symbols(self, elffile: ELFFile) -> None:
        symtab = elffile.get_section_by_name(".symtab")
        if not symtab or not isinstance(symtab, SymbolTableSection):
            return
        collected: List[Tuple[int, str, int]] = []
        for sym in symtab.iter_symbols():
            name = sym.name
            addr = sym["st_value"]
            if not name or not addr:
                continue
            info_type = sym["st_info"]["type"]
            clean = addr & ~1              # drop the Thumb bit
            self.symbols[name] = clean
            if info_type in ("STT_FUNC", "STT_NOTYPE"):
                collected.append((clean, name, sym["st_size"] or 0))
        collected.sort(key=lambda t: t[0])
        self._sym_addrs = [c[0] for c in collected]
        self._sym_names = [c[1] for c in collected]
        self._sym_sizes = [c[2] for c in collected]

    def _load_lines(self, elffile: ELFFile) -> None:
        if not elffile.has_dwarf_info():
            return
        dwarf_info = elffile.get_dwarf_info()
        rows: List[Tuple[int, int, Optional[str]]] = []
        for cu in dwarf_info.iter_CUs():
            try:
                lp = dwarf_info.line_program_for_CU(cu)
                if lp is None:
                    continue
                comp_dir = ""
                try:
                    attr = cu.get_top_DIE().attributes.get("DW_AT_comp_dir")
                    if attr is not None:
                        comp_dir = _decode(attr.value)
                except Exception:
                    pass
                file_cache: Dict[int, Optional[str]] = {}
                for entry in lp.get_entries():
                    state = entry.state
                    if state is None:
                        continue
                    if state.end_sequence:
                        rows.append((state.address, 0, None))   # sentinel: end of code range
                        continue
                    if state.file not in file_cache:
                        file_cache[state.file] = self._file_name(lp, state.file, comp_dir)
                    rows.append((state.address, state.line, file_cache[state.file]))
            except Exception:
                continue

        rows.sort(key=lambda r: r[0])
        self._line_addrs = [r[0] for r in rows]
        self._line_rows = [(r[1], r[2]) for r in rows]

    @staticmethod
    def _file_name(lp, file_index: int, comp_dir: str) -> Optional[str]:
        """Resolve a line-program file index, honouring the DWARF 5 index change."""
        try:
            version = lp.header.get("version", 4)
            entries = lp["file_entry"] or []
            dirs = lp["include_directory"] or []
            idx = file_index if version >= 5 else file_index - 1
            if not (0 <= idx < len(entries)):
                return None
            fe = entries[idx]
            name = _decode(fe.name)
            if os.path.isabs(name):
                return os.path.normpath(name)

            dir_index = getattr(fe, "dir_index", 0)
            if version >= 5:
                dirname = _decode(dirs[dir_index]) if 0 <= dir_index < len(dirs) else ""
            else:
                dirname = _decode(dirs[dir_index - 1]) if 1 <= dir_index <= len(dirs) else ""

            parts = [p for p in (comp_dir, dirname, name) if p]
            if len(parts) == 1:
                return os.path.normpath(parts[0])
            path = parts[-1]
            for prefix in reversed(parts[:-1]):
                if os.path.isabs(path):
                    break
                path = os.path.join(prefix, path)
            return os.path.normpath(path)
        except Exception:
            return None

    # ---------------------------------------------------------------- queries

    def get_symbol_address(self, name: str) -> Optional[int]:
        return self.symbols.get(name)

    def resolve_function_name(self, address: int) -> Optional[str]:
        clean = address & ~1
        if not self._sym_addrs:
            return None
        i = bisect_right(self._sym_addrs, clean) - 1
        if i < 0:
            return None
        start = self._sym_addrs[i]
        size = self._sym_sizes[i]
        if size and clean >= start + size:
            return None
        if not size and clean - start > 0x2000:
            return None
        return self._sym_names[i]

    def resolve_address(self, address: int, context_lines: int = 5) -> Optional[SourceLocation]:
        """Translate an execution address (PC/LR) into file, line, function and a snippet."""
        clean = address & ~1
        if not self._line_addrs:
            return None
        i = bisect_right(self._line_addrs, clean) - 1
        if i < 0:
            return None
        line, file_path = self._line_rows[i]
        if not file_path or line <= 0:
            return None   # address sits past the end of a code sequence

        resolved_path, snippet = self._extract_source_context(file_path, line, context_lines)
        return SourceLocation(
            address=address,
            file_path=file_path,
            line_number=line,
            function_name=self.resolve_function_name(clean),
            source_context=snippet,
            resolved_path=resolved_path,
        )

    # ---------------------------------------------------------------- source lookup

    def _candidate_paths(self, file_path: str) -> List[str]:
        basename = os.path.basename(file_path)
        candidates: List[str] = []
        if os.path.isabs(file_path):
            candidates.append(os.path.normpath(file_path))
        for root in self.source_roots:
            for up in ("", "..", os.path.join("..", ".."), os.path.join("..", "..", "..")):
                base = os.path.normpath(os.path.join(root, up)) if up else root
                candidates.append(os.path.normpath(os.path.join(base, file_path)))
                for sub in ("", "User", "USER", "Src", "src", "Source", "App",
                            os.path.join("Core", "Src"), "Hardware", "Drivers"):
                    candidates.append(os.path.normpath(os.path.join(base, sub, basename)))
        seen = set()
        unique = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def _extract_source_context(self, file_path: str, line_no: int,
                                context_lines: int = 5) -> Tuple[Optional[str], Optional[str]]:
        actual = None
        for cand in self._candidate_paths(file_path):
            if os.path.isfile(cand):
                actual = cand
                break
        if actual is None:
            return None, None

        try:
            with open(actual, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            return actual, None

        if not lines:
            return actual, None
        start = max(1, line_no - context_lines)
        end = min(len(lines), line_no + context_lines)
        formatted = []
        for i in range(start, end + 1):
            marker = ">>>" if i == line_no else "   "
            formatted.append(f"{marker} {i:4d} | {lines[i - 1].rstrip()}")
        return actual, "\n".join(formatted)
