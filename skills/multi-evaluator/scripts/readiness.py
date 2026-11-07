"""When is a product ready for real people? The stopping rule, the noise check and "do these next".

Used by eval_loop.py (status, next step) and report.py. Standard library only.

The stopping rule ("ready for people"): every journey scores READY_SCORE or better from every counting
reviewer, no high-severity fix is open, the reviewers are within READY_SPREAD of each other on every
journey, and all of that has held for READY_ROUNDS rounds in a row. A unanimous 10 is a flag to double
check, not the goal. Reviewers of kind "chat" (a web chat that saw screenshots, not the live product) do
not count toward readiness; they are tie breakers.

The noise check: a frozen control (the same screenshots every round) is scored every round as journey
"control". How far its score moves tells you how much of a change is noise.
"""
import os

READY_SCORE = 9
READY_SPREAD = 1
READY_ROUNDS = 2
MAX_ROUNDS = 6
CONTROL = "control"


def round_reviewers(p, n):
    """Reviewer ids that round n had scoring briefs for, or today's config when briefs are not written yet."""
    config_order = [r["id"] for r in p.enabled_reviewers()]
    config_ids = set(config_order)
    briefs_dir = p.rdir(n, "briefs")
    if not os.path.isdir(briefs_dir):
        return list(config_order)
    found = []
    for f in os.listdir(briefs_dir):
        if f.endswith(".md") and not f.endswith("-compare.md"):
            rid = f[:-3]
            if rid in config_ids:
                found.append(rid)
    if not found:
        return list(config_order)
    return [rid for rid in config_order if rid in found]


def brief_reviewers_dropped(p, n):
    """Brief files for reviewer ids no longer in the config (dropped from round_reviewers)."""
    config_ids = {r["id"] for r in p.reviewers()}
    briefs_dir = p.rdir(n, "briefs")
    if not os.path.isdir(briefs_dir):
        return []
    return sorted(f[:-3] for f in os.listdir(briefs_dir) if f.endswith(".md") and not f.endswith("-compare.md")
                  and f[:-3] not in config_ids)


def counting_reviewers(p, n):
    """Reviewers whose scores count toward readiness: everyone except web chat reviewers."""
    kinds = dict((r["id"], r.get("kind")) for r in p.reviewers())
    return [rid for rid in round_reviewers(p, n) if kinds.get(rid) != "chat"]


def journey_ids(p):
    return [j["id"] for j in p.journeys()]


def scores_of(verdict, key="score"):
    return dict((j.get("id"), j.get(key)) for j in verdict.get("journeys", []) if isinstance(j, dict))


def num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def round_check(p, n):
    """One round against the stopping rule: {"ready": bool, "reasons": [...], "disagreements": {...}, ...}."""
    v = p.verdicts(n)
    want = counting_reviewers(p, n)
    jids = journey_ids(p)
    reasons, disagreements, high, blockers = [], {}, [], []
    missing = [w for w in want if w not in v]
    if missing:
        reasons.append("no verdict yet from %s" % ", ".join(missing))
    for jid in jids:
        got = dict((w, scores_of(v[w]).get(jid)) for w in want if w in v)
        vals = [s for s in got.values() if num(s)]
        low = [w for w, s in got.items() if num(s) and s < READY_SCORE]
        if low:
            reasons.append("journey %s is below %d from %s" % (jid, READY_SCORE, ", ".join(low)))
        if len(vals) > 1 and max(vals) - min(vals) > READY_SPREAD:
            disagreements[jid] = round(max(vals) - min(vals), 1)
            reasons.append("the reviewers disagree by %s on journey %s" % (disagreements[jid], jid))
    for w in want:
        for j in v.get(w, {}).get("journeys", []):
            for f in j.get("fixes", []) or []:
                if isinstance(f, dict) and f.get("severity") == "high":
                    high.append({"reviewer": w, "journey": j.get("id"), "fix": f.get("fix", "")})
                if isinstance(f, dict) and f.get("severity") == "blocker":
                    blockers.append({"reviewer": w, "journey": j.get("id"), "fix": f.get("fix", "")})
    if blockers:
        reasons.append("%d blocker%s open" % (len(blockers), "" if len(blockers) == 1 else "s"))
    if high:
        reasons.append("%d high-severity fix%s still open" % (len(high), "" if len(high) == 1 else "es"))
    unanimous = bool(want) and not missing and all(scores_of(v[w]).get(j) == 10 for w in want for j in jids)
    return {"round": n, "ready": not reasons, "reasons": reasons, "disagreements": disagreements, "high_open": high, "blockers_open": blockers,
            "unanimous_ten": unanimous}


def ready_for_people(p):
    """The stopping rule over the latest rounds: ready only when READY_ROUNDS rounds in a row pass."""
    ns = p.round_numbers()
    recent = ns[-READY_ROUNDS:]
    checks = [round_check(p, k) for k in recent]
    held = len(checks) == READY_ROUNDS and all(c["ready"] for c in checks)
    out = {"ready": held, "rounds_needed": READY_ROUNDS, "rounds_held": sum(1 for c in checks if c["ready"]),
           "latest": checks[-1] if checks else None}
    if checks and checks[-1]["ready"] and not held:
        out["note"] = "this round passes; it must hold for %d rounds in a row" % READY_ROUNDS
    return out


def control_noise(p):
    """How far each reviewer's score of the frozen control has moved across rounds (None if no control)."""
    if not p.cfg.get("control"):
        return None
    moves = {}
    for n in p.round_numbers():
        for who, v in p.verdicts(n).items():
            s = scores_of(v).get(CONTROL)
            if num(s):
                moves.setdefault(who, []).append(s)
    out = dict((who, round(max(ss) - min(ss), 1)) for who, ss in moves.items() if ss)
    return {"per_reviewer": out, "band": max(out.values()) if out else 0, "rounds": len(p.round_numbers())}


def do_next(p, n, limit=8):
    """The fixes to make next: blockers first, then those on journeys every reviewer flagged, then high
    severity, then the biggest "if fixed" gap, then the lowest score."""
    v = p.verdicts(n)
    who_flagged = {}
    items = []
    for who, d in v.items():
        for j in d.get("journeys", []):
            jid = j.get("id")
            fixes = [f for f in (j.get("fixes", []) or []) if isinstance(f, dict)]
            if fixes:
                who_flagged.setdefault(jid, set()).add(who)
            gap = (j.get("if_fixed") or 0) - (j.get("score") or 0) if num(j.get("score")) and num(j.get("if_fixed")) else 0
            for f in fixes:
                items.append({"reviewer": who, "journey": jid, "severity": f.get("severity", "low"), "where": f.get("where", ""),
                              "problem": f.get("problem", ""), "fix": f.get("fix", ""), "gap": gap, "score": j.get("score")})
    rank = {"blocker": -1, "high": 0, "medium": 1, "low": 2}
    for it in items:
        it["agreed"] = len(who_flagged.get(it["journey"], ())) >= max(2, min(2, len(v)))
    items.sort(key=lambda it: (0 if it["severity"] == "blocker" else 1, 0 if it["agreed"] else 1, rank.get(it["severity"], 3), -it["gap"],
                               it["score"] if num(it["score"]) else 10))
    return items[:limit]


def round_state(p, n):
    v = p.verdicts(n)
    want = round_reviewers(p, n)
    prev = round_reviewers(p, n - 1) if n > 1 else []
    joined = [rid for rid in want if rid not in prev] if n > 1 else []
    dropped = brief_reviewers_dropped(p, n)
    scores = dict((who, scores_of(d)) for who, d in v.items())
    briefs = p.rdir(n, "briefs")
    check = round_check(p, n)
    out = {
        "round": n,
        "shots": len(p.shots(n)),
        "briefs": sorted(f[:-3] for f in os.listdir(briefs) if f.endswith(".md")) if os.path.isdir(briefs) else [],
        "verdicts": sorted(v),
        "reviewers": want,
        "joined": joined,
        "missing_verdicts": [w for w in want if w not in v],
        "overall": dict((who, d.get("overall")) for who, d in v.items()),
        "scores": scores,
        "ready": check["ready"],
        "not_ready_because": check["reasons"],
        "disagreements": check["disagreements"],
        "unanimous_ten": check["unanimous_ten"],
        "all_ten": check["unanimous_ten"],
    }
    if dropped:
        out["dropped_reviewers"] = dropped
        out["note"] = "briefs on disk for %s, but those ids are not in the config now" % ", ".join(dropped)
    return out


def next_step(p):
    n = p.latest()
    if not p.journeys():
        return "Add journeys (and views) to %s" % os.path.join(p.dir, "mstack-eval.json")
    if n is None:
        return "start-round (round 1 is the starting point)"
    st = round_state(p, n)
    if st["shots"] == 0 and p.views():
        return "capture --round %d" % n
    if len(st["briefs"]) < len(p.enabled_reviewers()):
        return "brief --round %d" % n
    if st["missing_verdicts"]:
        parts = []
        for rid in st["missing_verdicts"]:
            r = p.reviewer(rid) or {}
            if r.get("kind") == "command":
                parts.append("review --round %d --only %s" % (n, rid))
            elif r.get("kind") == "chat":
                parts.append("open a new private chat with %s in the person's browser, paste %s, save the reply, then: "
                             "verdict --round %d --reviewer %s <reply>" % (r.get("name", rid), p.rdir(n, "briefs", rid + ".md"), n, rid))
            else:
                parts.append("give %s to a fresh %s reviewer, then: verdict --round %d --reviewer %s <reply.json>" % (
                    p.rdir(n, "briefs", rid + ".md"), r.get("name", rid), n, rid))
        return "; ".join(parts)
    report = os.path.join(p.dir, "report.html")
    vdir = p.rdir(n, "verdicts")
    newest = max(os.path.getmtime(os.path.join(vdir, f)) for f in os.listdir(vdir))
    if not os.path.exists(report) or os.path.getmtime(report) < newest:
        return "report"
    rp = ready_for_people(p)
    if rp["ready"]:
        return ("ready for people: every journey is %d or better from every reviewer, no high-severity fix is open, the "
                "reviewers agree within %d, and it has held for %d rounds. If you can, have a few first-time people try the journeys "
                "(record them in rounds/r%d/people.md) and turn what they find into the next round's journeys." % (
                    READY_SCORE, READY_SPREAD, READY_ROUNDS, n))
    flag = " A unanimous 10 this round is a flag to double check the brief and the journeys, not a finish line." if st["unanimous_ten"] else ""
    if st["ready"]:
        return "this round passes the stopping rule; make no big changes, run one more round so it holds for %d rounds.%s" % (
            READY_ROUNDS, flag)
    cap = int(p.cfg.get("max_rounds", MAX_ROUNDS) or MAX_ROUNDS)
    if n >= cap:
        return ("round cap reached (%d rounds, not yet ready: %s). Stop and talk to the person: are the journeys or "
                "criteria asking for something the product should not do? Raise max_rounds in the config to go on." % (
                    n, "; ".join(st["not_ready_because"])))
    return "fix the reviewers' proposals in the product (see \"Do these next\" in the report; not ready because: %s), then start-round.%s" % (
        "; ".join(st["not_ready_because"]), flag)
