"""
Universal AutoDebug Injector for Any New STM32 Project
Usage:
    python inject_to_project.py [Target_Project_Directory]
"""
import os
import sys
import shutil
import glob

# Ensure UTF-8 output on Windows terminals
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

KIT_DIR = os.path.dirname(os.path.abspath(__file__))


def inject(target_dir):
    target_dir = os.path.abspath(target_dir)
    if not os.path.exists(target_dir):
        print(f"[-] Target directory does not exist: {target_dir}")
        return False

    print("\n=======================================================")
    print("  [*] Injecting STM32 AutoDebug Toolchain to New Project")
    print(f"  Target: {target_dir}")
    print("=======================================================")

    # 1. Copy AI rules & SOP (AGENTS.md & .cursorrules)
    src_agents = os.path.join(KIT_DIR, "AGENTS.md")
    dst_agents = os.path.join(target_dir, "AGENTS.md")
    dst_cursorrules = os.path.join(target_dir, ".cursorrules")

    if os.path.exists(src_agents):
        shutil.copy2(src_agents, dst_agents)
        shutil.copy2(src_agents, dst_cursorrules)
        print("  [+] Copied AGENTS.md & .cursorrules (AI automatic rule injection)")

    # 2. Copy run_autodebug.py and autodebug package
    src_runner = os.path.join(KIT_DIR, "run_autodebug.py")
    dst_runner = os.path.join(target_dir, "run_autodebug.py")
    shutil.copy2(src_runner, dst_runner)
    print("  [+] Copied run_autodebug.py")

    src_pkg = os.path.join(KIT_DIR, "autodebug")
    dst_pkg = os.path.join(target_dir, "autodebug")
    if os.path.exists(dst_pkg):
        shutil.rmtree(dst_pkg)
    shutil.copytree(src_pkg, dst_pkg)
    print("  [+] Copied autodebug/ core engine")

    # 3. Check for .uvprojx in target project
    uvprojx_files = glob.glob(os.path.join(target_dir, "**", "*.uvprojx"), recursive=True)
    if uvprojx_files:
        rel_proj = os.path.relpath(uvprojx_files[0], target_dir)
        print(f"\n  [🎯 Found Keil Project]: {rel_proj}")
        print(f"  [💡 Command to test in your new project window]:")
        print(f"     python run_autodebug.py --project \"{rel_proj}\"")
    else:
        print(f"\n  [!] Notice: No .uvprojx found yet. Once you generate your Keil project, run:")
        print(f"     python run_autodebug.py --project \"MDK-ARM/your_project.uvprojx\"")

    print(f"\n[SUCCESS] Injection Complete! You can now open {target_dir} in your AI editor!")
    print("=======================================================\n")
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        print("Please drag and drop your project folder onto inject_to_project.bat or input path:")
        target = input("Target Project Path: ").strip(' "')

    inject(target)
