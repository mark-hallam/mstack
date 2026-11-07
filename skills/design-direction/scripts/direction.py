#!/usr/bin/env python3
"""mStack design-direction: find the look of a new product, then lock it. One command line tool for people and agents.

  init      write direction.json and BRIEF.md in a folder
  options   start a round of up to four whole directions (command builders run now, agent builders are left to you)
  shots     capture each file at desktop and phone, light and dark
  compare   build the comparison page from compare.json; refuses to call the round complete until it is filled in
  pick      record the person's choice (--option b, or --variant 2)
  narrow    start a round of up to three variants that differ in structure only, on the picked look
  lock      write brand.json (tokens, fonts, radii, rules) from the picked file and check contrast
  status    where the direction is and what to do next

Python 3.9 or later, standard library only. shots also needs Node.js 18 or later and Google Chrome or Chromium.
Every command takes --dir, the folder that holds direction.json (default: the current folder), and --json.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from direction_build import start_round  # noqa: E402
from direction_common import CONFIG_NAME, SKILL, Project, fail, label, read, say, write  # noqa: E402
from direction_compare import cmd_compare  # noqa: E402
from direction_lock import cmd_lock  # noqa: E402
from direction_shots import cmd_shots  # noqa: E402


def cmd_init(args):
    folder = os.path.abspath(args.dir or ".")
    if os.path.exists(os.path.join(folder, CONFIG_NAME)):
        fail("%s already exists in %s." % (CONFIG_NAME, folder))
    cfg = json.loads(read(os.path.join(SKILL, "templates", "direction.json")))
    cfg["name"], cfg["taste"] = args.name, args.taste or ""
    taste = args.taste or "[[One line: the feel the person wants, for example \"Apple-clean, familiar, calm, light first\".]]"
    brief = read(os.path.join(SKILL, "templates", "BRIEF.md")).replace("{name}", args.name).replace("{taste}", taste)
    write(os.path.join(folder, CONFIG_NAME), json.dumps(cfg, indent=2) + "\n")
    write(os.path.join(folder, cfg["brief"]), brief)
    say(args, {"dir": folder, "config": os.path.join(folder, CONFIG_NAME), "brief": os.path.join(folder, cfg["brief"]),
               "next": "Write BRIEF.md with the person: fill in every [[placeholder]]."},
        "wrote %s and %s\nNext: write BRIEF.md with the person (fill in every [[placeholder]]), then run options." % (
            CONFIG_NAME, cfg["brief"]))


def cmd_pick(args):
    p = Project(args.dir)
    if bool(args.option) == bool(args.variant):
        fail("Say which: --option <letter> or --variant <number>.")
    mode = "options" if args.option else "narrow"
    item = ("option-" + args.option.lower().replace("option-", "")) if args.option else "variant-" + str(args.variant).replace("variant-", "")
    r = p.round(args.round) if args.round else p.latest(mode)
    if not r or r["mode"] != mode or item not in r["ids"] or not os.path.exists(p.item_file(r["n"], item)):
        fail("%s is not a built file in a %s round." % (label(item), mode))
    rel = os.path.relpath(p.item_file(r["n"], item), p.dir)
    p.cfg["picked"] = {"id": item, "label": label(item).lower(), "kind": item.partition("-")[0], "round": r["n"], "file": rel}
    r["picked"] = item
    p.save()
    say(args, {"picked": p.cfg["picked"], "next": status(p)["next"]}, "picked %s in round %d (%s)\nNext: %s" % (label(item), r["n"], rel, status(p)["next"]))


def status(p):
    me = "python3 %s" % os.path.join(HERE, "direction.py")
    cfg, rounds = p.cfg, p.rounds()
    r = rounds[-1] if rounds else None
    info = {"name": p.name, "locked": bool(cfg.get("locked")), "picked": cfg.get("picked"), "round": r["n"] if r else None,
            "mode": r["mode"] if r else None, "rounds": [{"n": x["n"], "mode": x["mode"], "complete": x.get("complete", False)} for x in rounds]}
    if cfg.get("locked"):
        stage, nxt = "locked", ("The look is locked (brand.json). Hand over to multi-evaluator: put \"brand\": \"%s\" in its mstack-eval.json so its "
                                "briefs list the brand rules, and build the product from the tokens. A different look needs the person's yes "
                                "and options --relook." % os.path.join(p.dir, "brand.json"))
    elif p.brief_open_items():
        stage, nxt = "brief", "Write BRIEF.md with the person: fill in every [[placeholder]] (%d left)." % len(p.brief_open_items())
    elif not r:
        stage, nxt = "options", "Run options --n 3 (at most 4): command builders run now; for agent builders, write the files it lists."
    elif len(p.built(r)) < len(r["ids"]):
        missing = [i for i in r["ids"] if i not in p.built(r)]
        stage, nxt = "build", "Write the missing files in %s: %s (run %s %s again to retry command builders)." % (
            p.rdir(r["n"], "options"), ", ".join(missing), "options" if r["mode"] == "options" else "narrow", "--dir " + p.dir)
    elif any(not os.path.exists(p.rdir(r["n"], "shots", n + ".png")) for i in r["ids"] for n in p.shot_names(i)):
        stage, nxt = "shots", "Run shots to capture each file at desktop and phone, light and dark."
    elif not r.get("complete"):
        what = "a recommendation (base, borrow, cost, first_principles)" if r["mode"] == "options" else "two to four numbered questions"
        stage, nxt = "compare", "Edit %s: strengths and watch-outs for each, and %s. Then run compare." % (p.rdir(r["n"], "compare.json"), what)
    elif not (cfg.get("picked") and cfg["picked"]["round"] == r["n"]):
        stage, nxt = "pick", "Show the person %s and ask them to pick (pick --%s <%s>). The decision is theirs." % (
            p.rdir(r["n"], "index.html"), "option" if r["mode"] == "options" else "variant", "letter" if r["mode"] == "options" else "number")
    elif r["mode"] == "options":
        stage, nxt = "narrow", "Run narrow --n 3 to try structure on the picked look, or lock if the person is happy with it as it is."
    else:
        stage, nxt = "lock", "Run lock to write brand.json from the picked variant, then hand over to multi-evaluator."
    info.update(stage=stage, next=nxt)
    return info


def cmd_status(args):
    info = status(Project(args.dir))
    say(args, info, "%s: %s\nNext: %s" % (info["name"], info["stage"], info["next"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def add(name, fn, **kw):
        s = sub.add_parser(name, help=kw.pop("help", None))
        s.add_argument("--dir", default=".", help="the folder that holds direction.json")
        s.add_argument("--json", action="store_true")
        s.set_defaults(fn=fn)
        return s
    s = add("init", cmd_init, help="write direction.json and BRIEF.md")
    s.add_argument("--name", required=True)
    s.add_argument("--taste", help="one line, for example \"Apple-clean, familiar, calm, light first\"")
    s = add("options", lambda a: start_round(a, "options", a.n), help="start a round of directions")
    s.add_argument("--n", type=int, default=3)
    s.add_argument("--round", type=int)
    s.add_argument("--force", action="store_true", help="rebuild files that already exist")
    s.add_argument("--relook", action="store_true", help="the person wants a different look: unlock and draw new directions")
    s = add("narrow", lambda a: start_round(a, "narrow", a.n), help="start a round of structure-only variants")
    s.add_argument("--n", type=int, default=3)
    s.add_argument("--round", type=int)
    s.add_argument("--force", action="store_true")
    for name, fn in (("shots", cmd_shots), ("compare", cmd_compare)):
        s = add(name, fn)
        s.add_argument("--round", type=int)
    s = add("pick", cmd_pick, help="record the person's choice")
    s.add_argument("--option")
    s.add_argument("--variant")
    s.add_argument("--round", type=int)
    add("lock", cmd_lock, help="write brand.json")
    add("status", cmd_status, help="where it is and what to do next")
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
