#!/usr/bin/env python3
"""The design-direction skill, start to finish, with a stand-in builder: no AI and no network.

Covers init, the brief check, options, shots (skipped without Chrome), compare (and its refusal), pick,
narrow (the builder must be given the "look is decided" paragraph), lock (tokens, contrast warning),
status at every stage, and the hand over to multi-evaluator (brand rules in its scoring brief).

  python3 tests/test_direction.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRECTION = os.path.join(ROOT, "skills", "design-direction", "scripts", "direction.py")
EVAL_LOOP = os.path.join(ROOT, "skills", "multi-evaluator", "scripts", "eval_loop.py")
STAND_IN = os.path.join(ROOT, "tests", "stand_in_builder.py")
sys.path.insert(0, os.path.join(ROOT, "skills", "multi-evaluator", "scripts"))
from eval_common import tmp_base  # noqa: E402
from serving import find_chrome  # noqa: E402

failures = []


def check(ok, what):
    print("%s  %s" % ("pass" if ok else "FAIL", what), flush=True)
    if not ok:
        failures.append(what)


def run(script, *args, **kw):
    r = subprocess.run([sys.executable, script] + [str(a) for a in args], capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout, r.stderr


def direction(folder, *args):
    return run(DIRECTION, *(list(args) + ["--dir", folder]))


def status(folder):
    rc, out, err = direction(folder, "status", "--json")
    return json.loads(out) if rc == 0 else {"next": "status failed: " + err}


def edit_json(path, fn):
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    fn(doc)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)


def main():
    work = tempfile.mkdtemp(prefix="mstack-direction-", dir=tmp_base())
    d = os.path.join(work, "look")
    cfg = os.path.join(d, "direction.json")
    try:
        # init
        rc, out, err = direction(d, "init", "--name", "Sample Product", "--taste", "Apple-clean, calm, light first")
        check(rc == 0 and os.path.exists(cfg) and os.path.exists(os.path.join(d, "BRIEF.md")), "init writes direction.json and BRIEF.md")
        brief = open(os.path.join(d, "BRIEF.md"), encoding="utf-8").read()
        for heading in ("What this is and who it is for", "What every option must contain", "Hard rules", "The person's taste", "Decision rule"):
            check(("## " + heading) in brief, "the brief has the section: " + heading)
        check("prefers-reduced-motion" in brief and "390 pixels" in brief and "4.5 to 1" in brief, "the brief carries the hard rules")
        check("Sample Product" in brief and "Apple-clean, calm, light first" in brief, "init fills the name and the taste")
        check("Sample Product" in open(cfg, encoding="utf-8").read(), "direction.json holds the name")
        check("BRIEF.md" in status(d)["next"], "status before the brief is written says to write the brief")
        rc, out, err = direction(d, "options", "--n", 2)
        check(rc != 0 and "BRIEF.md" in (out + err), "options refuses while the brief still has placeholders")
        filled = re.sub(r"\[\[.*?\]\]", "Filled in for the test.", brief, flags=re.S)
        open(os.path.join(d, "BRIEF.md"), "w", encoding="utf-8").write(filled)
        edit_json(cfg, lambda c: c.update(builders=[{"id": "standin", "name": "Stand-in", "maker": "test", "kind": "command", "command": [
            sys.executable, STAND_IN, "--out", "{out}", "--letter", "{letter}", "--work", "{work}"]}]))
        check("options" in status(d)["next"], "status with a filled brief says to run options")
        rc, out, err = direction(d, "options", "--n", 5)
        check(rc != 0, "options refuses more than four directions")

        # options
        rc, out, err = direction(d, "options", "--n", 2, "--json")
        files = [os.path.join(d, "rounds", "r1", "options", "option-%s.html" % x) for x in "ab"]
        check(rc == 0 and all(os.path.exists(f) for f in files), "options builds both option files (%s)" % (err.strip()[-200:]))
        check(all(open(f, encoding="utf-8").read().lstrip().startswith("<!--") for f in files), "each option starts with its design-language comment")
        seen = open(os.path.join(d, "rounds", "r1", "work", "option-a", "brief-seen.md"), encoding="utf-8").read()
        check("What every option must contain" in seen and "option-a.html" in seen, "the builder is given the brief and its output path")
        check("shots" in status(d)["next"], "status after options says to capture shots")

        # shots
        have_chrome = bool(find_chrome() and shutil.which("node"))
        if have_chrome:
            rc, out, err = direction(d, "shots")
            names = ["option-%s-%s-%s" % (x, v, s) for x in "ab" for v in ("desktop", "phone") for s in ("light", "dark")]
            shots = os.path.join(d, "rounds", "r1", "shots")
            check(rc == 0 and all(os.path.exists(os.path.join(shots, n + ".png")) and os.path.exists(os.path.join(shots, n + ".txt")) for n in names),
                  "shots captures every option at desktop and phone, light and dark, with the visible text (%s)" % (out + err).strip()[-300:])
        else:
            print("skipped: no Chrome (shots)")

        # compare
        rc, out, err = direction(d, "compare")
        page = os.path.join(d, "rounds", "r1", "index.html")
        html = open(page, encoding="utf-8").read() if os.path.exists(page) else ""
        check(rc != 0 and "recommendation.base" in (out + err), "compare refuses to call the round complete without recommendation.base")
        check("option-a" in html and "option-b" in html and "a stand-in for item A" in html.replace("Design language: ", ""), "the compare page names both options with their design-language paragraph")
        check("prefers-color-scheme" in html and "http://" not in html and "https://" not in html, "the compare page is self-contained with a dark mode")
        check("compare" in status(d)["next"], "status says to fill compare.json")
        cpath = os.path.join(d, "rounds", "r1", "compare.json")

        def fill_compare(c):
            c["items"]["option-a"]["strengths"] = ["Calm and clear"]
            c["recommendation"].update(base="option-b", borrow="The spacing of option a", cost="One more round", first_principles="Which feel do you want first?")
        edit_json(cpath, fill_compare)
        rc, out, err = direction(d, "compare")
        html = open(page, encoding="utf-8").read()
        check(rc == 0 and "Calm and clear" in html and "The spacing of option a" in html, "compare rebuilds the page from compare.json and completes")
        check("pick" in status(d)["next"], "status asks the person to pick")

        # pick, narrow
        rc, out, err = direction(d, "pick", "--option", "a")
        doc = json.load(open(cfg, encoding="utf-8"))
        check(rc == 0 and doc["picked"]["id"] == "option-a" and doc["picked"]["round"] == 1, "pick records the option and its round")
        check("narrow" in status(d)["next"], "status after a pick says to narrow")
        rc, out, err = direction(d, "narrow", "--n", 4)
        check(rc != 0, "narrow refuses more than three variants")
        rc, out, err = direction(d, "narrow", "--n", 2)
        v1 = os.path.join(d, "rounds", "r2", "options", "variant-1.html")
        check(rc == 0 and os.path.exists(v1) and os.path.exists(v1.replace("variant-1", "variant-2")), "narrow builds the variants")
        seen = open(os.path.join(d, "rounds", "r2", "work", "variant-1", "brief-seen.md"), encoding="utf-8").read()
        check("The look is decided: option a in round 1" in seen and "option-a.html" in seen and "Vary only structure" in seen,
              "the builder is given the look-is-decided paragraph")
        check("What every option must contain" in seen, "the narrow brief still holds the original brief")
        if have_chrome:
            rc, out, err = direction(d, "shots")
            check(rc == 0 and os.path.exists(os.path.join(d, "rounds", "r2", "shots", "variant-1-phone-dark.png")), "shots works for variants")
        rc, out, err = direction(d, "compare")
        check(rc != 0 and "questions" in (out + err), "a narrow round is not complete without numbered questions")
        edit_json(os.path.join(d, "rounds", "r2", "compare.json"), lambda c: c.update(questions=[
            {"question": "Sidebar or top bar?", "variants": {"1": "Sidebar", "2": "Top bar"}},
            {"question": "Dense or roomy?", "variants": {"1": "Roomy", "2": "Dense"}}]))
        rc, out, err = direction(d, "compare")
        html = open(os.path.join(d, "rounds", "r2", "index.html"), encoding="utf-8").read()
        check(rc == 0 and "Sidebar or top bar?" in html, "a narrow compare page shows the questions")
        rc, out, err = direction(d, "pick", "--variant", 1)
        doc = json.load(open(cfg, encoding="utf-8"))
        check(rc == 0 and doc["picked"]["id"] == "variant-1" and doc["picked"]["round"] == 2, "pick --variant records the variant")
        check("lock" in status(d)["next"], "status after a variant pick says to lock")

        # lock
        edit_json(cfg, lambda c: c.update(pairs=[
            {"name": "text on bg", "fg": "--text", "bg": "--bg"}, {"name": "muted on bg", "fg": "--muted", "bg": "--bg"},
            {"name": "accent-ink on accent", "fg": "--accent-ink", "bg": "--accent"},
            {"name": "faint on bg", "fg": "--faint", "bg": "--bg"}]))
        rc, out, err = direction(d, "lock", "--json")
        brand_path = os.path.join(d, "brand.json")
        brand = json.load(open(brand_path, encoding="utf-8")) if os.path.exists(brand_path) else {}
        tokens = brand.get("tokens", {})
        check(rc == 0 and brand.get("name") == "Sample Product" and brand.get("source", "").endswith("variant-1.html"), "lock writes brand.json naming the picked file")
        check(tokens.get("light", {}).get("--bg") == "#ffffff" and tokens.get("dark", {}).get("--bg") == "#1c1c1e", "brand.json has the light tokens and the dark override (both forms)")
        check(tokens.get("dark", {}).get("--accent-ink") == "#000000" and tokens.get("light", {}).get("--radius") == "12px", "brand.json keeps every custom property")
        check(brand.get("fonts") and "-apple-system" in brand["fonts"][0], "brand.json has the font stack")
        check(any("Variants change structure only; the look is locked" == r for r in brand.get("rules", [])) and len(brand.get("rules", [])) > 5,
              "brand.json has the brief's hard rules plus the lock rule")
        check("faint on bg" in (out + err) and "4.5" in (out + err), "lock warns about a pair below 4.5 to 1")
        check("text on bg" not in json.dumps(json.loads(out).get("warnings", [])), "lock does not warn about pairs that pass")
        check(json.load(open(cfg, encoding="utf-8"))["locked"] is True, "lock sets locked")
        check("multi-evaluator" in status(d)["next"], "status after lock hands over to multi-evaluator")
        rc, out, err = direction(d, "options", "--n", 2)
        check(rc != 0 and "relook" in (out + err), "options is refused once a look is locked, unless the person asks for a relook")

        # hand over to multi-evaluator
        review = os.path.join(work, "review")
        run(EVAL_LOOP, "init", "--dir", review, "--name", "Sample Product")
        edit_json(os.path.join(review, "mstack-eval.json"), lambda c: c.update(brand=brand_path))
        run(EVAL_LOOP, "start-round", "--dir", review)
        rnd = os.path.join(review, "rounds", "r1")
        os.makedirs(os.path.join(rnd, "shots"), exist_ok=True)
        open(os.path.join(rnd, "shots", "x.png"), "wb").write(b"\x89PNG\r\n\x1a\n")
        rc, out, err = run(EVAL_LOOP, "brief", "--dir", review)
        text = open(os.path.join(rnd, "briefs", "claude.md"), encoding="utf-8").read() if rc == 0 else ""
        check("Rules your fixes must respect (not scored)" in text and "Variants change structure only; the look is locked" in text,
              "multi-evaluator's scoring brief lists the brand rules as not scored (%s)" % err.strip()[-200:])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not failures else "%d checks failed" % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
