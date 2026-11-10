"""What the person has taught each skill: learn, learned (numbered) and unlearn.

Python 3.9 or later, standard library only. Rules live in <home>/learned/<skill>.md, one line starting "- " each.
"""
import datetime
import os

from mbase import Fail, check_skill, home, say, skills


def path_for(skill):
    return home("learned", skill + ".md")


def read_lines(skill):
    try:
        with open(path_for(skill), encoding="utf-8") as fh:
            return fh.read().split("\n")
    except OSError:
        return []


def read_rules(skill):
    """The rule lines of a skill's learned file, in order: [{"n", "rule", "at"}], at being the line's place in the file."""
    out = []
    for i, line in enumerate(read_lines(skill)):
        if line.startswith("- "):
            out.append({"n": len(out) + 1, "rule": line[2:].strip(), "at": i})
    return out


def cmd_learn(args):
    check_skill(args.skill)
    rule = " ".join(args.rule.split())
    if not rule:
        raise Fail("A rule cannot be empty.", 2)
    os.makedirs(home("learned"), exist_ok=True)
    path = path_for(args.skill)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as fh:
        if new:
            fh.write("# What this person has taught %s\n\nAccepted improvements, newest last. They win over the "
                     "skill's own SKILL.md where the two differ.\n\n" % args.skill)
        fh.write("- %s (%s)\n" % (rule, datetime.date.today().isoformat()))
    say(args, {"ok": True, "skill": args.skill, "file": path, "rules": len(read_rules(args.skill))},
        "kept in %s" % path)


def cmd_learned(args):
    if args.skill:
        check_skill(args.skill)
    names = [args.skill] if args.skill else [s["name"] for s in skills()]
    found = dict((n, read_rules(n)) for n in names)
    found = dict((n, r) for n, r in found.items() if r)
    data = {"ok": True, "learned": dict((n, [{"n": x["n"], "rule": x["rule"]} for x in r]) for n, r in found.items())}
    if not found:
        say(args, data, "Nothing learned yet for %s." % (args.skill or "any skill"))
        return
    blocks = []
    for n, r in found.items():
        head = "" if args.skill else "%s (%s)\n" % (n, path_for(n))
        blocks.append(head + "\n".join("%d. %s" % (x["n"], x["rule"]) for x in r))
    say(args, data, "\n\n".join(blocks))


def cmd_unlearn(args):
    check_skill(args.skill)
    rules = read_rules(args.skill)
    if not 1 <= args.number <= len(rules):
        raise Fail("%s has %d learned rule%s; there is no number %d. Run: mstack.py learned %s" % (
            args.skill, len(rules), "" if len(rules) == 1 else "s", args.number, args.skill), 1)
    gone = rules[args.number - 1]
    path = path_for(args.skill)
    if len(rules) == 1:
        os.remove(path)                                  # nothing left: drop the file so the session start note stops pointing at it
    else:
        lines = read_lines(args.skill)
        del lines[gone["at"]]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    say(args, {"ok": True, "skill": args.skill, "removed": {"n": gone["n"], "rule": gone["rule"]},
               "remaining": len(rules) - 1},
        "removed rule %d from %s: %s" % (gone["n"], args.skill, gone["rule"]))
