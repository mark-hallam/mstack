#!/usr/bin/env python3
"""Usage awareness for crew: measured, never guessed.

Where a reading comes from (each verified on a real computer; crew never claims a number it cannot read):

- Claude Code: every headless run with `--output-format stream-json --verbose` emits a `rate_limit_event` whose
  `rate_limit_info.unifiedWindows` holds each plan window (for example `seven_day`, `five_hour`) as
  `{"utilization": 0.52, "resetsAt": <unix seconds>}`. crew reads it from every job it runs (free), and when no
  reading is fresh it may make one probe: a one word call on the smallest model.
- Codex: every turn appends a `token_count` event to the session log under `~/.codex/sessions/<y>/<m>/<d>/`
  with `rate_limits.primary` (the 5 hour window, `window_minutes` 300) and `rate_limits.secondary` (the 7 day
  window, 10080) as `used_percent` plus `resets_at`. crew reads the newest log (free) and the log its own jobs
  write. `codex exec --json` prints token usage per turn but not the windows.

When neither is available for a runner, crew falls back to a conservative mode for that runner: quiet hours
only and a small daily cap, and says so plainly.
"""
import datetime
import glob
import json
import os
import subprocess

import crew_store as st


def readings_path():
    return st.home("usage.json")


def load_readings():
    return st.read_json(readings_path(), {})


def save_reading(runner, reading):
    data = load_readings()
    data[runner] = reading
    st.write_json(readings_path(), data)
    return reading


def window(name, percent, resets_at, minutes=None):
    return {"window": name, "percent": round(float(percent), 1), "resets_at": int(resets_at or 0),
            "resets": datetime.datetime.fromtimestamp(int(resets_at)).isoformat(timespec="minutes") if resets_at else "",
            "minutes": minutes}


# ---------------------------------------------------------------- Claude Code

def parse_claude_stream(text):
    """The windows from the newest rate_limit_event in a stream-json output. Returns a reading or None."""
    found = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{") or "rate_limit" not in line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") != "rate_limit_event":
            continue
        info = ev.get("rate_limit_info") or {}
        wins = []
        for name, w in (info.get("unifiedWindows") or {}).items():
            if isinstance(w, dict) and w.get("utilization") is not None:
                wins.append(window(name, float(w["utilization"]) * 100, w.get("resetsAt")))
        if not wins and info.get("utilization") is not None:
            wins.append(window(info.get("rateLimitType") or "window", float(info["utilization"]) * 100, info.get("resetsAt")))
        if wins:
            found = {"runner": "claude", "at": st.stamp(), "windows": wins, "how": "rate_limit_event",
                     "status": info.get("status", ""), "overage": bool(info.get("isUsingOverage"))}
    return found


def probe_claude(cfg):
    """One word on the smallest model, only to read the windows. Costs a little usage; crew says so."""
    r = cfg["runners"]["claude"]
    cmd = list(r.get("command") or ["claude", "-p"])
    if not st.have(cmd[0]):
        return None
    cmd += ["Reply with the single word ok", "--output-format", "stream-json", "--verbose",
            "--model", r.get("probe_model") or "haiku"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    reading = parse_claude_stream(out.stdout)
    if reading:
        reading["how"] = "probe"
    return reading


# ---------------------------------------------------------------- Codex

def codex_session_logs():
    base = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    files = glob.glob(os.path.join(base, "sessions", "*", "*", "*", "*.jsonl"))
    return sorted(files, key=os.path.getmtime, reverse=True)


def parse_codex_log(path):
    """The newest rate_limits in one Codex session log. Returns a reading or None."""
    found = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"rate_limits"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                rl = (ev.get("payload") or {}).get("rate_limits") or {}
                wins = []
                for name, w in (("primary", rl.get("primary")), ("secondary", rl.get("secondary"))):
                    if isinstance(w, dict) and w.get("used_percent") is not None:
                        label = {300: "five_hour", 10080: "seven_day"}.get(w.get("window_minutes"), name)
                        wins.append(window(label, w["used_percent"], w.get("resets_at"), w.get("window_minutes")))
                if wins:
                    found = {"runner": "codex", "at": ev.get("timestamp") or st.stamp(), "windows": wins,
                             "how": "session log", "credits": bool((rl.get("credits") or {}).get("has_credits")),
                             "plan": rl.get("plan_type") or "", "log": path}
    except OSError:
        return None
    if found and found["at"].endswith("Z"):             # Codex stamps in UTC; keep local time like everything else
        utc = datetime.datetime.strptime(found["at"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        found["at"] = utc.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    return found


def read_codex(limit=5):
    for path in codex_session_logs()[:limit]:
        reading = parse_codex_log(path)
        if reading:
            return reading
    return None


# ---------------------------------------------------------------- the reading crew acts on

def age_minutes(reading):
    try:
        then = datetime.datetime.fromisoformat(reading["at"][:19])
    except (KeyError, ValueError):
        return 10 ** 6
    return (st.now() - then).total_seconds() / 60.0


def fresh_reading(cfg, runner, allow_probe=True):
    """The freshest reading for a runner: the saved one, else the Codex log, else (Claude) a probe. None when
    nothing can be read. A saved reading past its reset time is refreshed the same way."""
    max_age = float(cfg.get("usage_max_age_minutes", 90))
    saved = load_readings().get(runner)
    if saved and age_minutes(saved) <= max_age and not past_reset(saved):
        return saved
    if runner == "codex":
        fresh = read_codex()
        if fresh and (not saved or age_minutes(fresh) <= age_minutes(saved)):
            return save_reading("codex", fresh)
    elif runner == "claude" and allow_probe and cfg.get("probe", True) and os.environ.get("MSTACK_CREW_NO_PROBE") != "1":
        fresh = probe_claude(cfg)
        if fresh:
            return save_reading("claude", fresh)
    return saved if saved and not past_reset(saved) else None


def past_reset(reading):
    """A window has reset since the reading: the number is no longer true, so read again."""
    try:
        then = datetime.datetime.fromisoformat(reading["at"][:19]).timestamp()
    except (KeyError, ValueError):
        return True
    return any(0 < w.get("resets_at", 0) < st.now().timestamp() and then < w["resets_at"] for w in reading.get("windows", []))


def headroom(cfg, reading):
    """Percentage points crew may still use before the person's reserve, on the fullest window."""
    cap = 100 - float(cfg.get("reserve_percent", 15))
    used = max(w["percent"] for w in reading["windows"])
    return round(cap - used, 1), used, cap


def continue_key(runner, reading):
    """One question per runner per window reset, so the person is asked once, not every tick."""
    fullest = max(reading["windows"], key=lambda w: w["percent"])
    return "continue-%s-%s" % (runner, fullest.get("resets_at") or fullest["window"])


def runner_budget(cfg, runner, q, allow_probe=True):
    """What crew may do with a runner right now:
    {"mode": "ok" | "ask" | "allowed-past-reserve" | "conservative", "why": ..., "reading": ..., "headroom": ...}"""
    reading = fresh_reading(cfg, runner, allow_probe)
    if not reading:
        return {"mode": "conservative", "runner": runner, "reading": None, "headroom": None,
                "why": "usage for %s cannot be read on this computer: quiet hours only and at most %d jobs a day" % (
                    runner, int(cfg["conservative"]["jobs_per_day"]))}
    room, used, cap = headroom(cfg, reading)
    out = {"runner": runner, "reading": reading, "headroom": room, "used": used, "cap": cap, "mode": "ok",
           "why": "%s at %.0f%% of its fullest window; crew may use up to %.0f%% (the person keeps %d%%)" % (
               runner, used, cap, int(cfg.get("reserve_percent", 15)))}
    if room > 0:
        return out
    key = continue_key(runner, reading)
    answer = next((x for x in q.get("questions", []) if x["key"] == key), None)
    if answer and str(answer.get("answer", "")).lower().startswith("y"):
        if used < 100:
            out.update(mode="allowed-past-reserve", why="%s is past the person's reserve (%.0f%%) and they said to keep going" % (runner, used))
        else:
            out.update(mode="ask", why="%s has no usage left until its window resets" % runner)
        return out
    out.update(mode="ask", key=key, why="%s reached %.0f%%, the person's reserve starts at %.0f%%: crew stops and asks" % (
        runner, used, cap))
    return out


def file_continue_question(q, budget):
    """Queue the ask-to-continue once; returns the question (new or existing)."""
    key = budget["key"]
    for x in q["questions"]:
        if x["key"] == key:
            return x
    reading = budget["reading"]
    fullest = max(reading["windows"], key=lambda w: w["percent"])
    x = {"key": key, "job": "", "project": "", "asked": st.stamp(), "answer": "",
         "question": "%s is at %.0f%% of its %s window (resets %s). Keep crew going into your last %d%%?" % (
             budget["runner"], budget["used"], fullest["window"].replace("_", " "), fullest.get("resets") or "soon",
             int(100 - budget["cap"])),
         "default": "no: wait for the window to reset"}
    q["questions"].append(x)
    return x


def record_job_usage(runner, text, job):
    """Tokens and the window reading from a finished run, kept on the job and in usage.json."""
    usage = {"runner": runner}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if runner == "claude" and ev.get("type") == "result":
            u = ev.get("usage") or {}
            usage.update(input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0),
                         cache_read_tokens=u.get("cache_read_input_tokens", 0),
                         cache_write_tokens=u.get("cache_creation_input_tokens", 0),
                         list_price_usd=ev.get("total_cost_usd"), turns=ev.get("num_turns"), seconds=round((ev.get("duration_ms") or 0) / 1000))
        elif runner == "codex" and ev.get("type") == "turn.completed":
            u = ev.get("usage") or {}
            usage.update(input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0),
                         cache_read_tokens=u.get("cached_input_tokens", 0))
    usage["total_tokens"] = sum(int(usage.get(k, 0) or 0) for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))
    if runner == "claude":
        reading = parse_claude_stream(text)
        if reading:
            save_reading("claude", reading)
            usage["window_after"] = max(w["percent"] for w in reading["windows"])
    else:
        reading = read_codex()
        if reading:
            save_reading("codex", reading)
            usage["window_after"] = max(w["percent"] for w in reading["windows"])
    job["usage"] = usage
    return usage
