"""
Inject the AutoDebug toolchain into any existing STM32 project.

Usage:
    python inject_to_project.py <target_project_dir>
    (or drag the project folder onto inject_to_project.bat)

What lands in the target:
    AGENTS.md / .cursorrules / CLAUDE.md   AI rules incl. the mandatory closed loop
    run_autodebug.py                       the runner the AI calls
    autodebug/                             engine (build, flash, monitor, diagnose)
    autodebug.config.yaml                  editable per-project config
    mcu_support/                           cm_backtrace_lite crash tracer for the firmware
"""
import os
import shutil
import sys

if sys.platform.startswith("win"):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

KIT_DIR = os.path.dirname(os.path.abspath(__file__))
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".autodebug")

GITIGNORE_LINES = [
    "# AutoDebug artifacts",
    "diagnostic_report.json",
    "build_autodebug.log",
    ".autodebug/",
]


def _copy_file(rel_src: str, dst: str, label: str) -> bool:
    src = os.path.join(KIT_DIR, rel_src)
    if not os.path.exists(src):
        print(f"  [!] missing in kit: {rel_src}")
        return False
    shutil.copy2(src, dst)
    print(f"  [+] {label}")
    return True


def _merge_gitignore(target_dir: str) -> None:
    path = os.path.join(target_dir, ".gitignore")
    existing = ""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                existing = f.read()
        except Exception:
            return
    missing = [ln for ln in GITIGNORE_LINES if ln not in existing]
    if not missing:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(missing) + "\n")
        print("  [+] .gitignore updated with AutoDebug artifacts")
    except Exception:
        pass


def find_projects(target_dir: str) -> list:
    skip = {".git", "__pycache__", "node_modules", "Objects", "Listings", ".autodebug"}
    found = []
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.endswith(".uvprojx"):
                found.append(os.path.join(root, f))
    found.sort(key=lambda p: (0 if "MDK-ARM" in p else 1, p.count(os.sep), p))
    return found


def inject(target_dir: str) -> bool:
    target_dir = os.path.abspath(target_dir)
    if not os.path.isdir(target_dir):
        print(f"[-] Target directory does not exist: {target_dir}")
        return False
    if os.path.normcase(target_dir) == os.path.normcase(KIT_DIR):
        print("[-] Refusing to inject the kit into itself.")
        return False

    print("\n" + "=" * 63)
    print("  Injecting the STM32 AutoDebug toolchain")
    print(f"  Target: {target_dir}")
    print("=" * 63)

    # 1. AI rules -----------------------------------------------------------------
    _copy_file("AGENTS.md", os.path.join(target_dir, "AGENTS.md"), "AGENTS.md (AI rules)")
    _copy_file("AGENTS.md", os.path.join(target_dir, ".cursorrules"), ".cursorrules (Cursor / Windsurf)")
    claude_md = os.path.join(target_dir, "CLAUDE.md")
    if os.path.exists(claude_md):
        print("  [=] CLAUDE.md already exists, left untouched "
              "(add a line pointing at AGENTS.md if you want Claude Code to auto-load it)")
    else:
        _copy_file("AGENTS.md", claude_md, "CLAUDE.md (Claude Code auto-loads this)")

    # 2. Runner + engine ----------------------------------------------------------
    _copy_file("run_autodebug.py", os.path.join(target_dir, "run_autodebug.py"), "run_autodebug.py")

    dst_pkg = os.path.join(target_dir, "autodebug")
    if os.path.exists(dst_pkg):
        shutil.rmtree(dst_pkg, ignore_errors=True)
    shutil.copytree(os.path.join(KIT_DIR, "autodebug"), dst_pkg, ignore=IGNORE)
    print("  [+] autodebug/ engine")

    # 3. Per-project config (never clobber an edited one) --------------------------
    dst_cfg = os.path.join(target_dir, "autodebug.config.yaml")
    if os.path.exists(dst_cfg):
        print("  [=] autodebug.config.yaml already exists, kept your version")
    else:
        _copy_file(os.path.join("autodebug", "config.yaml"), dst_cfg,
                   "autodebug.config.yaml (per-project settings)")

    # 4. Firmware-side crash tracer ------------------------------------------------
    dst_mcu = os.path.join(target_dir, "mcu_support")
    os.makedirs(dst_mcu, exist_ok=True)
    for name in ("cm_backtrace_lite.c", "cm_backtrace_lite.h"):
        _copy_file(os.path.join("mcu_support", name), os.path.join(dst_mcu, name),
                   f"mcu_support/{name}")

    _merge_gitignore(target_dir)

    # 5. Next steps ----------------------------------------------------------------
    projects = find_projects(target_dir)
    print("\n" + "-" * 63)
    if projects:
        rel = os.path.relpath(projects[0], target_dir)
        print(f"  Keil project found: {rel}")
        if len(projects) > 1:
            print(f"  (+{len(projects) - 1} more; pass --project to pick one)")
        print("\n  Run the loop:")
        print(f"     python run_autodebug.py --project \"{rel}\"")
    else:
        print("  No .uvprojx found yet. After generating your Keil project run:")
        print("     python run_autodebug.py --project \"MDK-ARM/YourProject.uvprojx\"")

    print("\n  To get HardFault auto-diagnosis without a probe:")
    print("     1. add mcu_support/cm_backtrace_lite.c to the Keil project")
    print("     2. implement void cm_backtrace_putchar(char c) with a blocking UART write")
    print("     3. call cm_backtrace_init() at the top of main()")
    print("     (if the linker reports a duplicate HardFault_Handler, delete the stub")
    print("      in stm32xxxx_it.c - that one is empty and swallows the crash)")
    print("-" * 63)
    print(f"\n[SUCCESS] Injection complete. Open {target_dir} in your AI editor.\n")
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        print("Drag your project folder onto inject_to_project.bat, or type the path:")
        target = input("Target project path: ").strip(' "')
    sys.exit(0 if inject(target) else 1)
