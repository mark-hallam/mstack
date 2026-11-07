"""The measured audit: read the per-view numbers that capture saves, and line them up across rounds.

capture saves rounds/r<N>/shots/<view id>.audit.json for every view (see audit.mjs for what is measured).
Standard library only.
"""
import json
import os

# (key, label shown in the report)
MEASURES = [
    ("screens", "Screens long"),
    ("words", "Words of visible text"),
    ("repeats", "Phrases repeated 3 or more times"),
    ("contrast", "Text failing contrast (4.5 to 1, or 3 to 1 for large text)"),
    ("images_without_alt", "Images without alt text"),
    ("sideways_scroll", "Sideways scroll"),
    ("motion", "Endless animations (as is / with reduce motion)"),
    ("weight_kb", "Page weight (KB)"),
    ("heading_skips", "Heading levels skipped"),
]


def round_audit(p, n):
    """{view id: audit dict} for round n. A view with no audit (older round, or the audit failed) is left out."""
    sdir = p.rdir(n, "shots")
    out = {}
    if not os.path.isdir(sdir):
        return out
    for f in sorted(os.listdir(sdir)):
        if not f.endswith(".audit.json"):
            continue
        try:
            with open(os.path.join(sdir, f), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out[f[:-len(".audit.json")]] = data
    return out


def read_run(run):
    """The audit.json the driver wrote in a capture run folder, or None if it is missing or incomplete."""
    try:
        with open(os.path.join(run, "audit.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "screens" in data and "motion" in data else None


def value(a, key):
    """One measure as a plain value for a table cell: a number, a word or a short string."""
    if not a or key not in a:
        return None
    v = a[key]
    if key in ("repeats", "contrast"):
        return len(v)
    if key == "images_without_alt":
        return v.get("count")
    if key == "sideways_scroll":
        return "yes" if v else "no"
    if key == "motion":
        return "%s / %s" % (v.get("always"), v.get("reduced"))
    return v


def audit_rows(p, rounds):
    """{view id: {measure key: [value for each round in `rounds`, None where that round has none]}}"""
    per_round = [round_audit(p, n) for n in rounds]
    views = []
    for r in per_round:
        views += [v for v in r if v not in views]
    return {v: {key: [value(r.get(v), key) for r in per_round] for key, _ in MEASURES} for v in views}
