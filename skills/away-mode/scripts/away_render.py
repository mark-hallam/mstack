#!/usr/bin/env python3
"""Phone-readable copies of a file or address, for away mode. Used by away.py render; also runs on its own.

Python 3.9 or later, standard library only. Uses headless Google Chrome or Chromium when present (set
MSTACK_CHROME to point at one; MSTACK_CHROME_ARGS adds flags such as --no-sandbox), and falls back to the
macOS tools qlmanage and sips. Says plainly when nothing can render.

  an HTML page      -> a PDF, a phone-width PNG of the first screen (light theme), a full-page PNG if short
  a Markdown file   -> HTML (light theme, system font), then the same as HTML
  an image          -> passed through (HEIC becomes PNG on macOS)
  a PDF             -> passed through, plus a PNG of the first page on macOS
  an http address   -> PNG screenshots, desktop and phone, plus a PDF

  python3 away_render.py <file-or-url> [--out DIR] [--name NAME]
"""
import datetime
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

DEFAULTS = {"phone_width": 390, "phone_height": 844, "desktop_width": 1280, "desktop_height": 800, "scale": 2,
            "full_page_screens": 4}
IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp")


def home(*parts):
    base = os.environ.get("MSTACK_HOME") or os.path.join(os.path.expanduser("~"), ".mstack")
    return os.path.join(base, *parts)


def outbox():
    return home("outbox", datetime.date.today().isoformat())


def tmp_base():
    # Chrome on macOS will not start from the per-user system temp folder, so use /tmp there.
    return os.environ.get("MSTACK_TMP") or ("/tmp" if sys.platform == "darwin" else tempfile.gettempdir())


def find_chrome():
    if os.environ.get("MSTACK_CHROME"):
        return os.environ["MSTACK_CHROME"]
    places = {"darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                         "/Applications/Chromium.app/Contents/MacOS/Chromium"],
              "win32": [r"C:\Program Files\Google\Chrome\Application\chrome.exe"]}.get(sys.platform, [])
    for x in places:
        if os.path.exists(x):
            return x
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    return None


def chrome(url, flags, timeout=90):
    """Run headless Chrome once with a throwaway profile. Returns (ok, stdout_text)."""
    bin_ = find_chrome()
    if not bin_:
        return False, ""
    profile = tempfile.mkdtemp(prefix="mstack-away-chrome-", dir=tmp_base())
    cmd = [bin_, "--headless=new", "--user-data-dir=" + profile, "--no-first-run", "--disable-gpu", "--hide-scrollbars",
           "--force-color-profile=srgb", "--virtual-time-budget=4000"] + os.environ.get("MSTACK_CHROME_ARGS", "").split() \
        + flags + [url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode == 0, r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return False, ""
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def file_url(path):
    return "file://" + urllib.parse.quote(os.path.abspath(path))


# ---------------------------------------------------------------- Markdown to HTML (light theme, system font)

CSS = ("body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:17px;"
       "line-height:1.55;color:#1d1d1f;background:#fff;margin:0;padding:20px 18px;max-width:680px}"
       "h1{font-size:28px;margin:.4em 0 .5em}h2{font-size:22px;margin:1.2em 0 .4em}h3{font-size:18px;margin:1em 0 .3em}"
       "code{font-family:Menlo,Consolas,monospace;font-size:.92em;background:#f5f5f7;border-radius:5px;padding:1px 5px}"
       "pre{background:#f5f5f7;border-radius:10px;padding:12px 14px;overflow-x:auto}pre code{background:none;padding:0}"
       "table{border-collapse:collapse;width:100%;font-size:15px}th,td{border-bottom:1px solid #e5e5ea;padding:7px 8px;"
       "text-align:left;vertical-align:top}th{background:#f5f5f7}blockquote{border-left:3px solid #d1d1d6;margin:0;"
       "padding:2px 14px;color:#515154}a{color:#0071e3}img{max-width:100%;height:auto}")


def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", r'<img alt="\1" src="\2">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![*\w])\*([^*]+)\*(?![*\w])", r"<em>\1</em>", text)
    return text


def markdown_to_html(text, title="Report"):
    out, para, list_tag, in_code, table, code = [], [], None, False, [], []

    def flush():
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para)))
            del para[:]

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append("</%s>" % list_tag)
            list_tag = None

    def close_table():
        if table:
            head, body = table[0], table[1:]
            out.append("<table><tr>%s</tr>%s</table>" % (
                "".join("<th>%s</th>" % inline(c) for c in head),
                "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in row) for row in body)))
            del table[:]

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            flush(); close_list(); close_table()
            if in_code:
                out.append("<pre><code>%s</code></pre>" % "\n".join(code))
                del code[:]
            in_code = not in_code
            continue
        if in_code:
            code.append(html.escape(raw))
            continue
        if line.startswith("|") and line.endswith("|"):
            flush(); close_list()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                table.append(cells)
            continue
        close_table()
        m = re.match(r"(#{1,6})\s+(.*)", line)
        if m:
            flush(); close_list()
            out.append("<h%d>%s</h%d>" % (len(m.group(1)), inline(m.group(2)), len(m.group(1))))
            continue
        m = re.match(r"\s*([-*+]|\d+[.)])\s+(.*)", line)
        if m:
            flush()
            tag = "ol" if m.group(1)[0].isdigit() else "ul"
            if list_tag != tag:
                close_list()
                out.append("<%s>" % tag)
                list_tag = tag
            out.append("<li>%s</li>" % inline(m.group(2)))
            continue
        if line.startswith(">"):
            flush(); close_list()
            out.append("<blockquote>%s</blockquote>" % inline(line.lstrip("> ")))
            continue
        if not line.strip():
            flush(); close_list()
            continue
        if list_tag and raw.startswith("  "):
            out[-1] = out[-1][:-5] + " " + inline(line.strip()) + "</li>"
            continue
        close_list()
        para.append(line.strip())
    flush(); close_list(); close_table()
    if in_code:
        out.append("<pre><code>%s</code></pre>" % "\n".join(code))
    body = "\n".join(out)
    m = re.search(r"<h1>(.*?)</h1>", body)
    title = re.sub(r"<[^>]+>", "", m.group(1)) if m else title
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light">'
            "<title>%s</title><style>%s</style></head><body>\n%s\n</body></html>\n" % (html.escape(title), CSS, body))


# ---------------------------------------------------------------- renderers

def add(result, path, what):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        result["files"].append({"path": path, "bytes": os.path.getsize(path), "what": what})
        return True
    return False


def page_height(url, cfg):
    """Content height of a local page at phone width, measured through a wrapper page. None if unknown."""
    work = tempfile.mkdtemp(prefix="mstack-away-measure-", dir=tmp_base())
    wrapper = os.path.join(work, "measure.html")
    with open(wrapper, "w", encoding="utf-8") as fh:
        fh.write('<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0">'
                 '<iframe id="f" src="%s" style="width:%dpx;height:100px;border:0"></iframe><script>'
                 "var f=document.getElementById('f');function done(){try{var d=f.contentDocument;"
                 "var h=Math.max(d.documentElement.scrollHeight,d.body?d.body.scrollHeight:0);"
                 "document.title='MSTACK_HEIGHT='+h}catch(e){document.title='MSTACK_HEIGHT=error'}}"
                 "f.addEventListener('load',function(){setTimeout(done,500)});</script></body></html>"
                 % (html.escape(url, quote=True), cfg["phone_width"]))
    try:
        ok, dom = chrome(file_url(wrapper), ["--allow-file-access-from-files", "--dump-dom",
                                             "--window-size=%d,%d" % (cfg["phone_width"], cfg["phone_height"])])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    m = re.search(r"MSTACK_HEIGHT=(\d+)", dom or "")
    return int(m.group(1)) if m else None


MIN_WINDOW = 600   # headless Chrome will not lay a page out narrower than about 500 css px


def phone_png(url, out, height, cfg):
    """A true phone-width screenshot. Headless Chrome lays out at 500 css px at least, so a 390 px window
    crops the right edge off a wider layout. Instead the page sits in a centred phone-width frame inside a
    wider window, and the frame is cropped out (sips on macOS). False when the crop step is unavailable."""
    if not shutil.which("sips"):
        return False
    work = tempfile.mkdtemp(prefix="mstack-away-phone-", dir=tmp_base())
    try:
        wrapper = os.path.join(work, "phone.html")
        with open(wrapper, "w", encoding="utf-8") as fh:
            fh.write('<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0;background:#fff">'
                     '<iframe src="%s" style="display:block;margin:0 auto;border:0;width:%dpx;height:%dpx"></iframe>'
                     "</body></html>" % (html.escape(url, quote=True), cfg["phone_width"], height))
        wide = os.path.join(work, "wide.png")
        chrome(file_url(wrapper), ["--allow-file-access-from-files", "--screenshot=" + wide,
                                   "--force-device-scale-factor=%s" % cfg["scale"],
                                   "--window-size=%d,%d" % (max(MIN_WINDOW, cfg["phone_width"]), height)])
        if not os.path.exists(wide):
            return False
        s = float(cfg["scale"])
        res = subprocess.run(["sips", "-c", str(int(height * s)), str(int(cfg["phone_width"] * s)), wide, "--out", out],
                             capture_output=True, timeout=60)
        return res.returncode == 0 and os.path.exists(out)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def frameable(url, local):
    """A local file or a page on this computer can be framed; a remote site may refuse to be (frame-ancestors)."""
    return local or re.match(r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?/", url or "") is not None


def shots_and_pdf(url, base, result, cfg, local):
    """PDF, phone PNG (first screen and full page if short), and for addresses a desktop PNG too."""
    scale = "--force-device-scale-factor=%s" % cfg["scale"]
    pdf = base + ".pdf"
    ok, _ = chrome(url, ["--print-to-pdf=" + pdf, "--no-pdf-header-footer"])
    add(result, pdf, "PDF of the page")
    phone = base + "-phone.png"
    if not (frameable(url, local) and phone_png(url, phone, cfg["phone_height"], cfg)):
        chrome(url, ["--screenshot=" + phone, scale, "--window-size=%d,%d" % (cfg["phone_width"], cfg["phone_height"])])
        result["notes"].append("phone screenshot taken without the phone-width frame: Chrome lays the page out at "
                               "about 500 css px, so the right edge may be cut off")
    add(result, phone, "first screen at phone width (%d css px, light theme)" % cfg["phone_width"])
    if local:
        height = page_height(url, cfg)
        if height is None:
            result["notes"].append("could not measure the page height, so no full-page screenshot")
        elif height <= cfg["phone_height"]:
            result["notes"].append("the whole page fits one phone screen")
        elif height <= cfg["phone_height"] * cfg["full_page_screens"]:
            full = base + "-phone-full.png"
            if not phone_png(url, full, height, cfg):
                chrome(url, ["--screenshot=" + full, scale, "--window-size=%d,%d" % (cfg["phone_width"], height)])
            add(result, full, "full page at phone width (%d css px tall)" % height)
        else:
            result["notes"].append("page is %d css px tall (over %d phone screens): the PDF carries the full content" % (
                height, cfg["full_page_screens"]))
    else:
        desktop = base + "-desktop.png"
        chrome(url, ["--screenshot=" + desktop, "--window-size=%d,%d" % (cfg["desktop_width"], cfg["desktop_height"])])
        add(result, desktop, "desktop screenshot (%dx%d)" % (cfg["desktop_width"], cfg["desktop_height"]))


def quicklook_png(src, base, result, what):
    """macOS fallback: a QuickLook thumbnail of the file."""
    if sys.platform != "darwin" or not shutil.which("qlmanage"):
        return False
    work = tempfile.mkdtemp(prefix="mstack-away-ql-", dir=tmp_base())
    try:
        subprocess.run(["qlmanage", "-t", "-s", "1600", "-o", work, src], capture_output=True, timeout=60)
        made = [f for f in os.listdir(work) if f.endswith(".png")]
        if made:
            shutil.move(os.path.join(work, made[0]), base + "-preview.png")
            return add(result, base + "-preview.png", what)
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return False


def render_html(path, base, result, cfg):
    if find_chrome():
        result["renderer"] = "chrome"
        shots_and_pdf(file_url(path), base, result, cfg, local=True)
    if not result["files"]:
        if quicklook_png(path, base, result, "QuickLook preview of the page (no Chrome found)"):
            result["renderer"] = "qlmanage"
        else:
            result["notes"].append("nothing here can render HTML: install Google Chrome or Chromium (or set MSTACK_CHROME)")


def render_markdown(path, base, result, cfg):
    with open(path, encoding="utf-8", errors="replace") as fh:
        page = markdown_to_html(fh.read(), title=os.path.splitext(os.path.basename(path))[0])
    with open(base + ".html", "w", encoding="utf-8") as fh:
        fh.write(page)
    add(result, base + ".html", "HTML of the Markdown (light theme, system font)")
    before = len(result["files"])
    render_html(base + ".html", base, result, cfg)
    if len(result["files"]) == before and sys.platform == "darwin" and shutil.which("cupsfilter"):
        with open(base + ".pdf", "wb") as fh:
            subprocess.run(["cupsfilter", path], stdout=fh, stderr=subprocess.DEVNULL, timeout=60)
        if add(result, base + ".pdf", "plain-text PDF of the Markdown (no Chrome found)"):
            result["renderer"] = "cupsfilter"


def render_image(path, base, result):
    ext = os.path.splitext(path)[1].lower()
    result["renderer"] = "copy"
    if ext in (".heic", ".heif", ".tif", ".tiff", ".bmp") and sys.platform == "darwin" and shutil.which("sips"):
        subprocess.run(["sips", "-s", "format", "png", path, "--out", base + ".png"], capture_output=True, timeout=60)
        if add(result, base + ".png", "image converted to PNG"):
            return
    shutil.copyfile(path, base + ext)
    add(result, base + ext, "the image, passed through")


def render_pdf(path, base, result):
    result["renderer"] = "copy"
    shutil.copyfile(path, base + ".pdf")
    add(result, base + ".pdf", "the PDF, passed through")
    quicklook_png(path, base, result, "first page as PNG")


def render(target, out_dir=None, cfg=None, name=None):
    cfg = dict(DEFAULTS, **(cfg or {}))
    out_dir = out_dir or outbox()
    os.makedirs(out_dir, exist_ok=True)
    result = {"input": target, "kind": None, "outbox": out_dir, "renderer": None, "files": [], "notes": []}
    is_url = re.match(r"https?://", target, re.I) is not None
    if is_url:
        result["kind"] = "web"
        safe = re.sub(r"[^A-Za-z0-9]+", "-", urllib.parse.urlparse(target).netloc + urllib.parse.urlparse(target).path).strip("-")
        base = os.path.join(out_dir, name or safe or "page")
        if find_chrome():
            result["renderer"] = "chrome"
            shots_and_pdf(target, base, result, cfg, local=False)
        else:
            result["notes"].append("no Chrome or Chromium found, so the address could not be captured")
    else:
        path = os.path.abspath(os.path.expanduser(target))
        if not os.path.isfile(path):
            result["notes"].append("no such file: %s" % path)
            return result
        stem, ext = os.path.splitext(os.path.basename(path))
        ext = ext.lower()
        base = os.path.join(out_dir, name or stem)
        if ext in (".html", ".htm"):
            result["kind"] = "html"
            render_html(path, base, result, cfg)
        elif ext in (".md", ".markdown", ".txt"):
            result["kind"] = "markdown"
            render_markdown(path, base, result, cfg)
        elif ext in IMAGES:
            result["kind"] = "image"
            render_image(path, base, result)
        elif ext == ".pdf":
            result["kind"] = "pdf"
            render_pdf(path, base, result)
        else:
            result["kind"] = "other"
            result["notes"].append("no renderer for %s files: send the file itself, or describe its content in the reply" % ext)
    if not result["files"] and not result["notes"]:
        result["notes"].append("nothing could be rendered")
    return result


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target")
    ap.add_argument("--out")
    ap.add_argument("--name")
    args = ap.parse_args(argv)
    result = render(args.target, out_dir=args.out, name=args.name)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["files"] else 1)


if __name__ == "__main__":
    main()
