"""
Post-install check: can every dependency actually be imported?

Run by setup_env as a plain script (`python autodebug/deps_check.py`), so it must not
import the autodebug package -- that would fail on exactly the breakage it looks for.

pip on Windows can fail to replace a package whose files are locked. It then leaves
the new copy under a "~"-prefixed directory (cmsis_pack_manager -> ~msis_pack_manager)
while the dist-info claims a normal install, so `pip install` believes all is well and
the import fails later, deep inside pyOCD. Hence: clear the leftovers, try each import,
force-reinstall only what still fails, and try once more.
"""
import glob
import importlib
import os
import shutil
import site
import subprocess
import sys

# import name -> pip distribution. Optional ones only warn (J-Link users only).
REQUIRED = {
    "pyocd": "pyocd",
    "cmsis_pack_manager": "cmsis-pack-manager",
    "elftools": "pyelftools",
    "serial": "pyserial",
    "yaml": "PyYAML",
}
OPTIONAL = {"pylink": "pylink-square"}

MIRROR = ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
          "--trusted-host", "pypi.tuna.tsinghua.edu.cn"]


def site_dirs():
    dirs = []
    try:
        dirs += site.getsitepackages()
    except Exception:
        pass
    try:
        dirs.append(site.getusersitepackages())
    except Exception:
        pass
    return [d for d in dirs if os.path.isdir(d)]


def clear_leftovers():
    removed = []
    for d in site_dirs():
        for path in glob.glob(os.path.join(d, "~*")):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                removed.append(path)
            except OSError:
                pass
    for path in removed:
        print(f"      已清理 pip 残留：{path}")
    return removed


def failing(modules):
    bad = []
    for name in modules:
        try:
            importlib.invalidate_caches()
            importlib.import_module(name)
        except Exception as e:
            bad.append((name, e))
    return bad


def main() -> int:
    clear_leftovers()
    bad = failing(REQUIRED)
    if bad:
        packages = [REQUIRED[name] for name, _ in bad]
        print(f"      导入失败：{', '.join(n for n, _ in bad)}，正在强制重装 {', '.join(packages)} ...")
        for extra in (MIRROR, []):
            cmd = [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps",
                   *extra, *packages]
            if subprocess.call(cmd) == 0:
                break
        clear_leftovers()
        bad = failing(REQUIRED)

    for name, e in failing(OPTIONAL):
        print(f"      [提示] 可选依赖 {name} 无法导入（{type(e).__name__}），只影响 J-Link 用户。")

    if bad:
        for name, e in bad:
            print(f"[错误] 无法导入 {name}：{type(e).__name__}: {e}")
        print("       请关闭所有正在运行的 Python / AI 编辑器后，手动执行：")
        print(f"       {sys.executable} -m pip install --force-reinstall "
              f"{' '.join(REQUIRED[n] for n, _ in bad)}")
        return 1
    print("      依赖导入检查通过。")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    sys.exit(main())
