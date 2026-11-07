"""Start the product under review and run the journey driver."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from eval_common import DRIVER, fill, free_port, port_free, tmp_base


class Target(object):
    """Start the product (if it has a start command) in a fresh temporary folder and wait until it answers."""

    def __init__(self, project, override=None, port=None):
        self.p = project
        t = dict(project.cfg.get("target", {}))
        t.update(override or {})
        self.t = t
        self.port = port or free_port()
        self.tmp = tempfile.mkdtemp(prefix="mstack-target-", dir=tmp_base())
        cwd = t.get("cwd", ".")
        self.cwd = cwd if os.path.isabs(cwd) else os.path.normpath(os.path.join(project.dir, cwd))
        self.values = {"port": self.port, "tmp": self.tmp, "dir": project.dir, "cwd": self.cwd}
        self.url = fill(t.get("url", "http://127.0.0.1:{port}/"), self.values)
        self.values["url"] = self.url
        self.proc = None
        self.log = os.path.join(self.tmp, "product.log")

    def tail(self):
        try:
            with open(self.log, encoding="utf-8", errors="replace") as fh:
                return "\nIts last output:\n" + "".join(fh.readlines()[-15:])
        except OSError:
            return ""

    def _run(self, cmd, wait):
        env = dict(os.environ, PYTHONUNBUFFERED="1")             # so a Python product's output shows up at once
        env.update(fill(self.t.get("env", {}), self.values))
        shell = isinstance(cmd, str)
        kw = dict(cwd=self.cwd, env=env, shell=shell, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.name == "posix":
            kw["start_new_session"] = True
        if wait:
            kw["stdout"] = kw["stderr"] = subprocess.PIPE
            r = subprocess.run(fill(cmd, self.values), timeout=600, **kw)
            if r.returncode != 0:
                raise SystemExit("A setup command failed: %s\n%s" % (cmd, (r.stderr or b"").decode(errors="replace")))
            return None
        kw["stdout"] = open(self.log, "w")
        kw["stderr"] = subprocess.STDOUT
        return subprocess.Popen(fill(cmd, self.values), **kw)

    def start(self):
        if self.t.get("start") and not port_free(self.port):
            self.stop()
            raise SystemExit("Port %d is already in use. Stop whatever is using it, or choose another port." % self.port)
        for cmd in self.t.get("setup", []):
            self._run(cmd, wait=True)
        if self.t.get("start"):
            self.proc = self._run(self.t["start"], wait=False)
        deadline = time.time() + float(self.t.get("ready_timeout", 30))
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never through a system proxy
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                msg = "The product stopped while starting (exit %s): %s%s" % (self.proc.returncode, self.t["start"], self.tail())
                self.stop()
                raise SystemExit(msg)
            try:
                direct.open(self.url, timeout=2)
                return self
            except urllib.error.HTTPError:
                return self                     # it answered, even if not with 200
            except Exception:
                time.sleep(0.3)
        msg = "The product did not answer at %s within %ss.%s" % (self.url, self.t.get("ready_timeout", 30), self.tail())
        self.stop()
        raise SystemExit(msg)

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(self.proc.pid, signal.SIGTERM)
                else:
                    self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()


def drive(spec, out, env=None, timeout=180):
    with open(os.path.join(out, "steps.json"), "w", encoding="utf-8") as fh:
        json.dump(spec, fh)
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js 18 or later is needed (https://nodejs.org).")
    r = subprocess.run([node, DRIVER, os.path.join(out, "steps.json"), os.path.join(out, "run")], capture_output=True,
                       text=True, timeout=timeout, env=env)
    if r.returncode != 0:
        raise SystemExit("The journey driver failed: %s %s" % (r.stdout.strip(), r.stderr.strip()))
    return os.path.join(out, "run")
