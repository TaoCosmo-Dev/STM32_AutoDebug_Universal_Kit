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
import io
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


# path -> which tool picks it up. Same content everywhere; only the filename differs.
RULE_TARGETS = [
    ("AGENTS.md", "通用约定 · Codex CLI / Zed / Jules / Cursor 新版"),
    ("CLAUDE.md", "Claude Code"),
    (".cursorrules", "Cursor"),
    (".windsurfrules", "Windsurf"),
    (".clinerules", "Cline / Roo Code"),
    (os.path.join(".github", "copilot-instructions.md"), "GitHub Copilot"),
]

# A file we generated earlier contains this; anything else is the user's own and is kept.
RULES_FINGERPRINT = "STM32 固件自主编程"


def _install_rules(target_dir: str) -> None:
    src = os.path.join(KIT_DIR, "AGENTS.md")
    if not os.path.exists(src):
        print("  [!] 套件里缺少 AGENTS.md")
        return
    with io.open(src, encoding="utf-8") as f:
        rules = f.read()

    for rel, tool in RULE_TARGETS:
        dst = os.path.join(target_dir, rel)
        if os.path.exists(dst):
            try:
                with io.open(dst, encoding="utf-8", errors="replace") as f:
                    existing = f.read()
            except Exception:
                existing = ""
            if RULES_FINGERPRINT not in existing:
                print(f"  [=] 已有 {rel}，保留你的版本"
                      f"（想让 {tool} 自动加载，在里面加一行指向 AGENTS.md）")
                continue
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with io.open(dst, "w", encoding="utf-8", newline="\n") as f:
            f.write(rules)
        print(f"  [+] {rel}（{tool}）")


def _copy_file(rel_src: str, dst: str, label: str) -> bool:
    src = os.path.join(KIT_DIR, rel_src)
    if not os.path.exists(src):
        print(f"  [!] 套件里缺少文件：{rel_src}")
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
        print("  [+] 已在 .gitignore 中忽略 AutoDebug 产物")
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
        print(f"[-] 目标文件夹不存在：{target_dir}")
        return False
    if os.path.normcase(target_dir) == os.path.normcase(KIT_DIR):
        print("[-] 不能把套件注入到它自己里。")
        return False

    print("\n" + "=" * 63)
    print("  正在注入 STM32 全自动开发套件")
    print(f"  目标工程：{target_dir}")
    print("=" * 63)

    # 1. AI rules ------------------------------------------------------------------
    # Every mainstream agent reads a different file, so drop the same rules at each
    # well-known path. AGENTS.md is the cross-tool convention; the rest are per-editor.
    _install_rules(target_dir)

    # 2. Runner + engine ----------------------------------------------------------
    _copy_file("run_autodebug.py", os.path.join(target_dir, "run_autodebug.py"), "run_autodebug.py")

    dst_pkg = os.path.join(target_dir, "autodebug")
    if os.path.exists(dst_pkg):
        shutil.rmtree(dst_pkg, ignore_errors=True)
    shutil.copytree(os.path.join(KIT_DIR, "autodebug"), dst_pkg, ignore=IGNORE)
    print("  [+] autodebug/ 引擎")

    # 3. Per-project config (never clobber an edited one) --------------------------
    dst_cfg = os.path.join(target_dir, "autodebug.config.yaml")
    if os.path.exists(dst_cfg):
        print("  [=] 已有 autodebug.config.yaml，保留你的版本")
    else:
        _copy_file(os.path.join("autodebug", "config.yaml"), dst_cfg,
                   "autodebug.config.yaml（本工程配置）")

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
        print(f"  找到 Keil 工程：{rel}")
        if len(projects) > 1:
            print(f"  （还有 {len(projects) - 1} 个，用 --project 可指定）")
        print("\n  跑一次完整闭环：")
        print(f"     python run_autodebug.py --project \"{rel}\"")
    else:
        print("  还没有 .uvprojx 工程。生成 Keil 工程后运行：")
        print("     python run_autodebug.py --project \"MDK-ARM/YourProject.uvprojx\"")

    print("\n  想让板子崩溃时自动报出错在哪一行（三步）：")
    print("     1. 把 mcu_support/cm_backtrace_lite.c 加入 Keil 工程")
    print("     2. 实现 void cm_backtrace_putchar(char c)，里面阻塞式写串口寄存器")
    print("     3. 在 main() 最开头调用 cm_backtrace_init()")
    print("     （若链接报 HardFault_Handler 重复定义，删掉 stm32xxxx_it.c 里")
    print("      那个空实现 —— 正是它把崩溃吞掉了）")
    print("-" * 63)
    print(f"\n[完成] 注入成功！用你的 AI 编辑器打开 {target_dir}\n")
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        print("请把工程文件夹拖到 inject_to_project.bat 图标上，或在下方输入路径：")
        target = input("工程路径：").strip(' "')
    sys.exit(0 if inject(target) else 1)
