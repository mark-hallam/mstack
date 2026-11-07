"""shots: capture every item of a round at desktop and phone, light and dark, with the sibling skill's journey driver."""
import functools
import http.server
import os
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from direction_common import SCHEMES, Project, fail, say


def serve(folder):
    """A static server on 127.0.0.1 in a background thread (no computer-name lookup, which can hang)."""
    class Server(http.server.ThreadingHTTPServer):
        def server_bind(self):
            import socketserver
            socketserver.TCPServer.server_bind(self)
            self.server_name, self.server_port = "127.0.0.1", self.server_address[1]
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=folder)
    httpd = Server(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def cmd_shots(args):
    p = Project(args.dir)
    r = p.need_round(args.round)
    items = p.built(r)
    if not items:
        fail("Round %d has no files yet. Run options (or narrow), or write the files, first." % r["n"])
    try:
        from eval_common import tmp_base
        from serving import find_chrome
        from target import drive
    except ImportError:
        fail("shots needs the multi-evaluator skill next to this one (it holds the journey driver).")
    if not shutil.which("node") or not find_chrome():
        fail("skipped: no Chrome. shots needs Node.js 18 or later and Google Chrome or Chromium (set MSTACK_CHROME).")
    out = p.rdir(r["n"], "shots")
    os.makedirs(out, exist_ok=True)
    httpd = serve(p.rdir(r["n"], "options"))
    base = "http://127.0.0.1:%d/" % httpd.server_address[1]

    def once(item, vname, scheme, name):
        work = tempfile.mkdtemp(prefix="mstack-direction-shot-", dir=tmp_base())
        try:
            vp = p.viewports()[vname]
            spec = {"viewport": vp, "scheme": scheme, "thumb": 640 if vp["w"] > 600 else 300,
                    "steps": [{"do": "goto", "url": base + item + ".html"}, {"do": "wait", "ms": 300}]}
            run = drive(spec, work)
            pngs = sorted(f for f in os.listdir(run) if f.endswith(".png"))
            shutil.copyfile(os.path.join(run, pngs[-1]), os.path.join(out, name + ".png"))
            if os.path.exists(os.path.join(run, "final.jpg")):
                shutil.copyfile(os.path.join(run, "final.jpg"), os.path.join(out, name + ".jpg"))
            shutil.copyfile(os.path.join(run, "log.txt"), os.path.join(out, name + ".txt"))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def one(job):
        item, vname, scheme = job
        name = "%s-%s-%s" % (item, vname, scheme)
        problem = None
        for _ in range(2):                  # a busy computer can make one Chrome start fail: try once more
            try:
                once(item, vname, scheme, name)
                return name, None
            except (SystemExit, Exception) as e:
                problem = str(e)
        return name, problem

    jobs = [(i, v, s) for i in items for v in p.viewports() for s in SCHEMES]
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(one, jobs))
    finally:
        httpd.shutdown()
    bad = [{"shot": n, "problem": e} for n, e in results if e]
    say(args, {"round": r["n"], "shots": out, "captured": len(results) - len(bad), "failed": bad},
        "captured %d of %d screenshots in %s\n%s\nNext: fill rounds/r%d/compare.json, then run compare." % (
            len(results) - len(bad), len(results), out, "\n".join("FAILED %s: %s" % (b["shot"], b["problem"]) for b in bad), r["n"]))
    if bad:
        raise SystemExit(1)
