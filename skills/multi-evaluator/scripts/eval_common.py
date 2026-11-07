"""Shared helpers for the multi-evaluator loop (placeholders, ports, product build metadata)."""
import json
import os
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
CONFIG_NAME = "mstack-eval.json"
DRIVER = os.path.join(HERE, "drive.mjs")
SEVERITIES = ("blocker", "high", "medium", "low")


def _build_captured_time():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def product_build(cwd):
    """Git HEAD of the product folder at capture time. Never raises."""
    captured = _build_captured_time()
    if not cwd:
        return {"commit": None, "captured": captured}
    path = os.path.abspath(cwd)
    head = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True)
    if head.returncode != 0:
        return {"commit": None, "captured": captured}
    commit = head.stdout.strip()
    status = subprocess.run(["git", "-C", path, "status", "--porcelain"], capture_output=True, text=True)
    dirty = bool(status.stdout.strip()) if status.returncode == 0 else False
    return {"commit": commit, "dirty": dirty, "captured": captured}


def round_build(p, n):
    path = p.rdir(n, "views.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError:
        return None
    if isinstance(doc, dict) and "build" in doc:
        return doc["build"]
    return None


def tmp_base():
    # Chrome on macOS will not start from the per-user system temp folder, so use /tmp there.
    return os.environ.get("MSTACK_TMP") or ("/tmp" if sys.platform == "darwin" else tempfile.gettempdir())


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def port_free(port):
    """True when nothing is listening on the port (a closed connection waiting to expire does not count)."""
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def fill(value, values):
    """Replace {port}, {tmp}, {dir}, {url}, {home} and friends in a string, a list or a dict."""
    if isinstance(value, str):
        for k, v in values.items():
            value = value.replace("{%s}" % k, str(v))
        return value
    if isinstance(value, list):
        return [fill(x, values) for x in value]
    if isinstance(value, dict):
        return dict((k, fill(v, values)) for k, v in value.items())
    return value
