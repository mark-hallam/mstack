"""lock: read the picked file's colour tokens, fonts and radii into brand.json and check contrast."""
import json
import os
import re

from direction_common import Project, fail, read, say, write


def blocks(css):
    """Top level (selector, body) pairs of some CSS, brace aware."""
    i, n = 0, len(css)
    while True:
        j = css.find("{", i)
        if j < 0:
            return
        depth, k = 1, j + 1
        while k < n and depth:
            depth += (css[k] == "{") - (css[k] == "}")
            k += 1
        yield css[i:j].split(";")[-1].strip(), css[j + 1:k - 1]
        i = k


def props(body):
    return dict((m.group(1), " ".join(m.group(2).split())) for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;{}]+)", body))


def walk(css, light, dark, fonts, media=None):
    for sel, body in blocks(css):
        if sel.startswith("@media"):
            m = "dark" if re.search(r"prefers-color-scheme\s*:\s*dark", sel) else "other"
            walk(body, light, dark, fonts, m)
        elif sel.startswith("@"):
            continue
        else:
            for s in [x.strip() for x in sel.split(",")]:
                themed_dark = re.search(r"data-theme\s*=\s*[\"']?dark", s)
                root = s.startswith((":root", "html", "[data-theme"))
                if root and (themed_dark or media == "dark"):
                    dark.update(props(body))
                elif s in (":root", "html") and media is None:
                    light.update(props(body))
                if s in ("body", "html", ":root") and media is None:
                    for f in re.findall(r"font-family\s*:\s*([^;{}]+)", body):
                        fonts.append(" ".join(f.split()))


def parse_tokens(html):
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    light, dark, fonts = {}, {}, []
    walk(css, light, dark, fonts)
    fonts += [v for k, v in list(light.items()) if "font" in k]
    fonts = [re.sub(r"var\((--[\w-]+)\)", lambda m: light.get(m.group(1), m.group(0)), f) for f in fonts]
    return light, dark, list(dict.fromkeys(fonts))


def resolve(value, toks, depth=0):
    value = (value or "").strip()
    m = re.fullmatch(r"var\((--[\w-]+)\s*(?:,\s*(.+))?\)", value)
    if m and depth < 6:
        return resolve(toks.get(m.group(1)) or m.group(2), toks, depth + 1)
    return value


def to_rgb(value):
    m = re.fullmatch(r"#([0-9a-f]{3,8})", value.lower())
    if m:
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) in (3, 4) else h
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) in (6, 8) else None
    m = re.fullmatch(r"rgba?\(([^)]*)\)", value.lower())
    if m:
        nums = re.findall(r"[\d.]+%?", m.group(1))[:3]
        return tuple(round(float(x[:-1]) * 2.55) if x.endswith("%") else float(x) for x in nums) if len(nums) == 3 else None
    m = re.fullmatch(r"hsla?\(\s*([\d.]+)(?:deg)?[ ,]+([\d.]+)%[ ,]+([\d.]+)%.*\)", value.lower())
    if m:
        h, s, l = float(m.group(1)) / 360, float(m.group(2)) / 100, float(m.group(3)) / 100
        q = l * (1 + s) if l < .5 else l + s - l * s
        pq = 2 * l - q

        def hue(t):
            t %= 1
            return pq + (q - pq) * 6 * t if t < 1 / 6 else q if t < .5 else pq + (q - pq) * (2 / 3 - t) * 6 if t < 2 / 3 else pq
        return tuple(round(255 * hue(h + d)) for d in (1 / 3, 0, -1 / 3))
    return None


def luminance(rgb):
    c = [(x / 255) / 12.92 if x / 255 <= .03928 else ((x / 255 + .055) / 1.055) ** 2.4 for x in rgb]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]


def ratio(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + .05) / (lb + .05)


def check_pairs(pairs, light, dark):
    warnings, skipped, results = [], [], []
    for scheme, toks in (("light", light), ("dark", dict(light, **dark))):
        for pr in pairs:
            fg, bg = to_rgb(resolve(toks.get(pr["fg"]), toks)), to_rgb(resolve(toks.get(pr["bg"]), toks))
            if not fg or not bg:
                skipped.append("%s (%s): %s or %s is missing or not a colour this tool can read" % (pr["name"], scheme, pr["fg"], pr["bg"]))
                continue
            r = round(ratio(fg, bg), 2)
            results.append({"pair": pr["name"], "scheme": scheme, "ratio": r})
            if r < 4.5:
                warnings.append("%s (%s) is %.1f to 1, below 4.5 to 1" % (pr["name"], scheme, r))
    return results, warnings, skipped


def hard_rules(brief):
    m = re.search(r"^## Hard rules\s*\n(.*?)(?=^## |\Z)", brief, re.S | re.M)
    return [" ".join(l[2:].replace("**", "").split()) for l in (m.group(1).splitlines() if m else []) if l.startswith("- ")]


def cmd_lock(args):
    p = Project(args.dir)
    pick = p.cfg.get("picked")
    if not pick:
        fail("Nothing is picked yet. Run pick --option <letter> (or --variant <n>) first.")
    src = os.path.join(p.dir, pick["file"])
    if not os.path.exists(src):
        fail("The picked file %s is missing." % src)
    light, dark, fonts = parse_tokens(read(src))
    if not light:
        fail("%s has no custom properties on :root, so there is nothing to lock. Ask the builder for colour tokens on :root." % pick["file"])
    radii = dict((k, v) for k, v in light.items() if re.search(r"radius|^--r(-|\d|$)", k))
    results, warnings, skipped = check_pairs(p.cfg.get("pairs") or [], light, dark)
    brand = {"name": p.name, "source": src, "tokens": {"light": light, "dark": dark}, "fonts": fonts, "radii": radii,
             "rules": hard_rules(p.brief_text()) + ["Variants change structure only; the look is locked"], "contrast": results}
    write(os.path.join(p.dir, "brand.json"), json.dumps(brand, indent=2) + "\n")
    p.cfg["locked"] = True
    p.save()
    text = ["locked: wrote %s from %s (%d light tokens, %d dark)" % (os.path.join(p.dir, "brand.json"), pick["file"], len(light), len(dark))]
    text += ["warning: " + w for w in warnings] + ["note: " + s for s in skipped]
    text.append("Next: hand over to multi-evaluator: put \"brand\": \"%s\" in its mstack-eval.json. Build the product from the tokens in "
                "brand.json." % os.path.join(p.dir, "brand.json"))
    say(args, {"brand": os.path.join(p.dir, "brand.json"), "warnings": warnings, "skipped": skipped, "locked": True}, "\n".join(text))
