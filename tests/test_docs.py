"""The built-in documentation: the pages, the pictures, and how they are served.

By Aadhil Haq

What is checked here is everything that can go wrong between the sidebar, the page files, the
pictures and the launcher's page: a page in the sidebar with no file, a link pointing at a section
that does not exist, a picture a page shows that was never taken or that the screenshot script no
longer takes, a dash used as punctuation, the guide in the repository saying one command and the
page another, and the routes themselves, which serve the docs without a token and nothing else.

    python3 tests/test_docs.py
"""
import html
import os
import re
import struct
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from hope_labs import docs, docskit, hub  # noqa: E402
import docs_screenshots as shots          # noqa: E402

fails, ran = [], 0


def check(cond, why):
    global ran
    ran += 1
    if not cond:
        fails.append(why)


# --- the pages themselves ---------------------------------------------------
bad = docs.audit()
check(not bad, "the documentation does not audit clean:\n      " + "\n      ".join(bad[:12]))


# --- every picture is a real PNG, wide enough to read, and taken by the script
def png_width(path):
    with open(path, "rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">I", head[16:20])[0]


used = set()
for slug in docs.SITE.order:
    used.update(re.findall(r'src="img/([^"]+)"', docskit.fragment(docs.SITE, slug) or ""))
check(used == set(shots.WANT),
      "the pages show %s but the screenshot script takes %s"
      % (sorted(used - set(shots.WANT)) or "nothing it does not", sorted(set(shots.WANT) - used)
         or "nothing they do not"))
for name in sorted(used):
    full = os.path.join(docs.HERE, "img", name)
    w = png_width(full) if os.path.isfile(full) else None
    check(w is not None, "img/%s is missing or is not a PNG" % name)
    check(w is None or w > 600, "img/%s is only %s px wide" % (name, w))

# --- the guide in the repository and the page say the same commands ---------
md = open(os.path.join(ROOT, "docs", "install-on-grace.md"), encoding="utf-8").read()
pages = "\n".join(docskit.fragment(docs.SITE, slug) or "" for slug in docs.SITE.order)
pre = "\n".join(html.unescape(re.sub(r"<[^>]+>", "", b))
                for b in re.findall(r"<pre>(.*?)</pre>", pages, re.S))
norm = lambda s: re.sub(r"\s+", " ", s).strip()                       # noqa: E731
in_page = {norm(line) for line in pre.splitlines() if line.strip()}
for block in re.findall(r"```(?:bash|json)\n(.*?)```", md, re.S):
    for line in block.splitlines():
        if line.strip() and norm(line) not in in_page:
            check(False, "docs/install-on-grace.md has a line no docs page has: %r" % line)
check(in_page, "the docs pages show no commands at all")


# --- the routes, through the launcher's own handler -------------------------
class NoCluster(hub.Hub):
    """The page logic with nothing behind it: these checks are about serving, not tools."""

    def __init__(self):
        super().__init__(None, user="jdoe", host="grace2")

    def runs(self, refresh=False, limit_each=12):
        return []


def get(path):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


h = NoCluster()
httpd, _url = hub.serve(h, port=0)
base = "http://127.0.0.1:%d" % httpd.server_address[1]
try:
    try:
        urllib.request.build_opener(NoRedirect).open(base + "/docs", timeout=10)
        check(False, "/docs did not redirect")
    except urllib.error.HTTPError as e:
        check(e.code == 302 and e.headers.get("Location") == "/docs/index.html",
              "/docs answered %s to %r" % (e.code, e.headers.get("Location")))
    for slug in docs.SITE.order:
        code, kind, body = get("/docs/%s.html" % slug)
        check(code == 200 and kind.startswith("text/html") and b'class="side"' in body,
              "/docs/%s.html answered %s %s" % (slug, code, kind))
    code, kind, _b = get("/docs/style.css")
    check(code == 200 and kind == "text/css", "/docs/style.css answered %s %s" % (code, kind))
    code, kind, _b = get("/docs/img/tools.png")
    check(code == 200 and kind == "image/png", "a picture answered %s %s" % (code, kind))
    for path in ("/docs/nope.html", "/docs/../hub.py", "/docs/img/../../hub.py", "/docs/pages/index.html"):
        code, _k, _b = get(path)
        check(code == 404, "%s answered %s, not 404" % (path, code))
    code, _k, _b = get("/api/state")
    check(code == 403, "/api/state without the token answered %s" % code)
    code, _k, body = get("/api/state?t=" + h.token)
    check(code == 200 and b'"tools"' in body, "/api/state with the token answered %s" % code)

    # the launcher's page: the bar along the bottom filled in, Docs in the top right of both views
    code, kind, body = get("/")
    text = body.decode("utf-8")
    check(code == 200 and kind.startswith("text/html"), "/ answered %s %s" % (code, kind))
    check("__CREDIT" not in text, "a placeholder for the bar was left in the page")
    check('class="creditbar"' in text and html.escape(docs.COPYRIGHT) in text,
          "the page has no bar along the bottom carrying the copyright")
    check(text.count('class="btn sm docs"') == 2, "Docs is not in the top right of both views")
    check('href="/docs/index.html"' in text and 'href="/docs/results.html"' in text,
          "the page's Docs links do not lead into the docs")
    code, _k, body = get("/tool")
    check(b'href="/docs/windows.html"' in body, "a tool's window has no link to the docs")
finally:
    httpd.shutdown()

# --- the kit is the same file in every repository ----------------------------
# Four interfaces share docskit.py and are kept byte identical; the HOPE pipelines' copy is the
# one changed first. Compared where it is present, skipped where it is not.
SIBLING = "/scratch/group/p.agr250019.000/HOPE-pipelines/hope_monitor/docskit.py"
if os.path.isfile(SIBLING):
    mine = open(os.path.join(ROOT, "hope_labs", "docskit.py"), "rb").read()
    check(mine == open(SIBLING, "rb").read(),
          "hope_labs/docskit.py differs from %s; the four copies are kept identical" % SIBLING)
else:
    print("note  %s is not here, so the copies were not compared" % SIBLING)

if fails:
    print("FAIL %d of %d" % (len(fails), ran))
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ok  %d checks: the docs, their pictures and their routes" % ran)
