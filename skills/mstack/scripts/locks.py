#!/usr/bin/env python3
"""Shared resource locks under MSTACK_HOME. Used by crew and the multi-evaluator review."""
import json
import os
import time


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def mstack_home():
    return os.environ.get("MSTACK_HOME") or os.path.join(os.path.expanduser("~"), ".mstack")


def lock_path(resource):
    return os.path.join(mstack_home(), "locks", "%s.json" % resource)


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def read_lock(resource):
    path = lock_path(resource)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not pid_alive(data.get("pid")):
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    return data


def holder(resource):
    """The live lock for this resource, or None when it is free or stale."""
    return read_lock(resource)


def write_lock(resource, owner, pid):
    path = lock_path(resource)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"owner": owner, "pid": int(pid), "since": stamp()}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return data


def acquire(resource, owner, pid=None, wait=0, interval=30):
    """Take the lock, waiting up to wait seconds when something else holds it. Returns True on success."""
    pid = os.getpid() if pid is None else int(pid)
    deadline = time.time() + float(wait)
    while True:
        existing = read_lock(resource)
        if not existing:
            write_lock(resource, owner, pid)
            return True
        if existing.get("owner") == owner and int(existing.get("pid", -1)) == pid:
            return True
        if wait <= 0 or time.time() >= deadline:
            return False
        print("%s is held by %s since %s" % (resource, existing["owner"], existing["since"]), flush=True)
        time.sleep(min(float(interval), max(0, deadline - time.time())))


def release(resource, pid=None):
    """Drop the lock when this process holds it."""
    pid = os.getpid() if pid is None else int(pid)
    existing = read_lock(resource)
    if existing and int(existing.get("pid", -1)) == pid:
        try:
            os.remove(lock_path(resource))
        except OSError:
            pass


def wait_message(resource, lock):
    return "waiting for %s, held by %s since %s" % (resource, lock["owner"], lock["since"])
