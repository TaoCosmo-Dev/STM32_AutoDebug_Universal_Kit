"""
Install the stm32-autodebug Agent Skill so every AI editor picks it up automatically,
in every project, without injecting the toolchain into each one.

Usage:
    python install_skill.py              # install / refresh
    python install_skill.py --uninstall  # remove
    python install_skill.py --list       # show what is installed where

Why this exists
---------------
`inject_to_project.py` copies the toolchain into one project. That is per-project manual
work. But the engine never actually needed to live inside the project -- every path it
touches is derived from `--project` (report, .autodebug/ state, mcu_support/ copy target),
and the config has a fallback chain ending in the packaged default. The only thing
injection really provided was putting AGENTS.md where the AI would read it.

An Agent Skill solves exactly that, once, globally. SKILL.md is an open standard read by
Claude Code, Cursor, Codex CLI, Gemini CLI, Cline, Windsurf, Copilot, Zed and others, so
one install covers the whole toolbox.

The skill we install is a POINTER, not a copy of the rules: it tells the agent to read
AGENTS.md. That keeps AGENTS.md the single source of truth -- the same reason
inject_to_project.py refuses to emit .cursorrules / .clinerules duplicates.
"""
import argparse
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

SKILL_NAME = "stm32-autodebug"

# realpath, not just abspath: resolves symlinks and Windows 8.3 short names ("PROGRA~1"),
# so the path we bake into SKILL.md is the one the user actually sees.
KIT_DIR = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(KIT_DIR, "skills", SKILL_NAME, "SKILL.md")


def _home() -> str:
    """The user's real home directory.

    Do NOT use a bare `~` or trust $HOME on Windows. Plenty of engineering tools
    (Cadence, Cygwin, Git Bash, MSYS, some MATLAB installs) set HOME to their own
    data directory, e.g. `HOME=D:\\Cadence\\Cadence\\SPB_Data`. Every AI editor we
    install for resolves the home dir the OS way (Node `os.homedir()`, Rust
    `dirs::home_dir()`), which on Windows is USERPROFILE -- so USERPROFILE is what
    we must match, or we would drop skills into a folder nothing ever reads.
    """
    if os.name == "nt":
        for candidate in (
            os.environ.get("USERPROFILE"),
            (os.environ.get("HOMEDRIVE", "") + os.environ.get("HOMEPATH", "")) or None,
        ):
            if candidate and os.path.isdir(candidate):
                return os.path.realpath(candidate)
    return os.path.realpath(os.path.expanduser("~"))


HOME = _home()


def _hijacked_home() -> str:
    """Return $HOME when it disagrees with the real home, else ''. Informational only."""
    raw = os.environ.get("HOME")
    if not raw or os.name != "nt":
        return ""
    try:
        same = os.path.normcase(os.path.realpath(raw)) == os.path.normcase(HOME)
    except OSError:
        same = False
    return "" if same else raw


# Global skill directories, by agent. `<home>/.agents/skills` is the converging shared
# convention (Cursor / Codex CLI / Gemini CLI all read it); the rest are per-tool.
# We install to the shared one first and treat it as the canonical copy.
#
# (dir_name, label, always_install)  -- always_install=False means "only if that tool
# looks installed", so we don't litter the home dir of someone who has never run it.
AGENT_DIRS = [
    (".agents", "共享约定（Cursor / Codex CLI / Gemini CLI）", True),
    (".claude", "Claude Code / Claude Desktop", True),
    (".cursor", "Cursor", False),
    (".cline", "Cline", False),
    (".gemini", "Gemini CLI", False),
    (".codex", "Codex CLI（旧路径）", False),
    (".windsurf", "Windsurf", False),
    (".config/opencode", "OpenCode", False),
]

CANONICAL = os.path.join(HOME, ".agents", "skills")


def _targets():
    """Resolve AGENT_DIRS against the real home, plus any user-supplied extras.

    Set AUTODEBUG_SKILL_DIRS to add locations (os.pathsep-separated) when an editor
    uses a path this list does not know about yet -- no need to edit this file.
    """
    out = [
        (os.path.join(HOME, *name.split("/"), "skills"), label, always)
        for name, label, always in AGENT_DIRS
    ]
    extra = os.environ.get("AUTODEBUG_SKILL_DIRS", "")
    out += [
        (os.path.realpath(p), "AUTODEBUG_SKILL_DIRS 指定", True)
        for p in extra.split(os.pathsep) if p.strip()
    ]
    return out


TARGETS = _targets()


def _kit_path_for_docs() -> str:
    """The kit path as it should appear inside SKILL.md.

    Forward slashes: they work in Python, cmd.exe, PowerShell and Git Bash alike,
    while backslashes get eaten as escapes the moment an agent puts the path in a
    Python/JSON string. Same path, one less way to break.
    """
    return KIT_DIR.replace("\\", "/")


def _render() -> str:
    """Read the template and bake in this machine's kit path."""
    if not os.path.exists(TEMPLATE):
        raise SystemExit(
            f"[-] 找不到 skill 模板：{TEMPLATE}\n"
            f"    套件似乎不完整，请重新 clone 或补上 skills/ 目录。"
        )
    with io.open(TEMPLATE, encoding="utf-8") as f:
        text = f.read()
    if "{{KIT_DIR}}" not in text:
        print("  [!] 模板里没有 {{KIT_DIR}} 占位符，安装后路径可能不对")
    return text.replace("{{KIT_DIR}}", _kit_path_for_docs())


def _tool_present(skills_dir: str) -> bool:
    """Is this agent actually installed? Its config root existing is the signal."""
    return os.path.isdir(os.path.dirname(skills_dir))


def _installed_kit(path: str) -> str:
    """Which kit does an already-installed SKILL.md point at? '' if unreadable."""
    try:
        with io.open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("**套件安装位置**"):
                    return line.split("`")[1] if "`" in line else ""
    except Exception:
        pass
    return ""


def _write(dest_dir: str, body: str) -> str:
    """Write SKILL.md into dest_dir/<name>/. Returns a short status word."""
    target = os.path.join(dest_dir, SKILL_NAME)
    os.makedirs(target, exist_ok=True)
    path = os.path.join(target, "SKILL.md")

    existing = None
    if os.path.exists(path):
        try:
            with io.open(path, encoding="utf-8", errors="replace") as f:
                existing = f.read()
        except Exception:
            pass
    if existing == body:
        return "已是最新"

    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return "已更新" if existing is not None else "已安装"


def _link_or_copy(dest_dir: str, body: str) -> str:
    """Prefer a symlink to the canonical copy so upgrades propagate; fall back to a
    real file (Windows needs Developer Mode or admin rights for symlinks)."""
    src = os.path.join(CANONICAL, SKILL_NAME)
    target = os.path.join(dest_dir, SKILL_NAME)

    if os.path.islink(target):
        try:
            if os.path.realpath(target) == os.path.realpath(src):
                return "已链接"
        except OSError:
            pass
        try:
            os.unlink(target)
        except OSError:
            pass

    if not os.path.exists(target):
        os.makedirs(dest_dir, exist_ok=True)
        try:
            os.symlink(src, target, target_is_directory=True)
            return "已链接"
        except (OSError, NotImplementedError, AttributeError):
            pass  # no symlink privilege -> fall through to a real copy

    return _write(dest_dir, body) + "（副本）"


def install() -> None:
    body = _render()
    print(f"套件位置：{KIT_DIR}")
    print(f"家目录  ：{HOME}")

    hijacked = _hijacked_home()
    if hijacked:
        print(f"\n  [!] 注意：环境变量 HOME 指向 {hijacked}")
        print(f"      （多半是 Cadence / Cygwin / MSYS 之类的工具设的）")
        print(f"      已忽略它，按 USERPROFILE 安装 —— AI 编辑器找的也是这里。")
    print()

    # 同一台机器换过套件位置时，先清掉指向旧位置的残留，避免两份 skill 打架
    stale = 0
    for skills_dir, _, _ in TARGETS:
        path = os.path.join(skills_dir, SKILL_NAME, "SKILL.md")
        if not os.path.exists(path):
            continue
        old = _installed_kit(path)
        if old and os.path.normcase(old) != os.path.normcase(_kit_path_for_docs()):
            stale += 1
    if stale:
        print(f"  [i] 发现 {stale} 处指向旧套件位置的安装，将就地更新为当前位置\n")

    print(f"  [*] {_write(CANONICAL, body)}  {CANONICAL}")
    print("      └─ 共享约定，Cursor / Codex CLI / Gemini CLI 直接读这里\n")

    copies = 0
    for skills_dir, label, always in TARGETS[1:]:
        if not (always or _tool_present(skills_dir)):
            continue
        status = _link_or_copy(skills_dir, body)
        if "副本" in status:
            copies += 1
        print(f"  [*] {status}  {skills_dir}")
        print(f"      └─ {label}")

    print("\n" + "=" * 62)
    print("  [完成] 现在打开**任意** Keil 工程，直接说人话即可")
    print("         不需要注入，不需要开场白 —— AI 会自己加载规范并跑闭环")
    print("=" * 62)
    if copies:
        print("\n  [!] 部分位置用的是文件副本而非符号链接（Windows 未开启开发者模式）。")
        print("      **移动或更新套件后请重跑本脚本**，让各处副本同步。")
    print("\n  验证：新开一个 AI 会话，说「帮我给 STM32F103 写个串口驱动」，")
    print("        它应该不用你提醒就按闭环规范走。\n")


def uninstall() -> None:
    removed = 0
    for skills_dir, label, _ in TARGETS:
        target = os.path.join(skills_dir, SKILL_NAME)
        if os.path.islink(target):
            os.unlink(target)
        elif os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        else:
            continue
        removed += 1
        print(f"  [-] 已移除  {target}  ({label})")
    print(f"\n共移除 {removed} 处。" if removed else "\n没有找到已安装的 skill。")


def show() -> None:
    print(f"套件位置：{KIT_DIR}")
    print(f"家目录  ：{HOME}")
    hijacked = _hijacked_home()
    if hijacked:
        print(f"  [!] HOME 环境变量指向 {hijacked}，已忽略（按 USERPROFILE 走）")
    print()

    want = _kit_path_for_docs()
    found = bad = 0
    for skills_dir, label, _ in TARGETS:
        target = os.path.join(skills_dir, SKILL_NAME)
        path = os.path.join(target, "SKILL.md")
        if not os.path.exists(path):
            continue
        found += 1
        kind = "链接" if os.path.islink(target) else "副本"
        note = ""
        old = _installed_kit(path)
        if old and os.path.normcase(old) != os.path.normcase(want):
            bad += 1
            note = f"\n         [!] 指向旧位置 {old} —— 重跑 install_skill.py 修复"
        elif not old:
            bad += 1
            note = "\n         [!] 读不出套件位置，文件可能损坏 —— 重跑 install_skill.py"
        print(f"  [{kind}] {path}\n         {label}{note}")

    if not found:
        print("未安装。运行 `python install_skill.py` 安装。")
        return
    print(f"\n共 {found} 处，其中 {bad} 处需要修复。" if bad else f"\n共 {found} 处，全部正常。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="安装 stm32-autodebug Agent Skill（免注入用法）")
    ap.add_argument("--uninstall", action="store_true", help="移除所有已安装的 skill")
    ap.add_argument("--list", action="store_true", help="列出已安装位置")
    args = ap.parse_args()

    if args.uninstall:
        uninstall()
    elif args.list:
        show()
    else:
        install()
