#!/usr/bin/env python3
"""The release step that keeps mStack's numbers true.

It installs a release into a clean Claude Code profile with a clean mStack home, asks plain phrases a
stranger might type (tests/release_phrases.json), each in its own fresh session, and records which skill
each one reached. The result is written into docs/evidence/routing.json, and the tables in docs/evidence.md
and README.md are generated from that file, so a number in the README always has a run behind it.

  run   --source <folder or owner/repo> [--out <folder>] [--model sonnet] [--lend-login | --login-file F] [--json]
        install from the source and ask every phrase; writes <out>/result.json
  write [--result <result.json>] [--json]
        add the result to docs/evidence/routing.json and rewrite the generated parts (without --result,
        only rewrite them)
  gate  [--json]
        exit 1 unless a result is recorded for the version in .claude-plugin/plugin.json and the generated
        parts match the recorded results (tests/test_release_check.py runs this on every test run)

The clean profile has no login of its own. `--lend-login` copies this computer's Claude Code login into it
for the run; the copy is deleted when the run ends, however it ends, and the run says so. Without it, sign
in another way (for example an API key in the environment). Python 3.9 or later, standard library only.
"""
import argparse
import concurrent.futures
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START, END = "<!-- evidence:routing:start -->", "<!-- evidence:routing:end -->"
MONTHS = ("January February March April May June July August September October November December").split()


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def say(args, data, text):
    print(json.dumps(data, indent=2) if args.json else text)


def fail(args, message):
    if args.json:
        print(json.dumps({"ok": False, "error": message}))
    else:
        print(message, file=sys.stderr)
    sys.exit(1)


def picked(reply, names):
    """The first mStack skill a reply names, or None."""
    spans = []
    for n in names:
        m = re.search(r"mstack:%s(?![\w-])" % re.escape(n), reply)
        if m:
            spans.append((m.start(), n))
    if not spans:
        for n in names:
            m = re.search(r"(?<![\w:/-])%s(?![\w:-])" % re.escape(n), reply)
            if m:
                spans.append((m.start(), n))
    return min(spans)[1] if spans else None


def lend(profile, login_file):
    """Copy a Claude Code login into the clean profile. Returns the path of the copy."""
    dest = os.path.join(profile, ".credentials.json")
    if login_file:
        shutil.copyfile(login_file, dest)
    elif sys.platform == "darwin":
        out = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                             capture_output=True, text=True)
        if out.returncode != 0 or not out.stdout.strip():
            raise RuntimeError("no Claude Code login was found in the keychain")
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(out.stdout)
    else:
        own = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"),
                           ".credentials.json")
        if not os.path.exists(own):
            raise RuntimeError("no Claude Code login was found at %s" % own)
        shutil.copyfile(own, dest)
    os.chmod(dest, 0o600)
    return dest


def cmd_run(args):
    spec = read_json(args.phrases)
    names = sorted(d for d in os.listdir(os.path.join(ROOT, "skills"))
                   if os.path.exists(os.path.join(ROOT, "skills", d, "SKILL.md")))
    out = os.path.abspath(args.out or tempfile.mkdtemp(prefix="mstack-release-"))
    profile, mhome, sandbox = (os.path.join(out, d) for d in ("claude-home", "mstack-home", "sandbox"))
    for d in (profile, mhome, sandbox):
        os.makedirs(d, exist_ok=True)
    os.chmod(profile, 0o700)
    env = dict(os.environ, CLAUDE_CONFIG_DIR=profile, MSTACK_HOME=mhome)
    local = os.path.isdir(args.source)
    source = os.path.abspath(args.source) if local else args.source
    lent, removed = None, True

    def claude(argv, log, cwd=out, timeout=300):
        try:
            done = subprocess.run([args.claude] + argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=timeout)
            text, err, code = done.stdout, done.stderr, done.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            text, err, code = "", str(exc), 1
        with open(os.path.join(out, log), "w", encoding="utf-8") as fh:
            fh.write(text + ("\n[standard error]\n" + err if err.strip() else ""))
        return code, text

    try:
        if args.lend_login or args.login_file:
            lent = lend(profile, args.login_file)
        if claude(["plugin", "marketplace", "add", source], "01-marketplace-add.log")[0] != 0:
            raise RuntimeError("the marketplace could not be added (see 01-marketplace-add.log in %s)" % out)
        if claude(["plugin", "install", "mstack@mstack"], "02-install.log")[0] != 0:
            raise RuntimeError("the plugin could not be installed (see 02-install.log in %s)" % out)
        cache = os.path.join(profile, "plugins", "cache", "mstack", "mstack")
        versions = sorted(os.listdir(cache)) if os.path.isdir(cache) else []
        version = versions[-1] if versions else "unknown"

        def ask(item):
            code, text = claude(["-p", "--model", args.model, "%s\n\n%s" % (item["phrase"], spec["ask"])],
                                "%s.out" % item["id"], cwd=sandbox)
            got = picked(text, names) if code == 0 else None
            return {"id": item["id"], "phrase": item["phrase"], "expected": item["expected"], "picked": got,
                    "right": got in item["expected"]}

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
            rows = list(pool.map(ask, spec["phrases"]))
    except RuntimeError as exc:
        return fail(args, str(exc))
    finally:
        if lent and os.path.exists(lent):
            os.remove(lent)
        removed = not os.path.exists(os.path.join(profile, ".credentials.json"))
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(mhome, ignore_errors=True)
    result = {"version": version, "date": datetime.date.today().isoformat(),
              "source": "the release candidate folder" if local else "GitHub (%s)" % source,
              "agent": "Claude Code", "model": args.model,
              "right": sum(1 for r in rows if r["right"]), "total": len(rows), "rows": rows,
              "login_removed": removed}
    with open(os.path.join(out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    lines = ["%s: %d of %d phrases reached the right skill (version %s, %s)." % (
        result["agent"], result["right"], result["total"], version, result["source"])]
    lines += ["  %-4s %-5s picked %-16s expected %s" % (r["id"], "right" if r["right"] else "MISS", r["picked"],
                                                       " or ".join(r["expected"])) for r in rows]
    lines.append("The clean profile and its login copy are deleted. Result: %s" % os.path.join(out, "result.json"))
    say(args, dict(result, ok=True, out=out), "\n".join(lines))


def long_date(iso):
    d = datetime.date.fromisoformat(iso)
    return "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)


def vkey(version):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.]", version))


def generated(results):
    """The generated text for docs/evidence.md and README.md, from the recorded results (newest first)."""
    rows = sorted(results, key=lambda r: (vkey(r["version"]), r["date"]), reverse=True)
    table = ["| Release | Date | Installed from | Agent | Phrases that reached the right skill |", "|---|---|---|---|---|"]
    table += ["| %s | %s | %s | %s (%s) | **%d of %d** |" % (r["version"], long_date(r["date"]), r["source"], r["agent"],
                                                            r["model"], r["right"], r["total"]) for r in rows]
    top = rows[0] if rows else None
    readme = ("- **%d of %d** plain phrases reached the right skill on a clean install of %s (%s). Every release\n"
              "  reruns them before it ships." % (top["right"], top["total"], top["version"], long_date(top["date"]))
              ) if top else ""
    return {"docs/evidence.md": "\n".join(table), "README.md": readme}


def swap(text, body):
    a, b = text.find(START), text.find(END)
    if a < 0 or b < a:
        return None
    return text[:a + len(START)] + "\n" + body + "\n" + text[b:]


def store(root):
    return os.path.join(root, "docs", "evidence", "routing.json")


def stale(root, results):
    """The files whose generated part differs from the recorded results."""
    out = []
    for rel, body in generated(results).items():
        path = os.path.join(root, rel)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if swap(text, body) != text:
            out.append(rel)
    return out


def cmd_write(args):
    path = store(args.root)
    results = read_json(path)["results"] if os.path.exists(path) else []
    entry = None
    if args.result:
        new = read_json(args.result)
        entry = {k: new[k] for k in ("version", "date", "source", "agent", "model", "right", "total")}
        entry["rows"] = [{k: r[k] for k in ("id", "expected", "picked", "right")} for r in new["rows"]]
        same = (entry["version"], entry["agent"], entry["source"])
        results = [r for r in results if (r["version"], r["agent"], r["source"]) != same] + [entry]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"results": results}, fh, indent=2)
            fh.write("\n")
    changed = []
    for rel, body in generated(results).items():
        target = os.path.join(args.root, rel)
        with open(target, encoding="utf-8") as fh:
            text = fh.read()
        new_text = swap(text, body)
        if new_text is None:
            return fail(args, "%s has no %s ... %s part to write into" % (rel, START, END))
        if new_text != text:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(new_text)
            changed.append(rel)
    said = "Recorded %s: %d of %d. " % (entry["version"], entry["right"], entry["total"]) if entry else ""
    say(args, {"ok": True, "recorded": entry["version"] if entry else None, "changed": changed},
        "%sRewrote: %s." % (said, ", ".join(changed) or "nothing"))


def cmd_gate(args):
    version = read_json(os.path.join(args.root, ".claude-plugin", "plugin.json"))["version"]
    path = store(args.root)
    results = read_json(path)["results"] if os.path.exists(path) else []
    problems = []
    if not any(r["version"] == version for r in results):
        problems.append("no routing result is recorded for version %s: run tests/release_check.py run, then write" % version)
    problems += ["%s: the generated part differs from docs/evidence/routing.json (run write again)" % rel
                 for rel in stale(args.root, results)]
    say(args, {"ok": not problems, "version": version, "problems": problems},
        "\n".join(problems) if problems else "The evidence is current for version %s." % version)
    sys.exit(1 if problems else 0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--source", required=True)
    r.add_argument("--out")
    r.add_argument("--model", default="sonnet")
    r.add_argument("--parallel", type=int, default=5)
    r.add_argument("--phrases", default=os.path.join(ROOT, "tests", "release_phrases.json"))
    r.add_argument("--claude", default="claude", help="the Claude Code program to run")
    r.add_argument("--lend-login", action="store_true")
    r.add_argument("--login-file")
    w = sub.add_parser("write")
    w.add_argument("--result")
    g = sub.add_parser("gate")
    for p in (r, w, g):
        p.add_argument("--json", action="store_true")
        p.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    {"run": cmd_run, "write": cmd_write, "gate": cmd_gate}[args.cmd](args)


if __name__ == "__main__":
    main()
