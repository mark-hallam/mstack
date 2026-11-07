"""Re-grade last round's proposed fixes, one by one. Used by briefs.py, verdicts.py and report_parts.py.

From round 2 the comparison brief lists the fixes proposed last round (the "Do these next" list plus the
reviewer's own fixes), each with an id (f1, f2...). The reviewer's comparison reply answers every id with a
state and the exact words or state on screen that prove it. The list is kept beside the brief so the answer
can be checked when it is saved.
"""
import html
import json
import os

import readiness

STATES = ("done", "partly", "not", "regressed", "not_testable")
LABELS = {"done": "done", "partly": "partly", "not": "not", "regressed": "regressed", "not_testable": "not testable"}
LIMIT = 12


def list_path(p, n, rid):
    return p.rdir(n, "briefs", rid + "-regrade.json")


def key(journey, text):
    return (str(journey), " ".join(str(text).lower().split()))


def build_list(p, prev, rid):
    """Last round's fixes for this reviewer: the round's do-next list, then its own, de-duplicated by text."""
    items, seen = [], set()
    own = []
    for j in (p.verdicts(prev).get(rid) or {}).get("journeys", []):
        for f in (j.get("fixes") or []):
            if isinstance(f, dict):
                own.append({"journey": j.get("id"), "where": f.get("where", ""), "fix": f.get("fix", "")})
    shared = [{"journey": it["journey"], "where": it["where"], "fix": it["fix"]} for it in readiness.do_next(p, prev)]
    for it in shared + own:
        text = " ".join(str(it["fix"]).split())
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        items.append({"id": "f%d" % (len(items) + 1), "journey": it["journey"], "where": it["where"], "fix": text})
        if len(items) >= LIMIT:
            break
    return items


def write_list(p, n, rid, prev):
    items = build_list(p, prev, rid)
    with open(list_path(p, n, rid), "w", encoding="utf-8") as fh:
        json.dump({"from_round": prev, "fixes": items}, fh, indent=2, ensure_ascii=False)
    return items


def load_list(p, n, rid):
    try:
        with open(list_path(p, n, rid), encoding="utf-8") as fh:
            return json.load(fh).get("fixes") or []
    except (OSError, ValueError, AttributeError):
        return []


def brief_lines(items):
    if not items:
        return []
    lines = ["## Last round's proposed fixes: re-grade each one", "",
             "For every fix below, say whether it was made, using the exact words or state you see on screen as proof.",
             "States: `done`, `partly`, `not`, `regressed` (made it worse) or `not_testable` (you could not reach it).", ""]
    for it in items:
        lines.append("%s. (journey %s, %s) %s" % (it["id"], it["journey"], it["where"] or "the product", it["fix"]))
    return lines + [""]


def check_reply(p, n, rid, reply):
    """Problems with the regrade part of a comparison reply, as plain sentences."""
    items = load_list(p, n, rid)
    if not items:
        return []
    got = reply.get("regrade")
    if not isinstance(got, list):
        return ["regrade must be a list answering every fix: %s." % ", ".join(i["id"] for i in items)]
    probs, answered = [], set()
    for a in got:
        if not isinstance(a, dict):
            probs.append("each regrade answer must be an object with id, state and seen.")
            continue
        if a.get("state") not in STATES:
            probs.append("regrade %s: state must be one of %s." % (a.get("id"), ", ".join(STATES)))
        elif not str(a.get("seen") or "").strip():
            probs.append("regrade %s: seen must quote the words or state on screen." % a.get("id"))
        else:
            answered.add(a.get("id"))
    missing = [i["id"] for i in items if i["id"] not in answered]
    if missing and not probs:
        probs.append("regrade is missing an answer for: %s." % ", ".join(missing))
    elif missing:
        probs.append("not answered with a valid state and seen text: %s." % ", ".join(missing))
    return probs


def load_round(p, n):
    """{"rows": [{fix, journey, answers: {rid: {state, seen}}}], "counts": {state: n}} for the report, or None."""
    rows, order = {}, []
    for rid, c in p.comparisons(n).items():
        by_id = dict((a.get("id"), a) for a in (c.get("regrade") or []) if isinstance(a, dict))
        for it in load_list(p, n, rid):
            a = by_id.get(it["id"])
            if not a:
                continue
            k = key(it["journey"], it["fix"])
            if k not in rows:
                rows[k] = {"fix": it["fix"], "journey": it["journey"], "answers": {}}
                order.append(k)
            rows[k]["answers"][rid] = {"state": a.get("state"), "seen": a.get("seen", "")}
    if not rows:
        return None
    counts = {}
    for r in rows.values():
        for a in r["answers"].values():
            counts[a["state"]] = counts.get(a["state"], 0) + 1
    return {"rows": [rows[k] for k in order], "counts": counts}


def table_html(data, info):
    if not data:
        return ""
    esc = lambda s: html.escape("" if s is None else str(s))  # noqa: E731
    who = sorted(set(w for r in data["rows"] for w in r["answers"]))
    counts = ", ".join("%d %s" % (data["counts"][s], LABELS[s]) for s in STATES if data["counts"].get(s))
    head = "".join("<th>%s</th>" % esc(info.get(w, {}).get("name", w)) for w in who)
    body = []
    for r in data["rows"]:
        cells = ""
        for w in who:
            a = r["answers"].get(w)
            cells += ("<td><b>%s</b><br><span class='small sub'>%s</span></td>" % (
                esc(LABELS.get(a["state"], a["state"])), esc(a["seen"]))) if a else "<td class='sub'>not asked</td>"
        body.append("<tr><td>%s <span class='small sub'>(journey %s)</span></td>%s</tr>" % (esc(r["fix"]), esc(r["journey"]), cells))
    return ("<h4>Last round's fixes, re-graded (%s)</h4><table><tr><th>Fix</th>%s</tr>%s</table>" % (esc(counts), head, "".join(body)))
