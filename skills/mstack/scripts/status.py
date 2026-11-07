#!/usr/bin/env python3
"""Status across everything: every project mStack knows, with what waits for the person first.

Python 3.9 or later, standard library only. Read only: it answers nothing and sends nothing.

  status [--project <folder>] [--json] [--render] [--days N]

Projects come from the rules files, the outcomes, the crew config and queue, and the multi-evaluator folders under
the mStack home, merged by folder. For each: what waits for the person (with the command that answers it), what is
running, the latest review, what shipped last, the State lines of its HANDOFF.md, and whether it has a rules file.
Then the folders that are gone, and the crew's usage against the cap. --render writes status.md in today's outbox and
makes a PDF and a phone-width PNG of it (through away-mode); the agent sends those when the person is away.
"""
import argparse
import datetime
import json
import os
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules as rules_file  # noqa: E402
import status_sources as src  # noqa: E402

WIDTH = 60


def gather(only=None, days=7):
    records, crew = src.collect()
    crew_cmd = src.tool("crew", "crew.py")
    projects, gone = [], []
    for path, rec in records.items():
        if only and path != only and not path.startswith(only + os.sep):
            continue
        if not os.path.isdir(path):
            gone.append({"name": rec["name"], "path": path, "refs": sorted(set(rec["kinds"]))})
            continue
        projects.append({"name": rec["name"], "path": path,
                         "waits_for_you": [dict(w, project=rec["name"], path=path) for w in src.waits_for(rec, crew_cmd)],
                         "running": src.running_for(rec, days), "latest_review": src.latest_review(rec, days),
                         "last_shipped": src.shipped(path), "state": src.state_lines(path),
                         "rules_file": os.path.isfile(os.path.join(rules_file.project_dir(path), "rules.md"))})
    projects.sort(key=lambda p: (-len(p["waits_for_you"]), p["name"].lower()))
    gone.sort(key=lambda g: g["path"])
    waits = [w for p in projects for w in p["waits_for_you"]]
    for x in [] if only else crew["loose"]:
        waits.append({"project": "crew", "path": "", "kind": "crew question",
                      "text": "crew asks: %s%s" % (x.get("question", ""), " (default: %s)" % x["default"] if x.get("default") else ""),
                      "command": '%s answer %s "..."' % (crew_cmd, x.get("job") or x["key"])})
    return {"generated": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "days": days,
            "waits_for_you": waits, "projects": projects, "gone": gone, "usage": src.usage_block()}


# ---------------------------------------------------------------- the text (the same for the terminal and status.md)

def review_line(r):
    scores = ", ".join("%s %s" % kv for kv in sorted(r["overall"].items())) or "no scores yet"
    return "round %d, %s; %s" % (r["round"], "ready for people" if r["ready"] else "not ready yet", scores)


def usage_lines(u):
    if not u.get("crew"):
        return ["Crew is not set up, so there is no usage to show."]
    out = []
    for name, b in u["runners"].items():
        if b["windows"]:
            for w in b["windows"]:
                out.append("%s, %s window: %.0f%% used" % (name, w["window"].replace("_", " "), w["percent"]))
        else:
            out.append("%s: usage cannot be read here" % name)
        if b["mode"] != "ok":
            out.append("%s: %s" % (name, b["why"]))
    out.append("Crew is %s." % ("not running: %s" % u["stopped"] if u["stopped"] else "running"))
    out.append("Quiet hours now: %s." % ("yes" if u["quiet_now"] else "no"))
    out.append("Last digest: %s" % (u["last_digest"] or "none yet"))
    return out


def build_text(d, md=False):
    out = []

    def block(title):
        if out:
            out.append("")
        out.append(("# " if md else "") + title)

    def item(text, indent=0):
        out.append(textwrap.fill(text, WIDTH, initial_indent=" " * indent + "- ", subsequent_indent=" " * (indent + 2),
                                 break_long_words=False, break_on_hyphens=False))

    def command(cmd):
        out.append("  - Run: `%s`" % cmd if md else "    Run: %s" % cmd)

    block("Waits for you")
    if not d["waits_for_you"]:
        out.append("Nothing waits for you.")
    last = None
    for w in d["waits_for_you"]:
        if w["project"] != last:
            out.append(("**%s**" if md else "%s") % w["project"])
            last = w["project"]
        item(w["text"])
        command(w["command"])
    for p in d["projects"]:
        block(p["name"])
        out.append("Path: " + p["path"])
        if p["waits_for_you"]:
            out.append("%d waiting for you (listed at the top)." % len(p["waits_for_you"]))
        if p["state"]:
            out.append("State:")
        for line in p["state"]:
            item(line)
        for line in p["running"]:
            item("Running: " + line)
        out.append(textwrap.fill("Latest review: " + (review_line(p["latest_review"]) if p["latest_review"] else "none in the last %d days" % d["days"]),
                                 WIDTH, subsequent_indent="  ", break_long_words=False))
        out.append("Last shipped: %s" % (p["last_shipped"] or "nothing yet"))
        out.append("Rules file: %s" % ("yes" if p["rules_file"] else "no"))
    if d["gone"]:
        block("Gone")
        for g in d["gone"]:
            item("%s (%s)" % (g["path"], ", ".join(g["refs"])))
    block("Usage")
    for line in usage_lines(d["usage"]):
        item(line)
    return "\n".join(out)


# ---------------------------------------------------------------- commands

def render(d):
    folder = src.home("outbox", datetime.date.today().isoformat())
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "status.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_text(d, md=True) + "\n")
    import away_render
    result = away_render.render(path, out_dir=folder)
    return {"status_md": path, "files": [f.get("path", "") for f in result.get("files", [])], "notes": result.get("notes", [])}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="status", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="only this project folder")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--render", action="store_true", help="write status.md in the outbox, then a PDF and a phone PNG")
    ap.add_argument("--days", type=int, default=7, help="how far back running work and reviews are shown (default 7)")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["status"]:                 # `status.py status ...` works the same as `mstack status ...`
        argv = argv[1:]
    args = ap.parse_args(argv)
    d = gather(src.norm(args.project) if args.project else None, args.days)
    if args.render:
        r = render(d)
        if args.json:
            print(json.dumps(dict(d, rendered=r), indent=2))
        else:
            print("status.md: " + r["status_md"])
            for f in r["files"]:
                print("file: " + f)
            for n in r["notes"]:
                print("note: " + n)
        return
    print(json.dumps(d, indent=2) if args.json else build_text(d))


if __name__ == "__main__":
    main()
