"""
Enable a HAL peripheral module in one step.

A CubeMX project carries only the drivers its .ioc asked for. Reaching for another
peripheral from code -- ADC, I2C -- then fails three ways in a row: the module macro is
commented out in stm32xxxx_hal_conf.h, the driver sources are not under Drivers/, and the
.c files are not in the Keil project. Each fix exposes the next error. This does all
three, or -- when any module cannot be satisfied -- none of them.

    enable_hal_modules("MDK-ARM/App.uvprojx", ["adc", "i2c"])

Driver files are taken from the project first, then from the local STM32CubeMX
repository (~/STM32Cube/Repository/STM32Cube_FW_<family>_V*), preferring the exact
firmware version the .ioc was generated with so no mixed-version driver sneaks in.
"""
import glob
import os
import re
import shutil
from typing import Dict, List, Optional, Tuple

from .project_editor import EditResult, KeilProjectEditor

_SKIP_DIRS = {".git", ".autodebug", "objects", "listings", "debugconfig"}

# Modules whose HAL driver is a thin layer over an LL one that must come along.
_LL_DEPENDENCIES: Dict[str, List[str]] = {
    "sd": ["sdmmc"], "mmc": ["sdmmc"],
    "pcd": ["usb"], "hcd": ["usb"],
    "nand": ["fsmc"], "nor": ["fsmc"], "sram": ["fsmc"], "pccard": ["fsmc"],
}


def _source_root(uvprojx_path: str) -> str:
    proj_dir = os.path.dirname(os.path.abspath(uvprojx_path))
    return (os.path.dirname(proj_dir) if os.path.basename(proj_dir).upper().startswith("MDK")
            else proj_dir)


def _walk(root: str):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS]
        yield dirpath, dirs, files


def _find_hal_conf(root: str) -> Optional[str]:
    for dirpath, _dirs, files in _walk(root):
        for name in files:
            if re.match(r"^stm32\w+_hal_conf\.h$", name, re.I) and "template" not in name.lower():
                return os.path.join(dirpath, name)
    return None


def _find_driver_dir(root: str, prefix: str) -> Optional[str]:
    wanted = f"{prefix}_hal_driver".lower()
    for dirpath, dirs, _files in _walk(root):
        for d in dirs:
            if d.lower() == wanted:
                return os.path.join(dirpath, d)
    return None


def _ioc_firmware(root: str) -> Optional[str]:
    """'STM32Cube FW_F1 V1.8.7' -> 'STM32Cube_FW_F1_V1.8.7'."""
    for path in glob.glob(os.path.join(root, "*.ioc")):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                m = re.search(r"^ProjectManager\.FirmwarePackage=(.+)$", f.read(), re.M)
        except OSError:
            continue
        if m:
            return m.group(1).strip().replace(" ", "_")
    return None


def _version_key(path: str):
    m = re.search(r"_V(\d+)\.(\d+)\.(\d+)$", path)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def cube_repository_drivers(prefix: str, root: str) -> List[str]:
    """HAL driver folders in the local CubeMX repository, best match first."""
    m = re.match(r"stm32(\w+?)xx$", prefix, re.I)
    if not m:
        return []
    family = m.group(1).upper()
    # USERPROFILE first: some toolchains (Cadence) point HOME somewhere else entirely.
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    repos = glob.glob(os.path.join(home, "STM32Cube", "Repository", f"STM32Cube_FW_{family}_V*"))
    pinned = _ioc_firmware(root)
    repos.sort(key=lambda p: (os.path.basename(p) != pinned, tuple(-x for x in _version_key(p))))
    drivers = []
    for repo in repos:
        drivers += [d for d in glob.glob(os.path.join(repo, "Drivers", "*_HAL_Driver"))
                    if os.path.basename(d).lower() == f"{prefix}_hal_driver".lower()]
    return drivers


def _module_files(prefix: str, module: str) -> Tuple[List[str], List[str]]:
    """(required, optional) base names without extension for one module."""
    required = [f"{prefix}_hal_{module}"]
    optional = [f"{prefix}_hal_{module}_ex"]
    required += [f"{prefix}_ll_{ll}" for ll in _LL_DEPENDENCIES.get(module, [])]
    return required, optional


def _locate(stem: str, ext: str, sub: str, dirs: List[str]) -> Optional[str]:
    for d in dirs:
        path = os.path.join(d, sub, stem + ext)
        if os.path.exists(path):
            return path
    return None


def enable_hal_modules(uvprojx_path: str, modules: List[str],
                       target_name: Optional[str] = None) -> Tuple[EditResult, List[str]]:
    """Enable each module. Returns (what changed, errors); errors mean nothing changed."""
    result = EditResult()
    root = _source_root(uvprojx_path)

    conf_path = _find_hal_conf(root)
    if not conf_path:
        return result, ["不是 HAL 工程：找不到 stm32xxxx_hal_conf.h。标准外设库工程不需要这一步。"]
    prefix = os.path.basename(conf_path)[:-len("_hal_conf.h")].lower()
    driver_dir = _find_driver_dir(root, prefix)
    if not driver_dir:
        return result, [f"找不到 {prefix.upper()}_HAL_Driver 目录（通常在 Drivers/ 下）。"]

    with open(conf_path, encoding="utf-8", errors="replace", newline="") as f:
        conf = f.read()
    available = sorted({m.lower() for m in re.findall(r"HAL_([A-Z0-9]+)_MODULE_ENABLED", conf)})
    sources = [driver_dir] + cube_repository_drivers(prefix, root)

    errors: List[str] = []
    plan = []          # (module, macro_state, [(src, dst)], [c files to register])
    for raw in modules:
        module = re.sub(r"^hal_", "", raw.strip().lower())
        if not module:
            continue
        macro = f"HAL_{module.upper()}_MODULE_ENABLED"
        if re.search(rf"^[ \t]*#define[ \t]+{macro}\b", conf, re.M):
            macro_state = "on"
        # CubeMX writes CRLF, and the file is read with newline="" to keep it that way,
        # so a line ends in "\r" before the "$" that re.M anchors on.
        elif re.search(rf"^[ \t]*/\*[ \t]*#define[ \t]+{macro}\b[^\n]*?\*/[ \t]*\r?$", conf, re.M):
            macro_state = "off"
        else:
            errors.append(f"{os.path.basename(conf_path)} 里没有 {macro}：模块名 '{raw}' 不对。"
                          f"可用的有：{', '.join(available)}")
            continue

        required, optional = _module_files(prefix, module)
        copies, registers, missing = [], [], []
        for stem in required + optional:
            for ext, sub in ((".c", "Src"), (".h", "Inc")):
                dst = os.path.join(driver_dir, sub, stem + ext)
                src = dst if os.path.exists(dst) else _locate(stem, ext, sub, sources[1:])
                if src is None:
                    if stem in required:
                        missing.append(stem + ext)
                    continue
                if src != dst:
                    copies.append((src, dst))
                if ext == ".c":
                    registers.append(dst)
        if missing:
            errors.append(
                f"模块 {module} 缺少驱动文件 {', '.join(missing)}，工程里和本机 CubeMX 仓库"
                f"（%USERPROFILE%\\STM32Cube\\Repository）里都没有。请用 CubeMX 打开 .ioc 启用该外设后"
                f"重新生成，或在 CubeMX 里安装对应系列的固件包后重试。")
            continue
        plan.append((module, macro, macro_state, copies, registers))

    if errors:
        return result, errors

    original_conf = conf
    for module, macro, macro_state, copies, _registers in plan:
        if macro_state == "off":
            conf = re.sub(rf"^([ \t]*)/\*[ \t]*(#define[ \t]+{macro}\b)[^\n]*?\*/[ \t]*(?=\r?$)",
                          r"\1\2", conf, count=1, flags=re.M)
            result.add(f"已打开 {macro}（{os.path.basename(conf_path)}）")
        for src, dst in copies:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            repo = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(src)))))
            result.add(f"已从本机 CubeMX 仓库 {repo} 拷入 {os.path.basename(dst)}")
    if conf != original_conf:
        with open(conf_path, "w", encoding="utf-8", newline="") as f:
            f.write(conf)

    editor = KeilProjectEditor(uvprojx_path)
    group = (editor.group_containing(f"{prefix}_hal_gpio.c", target_name)
             or f"Drivers/{os.path.basename(driver_dir)}")
    for module, _m, _s, _c, registers in plan:
        if registers:
            editor.add_sources(registers, group=group, target_name=target_name)
    result.merge(editor.save())

    if not result.changed:
        result.notes.append(f"{', '.join(p[0] for p in plan)} 已经启用，无需改动")
    if glob.glob(os.path.join(root, "*.ioc")):
        result.notes.append(
            "提醒：工程带 .ioc。以后在 CubeMX 里重新生成代码会按 .ioc 还原 hal_conf.h 与工程文件，"
            "长期使用的外设建议也在 CubeMX 里启用。")
    return result, []
