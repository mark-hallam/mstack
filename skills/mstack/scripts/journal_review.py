"""The private journal and "review my skills": log how a skill went, and gather the journal into evidence.

Python 3.9 or later, standard library only. Reading a review never changes anything; only `review --done` marks
the journal as reviewed and writes the day's evidence file.
"""
import datetime
import json
import os

from mbase import SKILLS, check_skill, home, say, skills

OUTCOMES = ("reached", "partial", "not-reached")


def journal(name):
    path = home("journal", name + ".jsonl")
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def marks():
    path = home("reviews", "last.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def last_review(name):
    return marks().get(name)


def cmd_log(args):
    check_skill(args.skill)
    entry = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "skill": args.skill, "outcome": args.outcome,
             "needed_user": args.needed_user, "stalled": args.stalled, "corrections": args.correction, "note": args.note}
    os.makedirs(home("journal"), exist_ok=True)
    with open(home("journal", args.skill + ".jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    say(args, {"ok": True, "skill": args.skill, "uses": len(journal(args.skill))},
        "recorded (%d uses of %s so far)" % (len(journal(args.skill)), args.skill))


def tally(items):
    counts = {}
    for i in items:
        key = i.strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def gather(names):
    report = {}
    seen = marks()
    for name in names:
        rows = journal(name)
        new = rows[(seen.get(name) or {}).get("uses", 0):]
        report[name] = {
            "uses": len(rows), "new_since_last_review": len(new),
            "outcomes": dict((o, sum(1 for r in new if r.get("outcome") == o)) for o in OUTCOMES),
            "needed_user": tally(x for r in new for x in (r.get("needed_user") or [])),
            "stalled": tally(x for r in new for x in (r.get("stalled") or [])),
            "corrections": tally(x for r in new for x in (r.get("corrections") or [])),
            "notes": [r["note"] for r in new if r.get("note")],
            "skill_file": os.path.join(SKILLS, name, "SKILL.md"),
            "learned_file": home("learned", name + ".md"),
        }
    return report


def evidence_text(report, day):
    lines = ["# mStack skills review, %s" % day, "",
             "Evidence from the private journal since each skill's last review. For each skill: propose concrete "
             "edits (a rule to add to its learned file, or a change to its SKILL.md), show them to the person, and "
             "keep only the ones they accept with: mstack.py learn <skill> \"<rule>\". Then run: mstack.py review --done.", ""]
    for name, r in report.items():
        if not r["new_since_last_review"]:
            continue
        lines += ["## %s: %d new uses (%s)" % (name, r["new_since_last_review"], ", ".join(
            "%s %d" % kv for kv in r["outcomes"].items())), ""]
        for label, key in (("Where it needed the person", "needed_user"), ("Where it stalled", "stalled"),
                           ("The person's corrections", "corrections")):
            if r[key]:
                lines.append("%s:" % label)
                lines += ["- %s (%d)" % kv for kv in r[key]]
                lines.append("")
    return "\n".join(lines) + "\n"


def cmd_review(args):
    """A plain read (also --dry-run) writes nothing and answers the same every time; --done marks the journal reviewed."""
    if args.skill:
        check_skill(args.skill)
    report = gather([args.skill] if args.skill else [s["name"] for s in skills()])
    day = datetime.date.today().isoformat()
    path = home("reviews", "%s.md" % day)
    text = evidence_text(report, day)
    done = bool(args.done) and not args.dry_run
    if done:
        os.makedirs(home("reviews"), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        mine = marks()
        for name, r in report.items():
            mine[name] = {"uses": r["uses"], "at": day}
        with open(home("reviews", "last.json"), "w", encoding="utf-8") as fh:
            json.dump(mine, fh, indent=2)
    say(args, {"ok": True, "review": path, "marked_reviewed": done, "skills": report},
        ("marked the journal as reviewed and wrote %s" % path) if done else
        text + "When the accepted rules are kept with learn, run: mstack.py review --done")
