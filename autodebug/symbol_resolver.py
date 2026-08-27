"""
ELF / AXF DWARF Symbol & Source Resolver for ARM Cortex-M.
Uses pyelftools to perform fast, in-memory address-to-line and symbol resolution.
"""
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


class SymbolResolver:
    def __init__(self, axf_path: str):
        self.axf_path = os.path.abspath(axf_path)
        self.symbols: Dict[str, int] = {}
        self.address_to_symbol: Dict[int, str] = {}
        self._line_programs = []
        self._load_elf()

    def _load_elf(self):
        if not os.path.exists(self.axf_path):
            return

        with open(self.axf_path, "rb") as f:
            elffile = ELFFile(f)

            # 1. Load Symbol Table
            symtab = elffile.get_section_by_name(".symtab")
            if symtab and isinstance(symtab, SymbolTableSection):
                for sym in symtab.iter_symbols():
                    name = sym.name
                    addr = sym["st_value"]
                    if name and addr:
                        # Clear Thumb bit (bit 0) for Cortex-M functions
                        clean_addr = addr & ~1
                        self.symbols[name] = clean_addr
                        self.address_to_symbol[clean_addr] = name

            # 2. Check DWARF Info
            if elffile.has_dwarf_info():
                dwarf_info = elffile.get_dwarf_info()
                for cu in dwarf_info.iter_CUs():
                    lp = dwarf_info.line_program_for_CU(cu)
                    if lp is not None:
                        self._line_programs.append((lp, cu.get_top_DIE()))

    def get_symbol_address(self, name: str) -> Optional[int]:
        return self.symbols.get(name)

    def resolve_function_name(self, address: int) -> Optional[str]:
        clean_addr = address & ~1
        if clean_addr in self.address_to_symbol:
            return self.address_to_symbol[clean_addr]

        # Find closest symbol before address
        best_name = None
        best_diff = float("inf")
        for sym_addr, name in self.address_to_symbol.items():
            if sym_addr <= clean_addr:
                diff = clean_addr - sym_addr
                if diff < best_diff and diff < 0x1000:  # within 4KB
                    best_diff = diff
                    best_name = name
        return best_name

    def resolve_address(self, address: int, context_lines: int = 5) -> Optional[SourceLocation]:
        """
        Translates a 32-bit execution address (e.g. PC/LR) to source file and line.
        """
        clean_addr = address & ~1
        if not os.path.exists(self.axf_path):
            return None

        best_location = None
        best_diff = float("inf")

        with open(self.axf_path, "rb") as f:
            elffile = ELFFile(f)
            if not elffile.has_dwarf_info():
                return None

            dwarf_info = elffile.get_dwarf_info()
            for cu in dwarf_info.iter_CUs():
                lp = dwarf_info.line_program_for_CU(cu)
                if lp is None:
                    continue

                entries = lp.get_entries()
                valid_states = [e.state for e in entries if e.state is not None and e.state.address > 0]
                if not valid_states:
                    continue

                # Find candidate state with closest address <= clean_addr
                matching_states = [s for s in valid_states if s.address <= clean_addr]
                if not matching_states:
                    continue

                best_state = max(matching_states, key=lambda s: s.address)
                diff = clean_addr - best_state.address
                if diff < best_diff and diff < 0x2000 and best_state.line > 0:
                    file_idx = best_state.file - 1
                    file_entries = lp["file_entry"]
                    if 0 <= file_idx < len(file_entries):
                        f_entry = file_entries[file_idx]
                        filename = f_entry.name.decode("utf-8", errors="replace")
                        if f_entry.dir_index > 0 and (f_entry.dir_index - 1) < len(lp["include_directory"]):
                            dirname = lp["include_directory"][f_entry.dir_index - 1].decode("utf-8", errors="replace")
                            full_path = os.path.normpath(os.path.join(dirname, filename))
                        else:
                            full_path = filename

                        func_name = self.resolve_function_name(clean_addr)
                        ctx = self._extract_source_context(full_path, best_state.line, context_lines)

                        best_diff = diff
                        best_location = SourceLocation(
                            address=address,
                            file_path=full_path,
                            line_number=best_state.line,
                            function_name=func_name,
                            source_context=ctx
                        )

        return best_location

    def _extract_source_context(self, file_path: str, line_no: int, context_lines: int = 5) -> Optional[str]:
        actual_path = file_path
        if not os.path.isabs(actual_path) or not os.path.exists(actual_path):
            # Try resolving relative to axf directory or its parents
            axf_dir = os.path.dirname(self.axf_path)
            basename = os.path.basename(file_path)
            candidates = [
                os.path.normpath(os.path.join(axf_dir, file_path)),
                os.path.normpath(os.path.join(axf_dir, "..", file_path)),
                os.path.normpath(os.path.join(axf_dir, "..", "..", file_path)),
                os.path.normpath(os.path.join(axf_dir, "..", "User", basename)),
                os.path.normpath(os.path.join(axf_dir, "..", "USER", basename)),
                os.path.normpath(os.path.join(axf_dir, "..", "Src", basename)),
                os.path.normpath(os.path.join(axf_dir, "..", "Source", basename)),
                os.path.normpath(os.path.join(axf_dir, "..", "App", basename)),
                os.path.normpath(os.path.join(axf_dir, "..", "Core", "Src", basename)),
                os.path.normpath(os.path.join(axf_dir, "..", "..", "User", basename)),
                os.path.normpath(os.path.join(axf_dir, "..", "..", "Core", "Src", basename)),
            ]
            for cand in candidates:
                if os.path.exists(cand):
                    actual_path = cand
                    break
            else:
                return None

        try:
            with open(actual_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            return None

        start = max(1, line_no - context_lines)
        end = min(len(lines), line_no + context_lines)

        formatted = []
        for i in range(start, end + 1):
            marker = ">>>" if i == line_no else "   "
            formatted.append(f"{marker} {i:4d} | {lines[i-1].rstrip()}")

        return "\n".join(formatted)
