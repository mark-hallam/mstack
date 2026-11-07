"""options and narrow: start a round, run the command builders in parallel, leave the agent builders to the agent."""
import os
import re
import subprocess
import threading

from direction_common import Project, fail, label, read, say, write

NARROW = ("The look is decided: %(label)s in round %(round)d (%(file)s). Every variant must use exactly its colours, "
          "type, radii, shadows and spacing (copy the tokens from that file). Vary only structure: layout, navigation, "
          "wording, density. Never a different visual style.")
ASK = ("Write one whole %(kind)s to %(out)s. Start with the design-language paragraph (an HTML comment naming the design "
       "language, its reference points and its trade-off), then make a real, working page that follows every rule above.")
MAX_OPTIONS, MAX_VARIANTS = 4, 3


def lint(path):
    """Warnings for the hard rules a quick read can catch. Not a substitute for looking at the page."""
    text = read(path)
    out = []
    if not text.lstrip().startswith("<!--"):
        out.append("does not start with the design-language comment")
    for needle, what in (("<meta name=\"viewport\"", "no viewport meta tag"), ("prefers-color-scheme", "no dark mode (prefers-color-scheme)"),
                         (":root", "no colour tokens on :root"), ("prefers-reduced-motion", "no prefers-reduced-motion rule")):
        if needle not in text:
            out.append(what)
    if re.search(r"(src|href)\s*=\s*[\"']?(https?:)?//", text, re.I) or re.search(r"(@import|url\()\s*[\"']?(https?:)?//", text, re.I):
        out.append("loads something from outside the file")
    return ["%s: %s" % (os.path.basename(path), w) for w in out]


def run_builder(p, k, item, builder, text, results):
    work = p.rdir(k, "work", item)
    os.makedirs(work, exist_ok=True)
    out = p.item_file(k, item)
    values = {"brief": p.rdir(k, "brief.md"), "out": out, "letter": item.partition("-")[2], "work": work,
              "options": os.path.dirname(out), "dir": p.dir, "home": os.path.expanduser("~")}
    cmd = builder["command"]
    cmd = [_fill(c, values) for c in cmd] if isinstance(cmd, list) else _fill(cmd, values)
    try:
        proc = subprocess.run(cmd, input=text, capture_output=True, text=True, cwd=work, shell=isinstance(cmd, str),
                              timeout=60 * float(builder.get("timeout_minutes", p.cfg.get("timeout_minutes", 30))))
    except subprocess.TimeoutExpired:
        results[item] = "timed out"
        return
    except OSError as e:
        results[item] = "could not run %s: %s" % (cmd[0] if isinstance(cmd, list) else cmd, e)
        return
    write(os.path.join(work, "builder-output.txt"), (proc.stdout or "") + (proc.stderr or ""))
    if not os.path.exists(out):                     # a builder that prints the page instead of writing it
        low = (proc.stdout or "").lower()
        start = min([i for i in (low.find("<!doctype"), low.find("<html")) if i >= 0] or [-1])
        if start >= 0:
            end = low.rfind("</html>")
            write(out, proc.stdout[start:end + 7 if end >= 0 else None])
    if not os.path.exists(out):
        results[item] = "the builder wrote no file (exit %s). Its output is in %s" % (proc.returncode, os.path.join(work, "builder-output.txt"))


def _fill(value, values):
    for k, v in values.items():
        value = value.replace("{%s}" % k, str(v))
    return value


def start_round(args, mode, count):
    p = Project(args.dir)
    kind = "option" if mode == "options" else "variant"
    top = MAX_OPTIONS if mode == "options" else MAX_VARIANTS
    if count < 1 or count > top:
        fail("Use at most %d %ss per round (you asked for %d). Fewer, whole and working, beats more." % (top, kind, count))
    base = None
    if mode == "options":
        if p.cfg.get("locked") and not getattr(args, "relook", False):
            fail("A look is locked. Directions are drawn only for a new product or a relook: make variants with narrow, "
                 "or run options --relook if the person asks for a different look.")
        if p.cfg.get("locked"):
            p.cfg["locked"] = False
            brand = os.path.join(p.dir, "brand.json")
            if os.path.exists(brand):
                os.replace(brand, os.path.join(p.dir, "brand.previous.json"))
    else:
        base = p.cfg.get("picked")
        if not base:
            fail("Pick an option first (pick --option <letter>): variants are built on the look the person chose.")
    open_items = p.brief_open_items()
    if open_items:
        fail("%s still has %d placeholder(s) in [[double brackets]], for example %s. Fill them in with the person first." % (
            os.path.basename(p.brief_path()), len(open_items), open_items[0][:60]))
    k = args.round or (max([r["n"] for r in p.rounds()] or [0]) + 1)
    r = p.round(k)
    if r and r["mode"] != mode:
        fail("Round %d is a %s round." % (k, r["mode"]))
    ids = ["%s-%s" % (kind, (chr(97 + i) if mode == "options" else str(i + 1))) for i in range(count)]
    if not r:
        r = {"n": k, "mode": mode, "ids": ids, "complete": False}
        p.rounds().append(r)
    else:
        r["ids"] = ids
    text = p.brief_text()
    if base:
        r["base"] = base
        text += "\n\n## The look is decided\n\n" + NARROW % {"label": base["label"], "round": base["round"], "file": os.path.join(p.dir, base["file"])}
    write(p.rdir(k, "brief.md"), text)
    for sub in ("options", "shots", "work"):
        os.makedirs(p.rdir(k, sub), exist_ok=True)
    builders, jobs, waiting = p.builders(), [], []
    for i, item in enumerate(ids):
        if os.path.exists(p.item_file(k, item)) and not args.force:
            continue
        b = builders[i % len(builders)]
        full = text + "\n\n" + ASK % {"kind": kind, "out": p.item_file(k, item)}
        if b.get("kind") == "command":
            jobs.append((item, b, full))
        else:
            waiting.append({"id": item, "builder": b.get("id"), "out": p.item_file(k, item), "brief": p.rdir(k, "brief.md"), "instruction": full})
    results = {}
    threads = [threading.Thread(target=run_builder, args=(p, k, item, b, full, results)) for item, b, full in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    r["complete"] = False
    p.save()
    warnings = [w for item in p.built(r) for w in lint(p.item_file(k, item))]
    data = {"round": k, "mode": mode, "built": p.built(r), "failed": [{"id": i, "problem": m} for i, m in results.items()],
            "waiting": waiting, "warnings": warnings}
    lines = ["round %d (%s): %s built" % (k, mode, ", ".join(data["built"]) or "nothing")]
    lines += ["FAILED %s: %s" % (i, m) for i, m in results.items()]
    lines += ["%s warning: %s" % (kind, w) for w in warnings]
    for w in waiting:
        lines += ["", "%s is yours to write (builder %s). Read %s, then write the file:" % (label(w["id"]), w["builder"], w["brief"]),
                  "  " + ASK % {"kind": kind, "out": w["out"]}]
    lines += ["", "Next: when every file exists, run shots, then compare."]
    say(args, data, "\n".join(lines))
    if results:
        raise SystemExit(1)
