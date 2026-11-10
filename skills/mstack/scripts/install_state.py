"""Keeps <mstack home>/install.json and the launcher in <mstack home>/bin/mstack.py up to date.

Python 3.9 or later, standard library only. Only session-start and `setup ... --write` call refresh(), and it
writes a file only when its content would change, so a plain read-only command never writes.
"""
import json
import os
import shutil

from mbase import HERE, SKILLS, home

LAUNCHER_SOURCE = os.path.join(HERE, "launcher.py")


def launcher_path():
    return home("bin", "mstack.py")


def version():
    try:
        with open(os.path.join(os.path.dirname(SKILLS), ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            return str(json.load(fh).get("version", ""))
    except (OSError, ValueError, AttributeError):
        return ""


def record():
    return {"root": os.path.dirname(SKILLS), "version": version()}


def ready():
    """True when the launcher and install.json already match this copy of mStack."""
    return not stale()


def put(path, text):
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return True


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def stale():
    want = json.dumps(record(), indent=2) + "\n"
    out = []
    if read(home("install.json")) != want:
        out.append(home("install.json"))
    if read(launcher_path()) != read(LAUNCHER_SOURCE):
        out.append(launcher_path())
    return out


def refresh():
    """Write install.json and the launcher when they differ. Returns the files written. Never raises."""
    changed = []
    try:
        if put(home("install.json"), json.dumps(record(), indent=2) + "\n"):
            changed.append(home("install.json"))
        if put(launcher_path(), read(LAUNCHER_SOURCE) or ""):
            os.chmod(launcher_path(), 0o755)
            changed.append(launcher_path())
        bin_ = home("bin")                           # copies of the tool's modules left by 0.7.1 or the first 0.7.2 fix
        for name in os.listdir(bin_):
            if name != "mstack.py" and name.endswith(".py") and os.path.exists(os.path.join(HERE, name)):
                os.remove(os.path.join(bin_, name))
                changed.append(os.path.join(bin_, name))
        if os.path.isdir(os.path.join(bin_, "__pycache__")):
            shutil.rmtree(os.path.join(bin_, "__pycache__"), ignore_errors=True)
    except OSError:
        pass
    return changed
