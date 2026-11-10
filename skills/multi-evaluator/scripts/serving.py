"""Serve the product for reviewers and run shared headless Chrome for sandboxed commands."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

from eval_common import tmp_base
from target import Target


def cmd_serve(args):
    from eval_loop import Project

    p = Project(args.dir)
    t = Target(p, port=args.port)

    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)          # a plain kill still stops the product too
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, stop)
    t.start()
    print(json.dumps({"ok": True, "url": t.url}) if getattr(args, "json", False) else "ready: %s" % t.url, flush=True)
    try:
        while t.proc is None or t.proc.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        t.stop()


def find_chrome():
    if os.environ.get("MSTACK_CHROME"):
        return os.environ["MSTACK_CHROME"]
    places = {"darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                         "/Applications/Chromium.app/Contents/MacOS/Chromium"],
              "win32": [r"C:\Program Files\Google\Chrome\Application\chrome.exe"]}.get(sys.platform, [])
    for x in places:
        if os.path.exists(x):
            return x
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    return None


def shared_chrome(port):
    """A headless Chrome that sandboxed reviewers reach through MSTACK_CDP_PORT."""
    bin_ = find_chrome()
    if not bin_:
        return None, None
    work = tempfile.mkdtemp(prefix="mstack-shared-chrome-", dir=tmp_base())
    proc = subprocess.Popen([bin_, "--headless=new", "--remote-debugging-port=%d" % port, "--user-data-dir=" + work,
                             "--hide-scrollbars", "--no-first-run"] + os.environ.get("MSTACK_CHROME_ARGS", "").split()
                            + ["about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    return proc, work
