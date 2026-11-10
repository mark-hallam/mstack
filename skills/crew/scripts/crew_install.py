#!/usr/bin/env python3
"""Install crew's background tick so it survives restarts: a launchd agent on macOS, a crontab line on Linux
(with systemd timer files shown as the alternative), and the Task Scheduler command to run on Windows.

`install --dry-run` prints exactly what would be written and where, and writes nothing. The tick itself
honours the stop file, mStack's off switch and the pause, so installing it never starts work the person has
not configured.
"""
import hashlib
import os
import plistlib
import shlex
import subprocess
import sys

import crew_store as st

LABEL = "com.mstack.crew"


def default_home():
    return os.path.join(os.path.expanduser("~"), ".mstack")


def home_path():
    """The absolute path of the mStack home in use (MSTACK_HOME, else ~/.mstack)."""
    return os.path.abspath(os.path.expanduser(os.environ.get("MSTACK_HOME") or default_home()))


def home_tag():
    """Empty for the default home; else the first 8 hex characters of sha256 of the home's absolute path."""
    h = home_path()
    return "" if h == os.path.abspath(default_home()) else hashlib.sha256(h.encode("utf-8")).hexdigest()[:8]


def label():
    """com.mstack.crew for the default home; com.mstack.crew.<tag> for any other, so homes never share a file."""
    return LABEL + ("." + home_tag() if home_tag() else "")


def cron_marker():
    return "# mstack-crew" + ("-" + home_tag() if home_tag() else "")


def plist_path():
    return os.path.join(launch_agents_dir(), label() + ".plist")


def has_marker(line):
    return line.rstrip().endswith(cron_marker())


def crew_tool():
    return os.path.join(st.HERE, "crew.py")


def env_block():
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": os.environ.get("LANG") or "en_AU.UTF-8"}
    if os.environ.get("MSTACK_HOME"):
        env["MSTACK_HOME"] = os.environ["MSTACK_HOME"]
    if os.environ.get("CODEX_HOME"):
        env["CODEX_HOME"] = os.environ["CODEX_HOME"]
    return env


def launch_agents_dir():
    return os.environ.get("MSTACK_LAUNCH_AGENTS") or os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")


def launchctl():
    return shlex.split(os.environ.get("MSTACK_LAUNCHCTL") or "launchctl")


def plist_dict(minutes):
    return {"Label": label(), "ProgramArguments": [sys.executable, crew_tool(), "tick"],
            "StartInterval": int(minutes) * 60, "RunAtLoad": True, "EnvironmentVariables": env_block(),
            "StandardOutPath": st.home("tick.log"), "StandardErrorPath": st.home("tick.log"),
            "WorkingDirectory": os.path.expanduser("~"), "ProcessType": "Background", "Nice": 5}


def cron_line(minutes):
    env = " ".join("%s=%s" % (k, shlex.quote(v)) for k, v in env_block().items())
    return "*/%d * * * * %s %s %s tick >> %s 2>&1 %s" % (
        int(minutes), env, shlex.quote(sys.executable), shlex.quote(crew_tool()), shlex.quote(st.home("tick.log")), cron_marker())


def systemd_units(minutes):
    service = "[Unit]\nDescription=mStack crew tick\n\n[Service]\nType=oneshot\n%s\nExecStart=%s %s tick\n" % (
        "\n".join("Environment=%s=%s" % kv for kv in env_block().items()), shlex.quote(sys.executable), shlex.quote(crew_tool()))
    timer = "[Unit]\nDescription=mStack crew every %d minutes\n\n[Timer]\nOnBootSec=2min\nOnUnitActiveSec=%dmin\n\n[Install]\nWantedBy=timers.target\n" % (
        int(minutes), int(minutes))
    return service, timer


def windows_command(minutes):
    return ("schtasks /Create /SC MINUTE /MO %d /TN \"mStack crew\" /TR \"%s %s tick\" /F" % (
        int(minutes), sys.executable, crew_tool()))


def plan(minutes):
    """Everything an install would do on this computer, as data, for the dry run and for the real thing."""
    out = {"platform": sys.platform, "every_minutes": int(minutes), "tick": [sys.executable, crew_tool(), "tick"],
           "home": home_path(), "label": label(), "honours": [st.stop_file(), "mstack.py disable crew", "crew.py pause"], "writes": [], "runs": [], "notes": []}
    if sys.platform == "darwin":
        path = plist_path()
        out["path"] = path
        out["writes"].append({"path": path, "content": plistlib.dumps(plist_dict(minutes), sort_keys=True).decode("utf-8")})
        out["runs"].append(launchctl() + ["unload", path])
        out["runs"].append(launchctl() + ["load", path])
        out["notes"].append("launchd runs the tick every %d minutes and again after every restart or login" % int(minutes))
    elif sys.platform.startswith("linux"):
        out["writes"].append({"path": "crontab (one line, marked %s)" % cron_marker(), "content": cron_line(minutes)})
        service, timer = systemd_units(minutes)
        out["notes"].append("the alternative is a systemd user timer: write the two units below to ~/.config/systemd/user/ "
                            "as mstack-crew.service and mstack-crew.timer, then: systemctl --user enable --now mstack-crew.timer")
        out["systemd"] = {"mstack-crew.service": service, "mstack-crew.timer": timer}
    else:
        out["runs"].append(["cmd", "/c", windows_command(minutes)])
        out["notes"].append("Windows: Task Scheduler runs the tick every %d minutes; crew does not run it for you, "
                            "copy the command and run it yourself" % int(minutes))
    return out


def crontab_cmd():
    return shlex.split(os.environ.get("MSTACK_CRONTAB") or "crontab")


def read_crontab():
    r = subprocess.run(crontab_cmd() + ["-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def write_crontab(text):
    subprocess.run(crontab_cmd() + ["-"], input=text, text=True, check=True)


def install(minutes, dry_run):
    p = plan(minutes)
    if dry_run:
        p["dry_run"] = True
        p["written"] = []
        return p
    os.makedirs(st.home(), exist_ok=True)
    written = []
    if sys.platform == "darwin":
        for w in p["writes"]:
            os.makedirs(os.path.dirname(w["path"]), exist_ok=True)
            with open(w["path"], "w", encoding="utf-8") as fh:
                fh.write(w["content"])
            written.append(w["path"])
        for cmd in p["runs"]:
            subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    elif sys.platform.startswith("linux"):
        keep = [l for l in read_crontab().splitlines() if not has_marker(l)]
        write_crontab("\n".join(keep + [cron_line(minutes)]) + "\n")
        written.append("crontab")
    p["written"] = written
    p["dry_run"] = False
    return p


def uninstall(dry_run):
    out = {"platform": sys.platform, "home": home_path(), "label": label(), "removes": [], "runs": [], "dry_run": dry_run, "removed": []}
    if sys.platform == "darwin":
        path = plist_path()
        out["path"] = path
        out["removes"].append(path)
        out["runs"].append(launchctl() + ["unload", path])
        if not dry_run:
            subprocess.run(launchctl() + ["unload", path], capture_output=True, text=True, timeout=60)
            if os.path.exists(path):
                os.remove(path)
                out["removed"].append(path)
    elif sys.platform.startswith("linux"):
        out["removes"].append("the crontab line marked %s" % cron_marker())
        if not dry_run:
            keep = [l for l in read_crontab().splitlines() if not has_marker(l)]
            write_crontab("\n".join(keep) + ("\n" if keep else ""))
            out["removed"].append("crontab")
    else:
        out["runs"].append(["cmd", "/c", "schtasks /Delete /TN \"mStack crew\" /F"])
    return out


def recorded_home(path):
    """The mStack home a launchd file was written for (none recorded means the default home), or None if unreadable."""
    try:
        with open(path, "rb") as fh:
            env = plistlib.load(fh).get("EnvironmentVariables") or {}
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    return os.path.abspath(os.path.expanduser(env.get("MSTACK_HOME") or default_home()))


def installed():
    """True only when this home's own file exists and was written for this home."""
    if sys.platform == "darwin":
        path = plist_path()
        return os.path.exists(path) and recorded_home(path) == home_path()
    if sys.platform.startswith("linux"):
        return any(has_marker(l) for l in read_crontab().splitlines())
    return False
