"""Guards for the shipped .bat / .ps1 entry points.

These scripts are the very first thing a new user runs, and they fail in a way that
is invisible in review: cmd.exe reads a batch file in fixed-size blocks, and a
multi-byte character straddling a block boundary is torn in half. The tail of the
line is then executed as a command, producing "'xxx' is not recognized" in the
middle of an otherwise normal run.

Which line breaks depends purely on byte offsets, so an edit anywhere in the file
can silently break a completely different line. A UTF-8 BOM fixes it: measured on
the Python-detection block, 1 of 11 padding offsets failed without a BOM and 0 of
11 failed with one.

PowerShell 5.1 has the matching hazard from the other direction: it reads a .ps1
without a BOM as ANSI, so non-ASCII text renders as mojibake.
"""
import io
import os
import subprocess
import sys
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every shipped script that carries non-ASCII text and is executed by cmd or
# PowerShell rather than by Python.
SHELL_SCRIPTS = ["setup_env.bat", "setup_env.ps1", "inject_to_project.bat"]


class EncodingGuards(unittest.TestCase):
    def test_scripts_with_non_ascii_have_a_utf8_bom(self):
        for name in SHELL_SCRIPTS:
            path = os.path.join(KIT, name)
            with self.subTest(script=name):
                self.assertTrue(os.path.exists(path), f"{name} is missing")
                with open(path, "rb") as fh:
                    raw = fh.read()
                if not any(b > 0x7F for b in raw):
                    continue  # pure ASCII cannot hit either hazard
                self.assertEqual(
                    raw[:3], b"\xef\xbb\xbf",
                    f"{name} contains non-ASCII text but has no UTF-8 BOM. "
                    f"cmd.exe will tear a multi-byte character at a block boundary "
                    f"and run the rest of that line as a command; PowerShell 5.1 "
                    f"will read the file as ANSI. See this module's docstring.")

    def test_scripts_are_valid_utf8(self):
        for name in SHELL_SCRIPTS:
            path = os.path.join(KIT, name)
            with self.subTest(script=name):
                with open(path, "rb") as fh:
                    raw = fh.read()
                try:
                    raw.decode("utf-8")
                except UnicodeDecodeError as e:
                    self.fail(f"{name} is not valid UTF-8: {e}")

    def test_batch_comments_carry_no_redirection_characters(self):
        """A ':: ' line is still scanned for < > |, which splits the comment."""
        for name in [s for s in SHELL_SCRIPTS if s.endswith(".bat")]:
            path = os.path.join(KIT, name)
            with self.subTest(script=name):
                offenders = []
                for i, line in enumerate(io.open(path, encoding="utf-8-sig"), 1):
                    stripped = line.strip()
                    if stripped.startswith("::") and any(c in stripped for c in "<>|"):
                        offenders.append((i, stripped[:60]))
                self.assertEqual(offenders, [], f"{name}: redirection characters in :: comments")

    def test_literal_bang_not_mixed_with_delayed_expansion(self):
        """With enabledelayedexpansion, a literal [!] plus a !VAR! on the same line
        makes cmd treat the text between the two '!' as a variable name and expand
        it away."""
        for name in [s for s in SHELL_SCRIPTS if s.endswith(".bat")]:
            path = os.path.join(KIT, name)
            text = io.open(path, encoding="utf-8-sig").read()
            if "enabledelayedexpansion" not in text.lower():
                continue
            with self.subTest(script=name):
                offenders = [(i, l.strip()[:60])
                             for i, l in enumerate(text.split("\n"), 1)
                             if "[!]" in l and l.count("!") >= 3]
                self.assertEqual(offenders, [], f"{name}: literal [!] alongside !VAR!")


class RunsWithoutTornLines(unittest.TestCase):
    """Run the shipped batch file byte-for-byte and assert cmd parsed every line.

    Byte offsets are what decide whether a multi-byte character lands on a block
    boundary, so the file must be copied verbatim -- truncating it to "just the
    interesting part" tests a layout that never ships and produces both false
    alarms and false clears. Side effects are held off with a stub `python` placed
    first on PATH instead, which leaves the batch bytes untouched.
    """

    @unittest.skipUnless(sys.platform.startswith("win"), "cmd.exe only")
    def test_setup_env_runs_without_a_torn_line(self):
        import shutil
        import tempfile

        src = os.path.join(KIT, "setup_env.bat")
        with tempfile.TemporaryDirectory() as tmp:
            stub = os.path.join(tmp, "stub")
            os.makedirs(stub)
            crlf = "\r\n"
            with io.open(os.path.join(stub, "python.bat"), "w", newline=crlf) as f:
                f.write("@echo off" + crlf
                        + 'if "%~1"=="--version" echo Python 3.12.0' + crlf
                        + "exit /b 0" + crlf)

            dst = os.path.join(tmp, "setup_env.bat")
            shutil.copyfile(src, dst)
            with open(dst, "rb") as a, open(src, "rb") as b:
                self.assertEqual(a.read(), b.read(),
                                 "the copy must be byte-identical or offsets shift")

            env = dict(os.environ, PATH=stub + os.pathsep + os.environ["PATH"])
            proc = subprocess.run(["cmd", "/c", dst], capture_output=True, cwd=tmp,
                                  env=env, stdin=subprocess.DEVNULL, timeout=180)

        torn = [l.strip() for l in proc.stderr.decode("utf-8", "replace").splitlines()
                if "not recognized" in l]
        self.assertEqual(
            torn, [],
            "cmd executed part of a line as a command, so a multi-byte character was "
            "torn at a block boundary. Check that setup_env.bat still starts with a "
            "UTF-8 BOM; see this module's docstring.")
        self.assertEqual(proc.returncode, 0, f"setup_env.bat exited {proc.returncode}")


if __name__ == "__main__":
    unittest.main()
