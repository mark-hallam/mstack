"""The "Measured" section of the report: the numbers capture took from each view, round by round."""
import html

import audit


def esc(s):
    return html.escape("" if s is None else str(s))


def measured(p, rs):
    """One table per view group: a row per measure, a column per round, the latest marked."""
    rounds = [r["n"] for r in rs]
    rows = audit.audit_rows(p, rounds)
    if not rows:
        return ""
    latest = audit.round_audit(p, rounds[-1])
    groups = {}
    for v in rs[-1]["views"]:
        if v["id"] in rows:
            groups.setdefault(v.get("group", "Screens"), []).append(v)
    head = "".join("<th scope='col'%s>Round %d%s</th>" % (
        " style='font-weight:700'" if n == rounds[-1] else "", n, " (latest)" if n == rounds[-1] else "") for n in rounds)
    out = []
    for g, vs in groups.items():
        body = []
        for v in vs:
            for key, label in audit.MEASURES:
                cells = []
                for i, val in enumerate(rows[v["id"]][key]):
                    mark = " style='font-weight:700'" if rounds[i] == rounds[-1] else ""
                    cells.append("<td%s>%s</td>" % (mark, esc(val) if val is not None else "&ndash;"))
                body.append("<tr><th scope='row'>%s%s</th>%s</tr>" % (
                    esc(v["name"] + ": ") if len(vs) > 1 else "", esc(label), "".join(cells)))
        fails = ""
        for v in vs:
            pairs = (latest.get(v["id"]) or {}).get("contrast") or []
            if pairs:
                items = "".join("<li>%s: <code>%s</code> on <code>%s</code>, %s to 1, %s px (<code>%s</code>)</li>" % (
                    esc(c.get("text")), esc(c.get("fg")), esc(c.get("bg")), esc(c.get("ratio")), esc(c.get("size")),
                    esc(c.get("selector"))) for c in pairs)
                fails += ("<details><summary>%s: %d text pair%s failing contrast in round %d</summary><ul>%s</ul></details>" % (
                    esc(v["name"]), len(pairs), "" if len(pairs) == 1 else "s", rounds[-1], items))
        out.append("<h3 class='grp'>%s</h3><div class='card'><table><thead><tr><th scope='col'>Measure</th>%s</tr></thead>"
                   "<tbody>%s</tbody></table>%s</div>" % (esc(g), head, "".join(body), fails))
    return ("<h2>Measured</h2><p class='small sub'>Numbers taken from the live page by the same script every round, "
            "so progress is a fact beside the reviewers' opinions. A dash means that round has no measurement.</p>%s"
            % "".join(out))
