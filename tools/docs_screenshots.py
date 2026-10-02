#!/usr/bin/env python3
"""Screenshots for the documentation, taken of the running page.

By Aadhil Haq

    python tools/docs_screenshots.py [--browser CHROME] [--out DIR]

Serves the launcher's own page from this checkout, through its own handler, with a hub that
answers from this machine instead of over SSH: the catalogue is the real one, two tools are shown
running, and the run folders are examples. No tool is started: a tool's tab goes on to the tool's
own page, which is the tool's to document. Then it drives the page the way a person would and saves
each view the docs show. Run it again after the page changes, so the pictures never describe an
older page.

Each view is taken inside its own step: one that fails is reported by name at the end, with the
others still taken. Needs Playwright in the Python running this script, with its own Chromium or
a Chrome named by --browser. Run it on a compute node: it starts a browser.
"""
import argparse
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from hope_labs import hub as hubmod          # noqa: E402
from hope_labs import tools as catalogue     # noqa: E402

IMG = os.path.join(HERE, "hope_labs", "web", "docs", "img")

#: Every picture the pages use. Reported as missing when a step did not produce it, so the docs
#: and this script cannot drift apart silently.
WANT = ["tools.png", "tools-parts.png", "tool-block.png", "results.png", "handoff.png",
        "starting.png"]

#: The parts the Overview's legend names, in reading order. The numbers are drawn onto the
#: picture here rather than described in the text, so the legend and the screenshot cannot
#: come apart.
PARTS = [
    (".brand", 1), ('.ritem[data-view="tools"]', 2), ("#railtools", 3), (".rfoot", 4),
    ("#cats", 5), (".search", 6), ("#view-tools .docs", 7), (".tool", 8),
    (".tool .acts", 9), (".creditbar", 10),
]

_BADGE_JS = """
(parts) => {
  document.querySelectorAll('.docsnum').forEach(e => e.remove());
  if (!document.getElementById('docsnumcss')) {
    const s = document.createElement('style'); s.id = 'docsnumcss';
    s.textContent = '.docsnum{position:fixed;z-index:9999;width:22px;height:22px;' +
      'border-radius:11px;background:#c2603a;color:#fff;font:700 12.5px/22px system-ui,' +
      'sans-serif;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.45);pointer-events:none}';
    document.head.appendChild(s);
  }
  let placed = 0;
  for (const [sel, n] of parts) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) continue;
    const d = document.createElement('div');
    d.className = 'docsnum'; d.textContent = n;
    // kept inside the window: a number half off its edge is a number nobody can read
    d.style.left = Math.min(Math.max(3, r.left - 11), innerWidth - 25) + 'px';
    d.style.top = Math.min(Math.max(3, r.top - 11), innerHeight - 25) + 'px';
    document.body.appendChild(d); placed++;
  }
  return placed;
}
"""


class Shown:
    """A tool shown as running: what the hub's Running is, with nothing behind it."""

    def __init__(self, tool):
        self.tool, self.local_port, self.token = tool, 9, ""
        self.started = time.time() - 1500

    @property
    def url(self):
        return "http://127.0.0.1:%d%s" % (self.local_port, self.tool.page)

    def alive(self):
        return True

    def stop(self):
        pass


def example_runs(now):
    """Run folders as the Results view lists them. Examples, named as the docs say they are."""
    rows = [
        ("adcp", "/scratch/user/jdoe/adcp_runs/MDM2_p53_peptides", 2 * 3600),
        ("hopemd", "/scratch/group/sflab/hopemd_runs/MDM2_p53_amber", 5 * 3600),
        ("pipelines", "/scratch/user/jdoe/hope/runs/TrkA_dimer_loop", 26 * 3600),
        ("bindcraft", "/scratch/group/sflab/bindcraft_runs/jdoe/PDL1_binders", 2 * 86400),
        ("aptamer", "/scratch/user/jdoe/hope-aptamer-runs/thrombin_exosite1", 3 * 86400),
        ("adcp", "/scratch/user/jdoe/adcp_runs/InsR_site1_peptides", 6 * 86400),
        ("hopemd", "/scratch/group/sflab/hopemd_runs/TrkA_hit3_openmm", 9 * 86400),
    ]
    out = []
    for key, path, age in rows:
        tool = catalogue.BY_KEY[key]
        out.append({"tool": key, "tool_name": tool.name, "name": os.path.basename(path),
                    "path": path, "when": int(now - age),
                    "next_steps": [{"to": to, "label": label} for to, label in tool.next_steps]})
    return out


class DemoHub(hubmod.Hub):
    """The real hub's page logic, answering from this machine."""

    def __init__(self, running=(), slow=()):
        super().__init__(None, user="jdoe", host="grace2")
        self.slow = set(slow)
        self.rows = example_runs(time.time())
        for key in running:
            self.running[key] = Shown(catalogue.BY_KEY[key])

    def launch(self, key, runs=""):
        tool = catalogue.BY_KEY[key]
        if key in self.running:
            return self.state_of(key)
        if key in self.slow:
            # What a person sees while a tool's environment loads on a cold login node.
            time.sleep(40)
        raise RuntimeError("%s was not started for the screenshots" % tool.name)

    def runs(self, refresh=False, limit_each=12):
        return self.rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--browser", default="",
                    help="a Chrome or Chromium to drive, when Playwright's own is not installed")
    ap.add_argument("--out", default=IMG)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)

    demo = DemoHub(running=("adcp", "hopemd"), slow=("aptamer",))
    httpd, _url = hubmod.serve(demo, port=0)          # serves from a thread of its own
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    print("  the page is at", base, flush=True)
    try:
        return shoot(base, demo.token, a.out, a.browser)
    finally:
        httpd.shutdown()


def shoot(base, token, out, browser_path=""):
    from playwright.sync_api import sync_playwright

    errors, made = [], []

    def save(page, name, clip=None):
        path = os.path.join(out, name)
        page.screenshot(path=path, clip=clip) if clip else page.screenshot(path=path)
        made.append(name)
        print("    wrote", name, flush=True)

    def union(page, *selectors, pad=0):
        """One clip holding all of these, across the full width of the window."""
        boxes = [b for b in (page.query_selector(sel).bounding_box() for sel in selectors) if b]
        top = max(0, min(b["y"] for b in boxes) - pad)
        bottom = max(b["y"] + b["height"] for b in boxes) + pad
        return {"x": 0, "y": top, "width": page.viewport_size["width"], "height": bottom - top}

    def step(name, fn):
        print("  " + name, flush=True)
        try:
            fn()
        except Exception:                                       # noqa: BLE001
            errors.append("%s:\n%s" % (name, traceback.format_exc(limit=3)))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=browser_path or None,
                                     args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 820}, device_scale_factor=2,
                                  color_scheme="light")
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))

        def tools_page():
            page.goto("%s/?t=%s" % (base, token), wait_until="load")
            page.wait_for_selector(".tool .state.up", timeout=20000)
            page.wait_for_timeout(800)
            save(page, "tools.png")
            n = page.evaluate(_BADGE_JS, PARTS)
            if n != len(PARTS):
                errors.append("only %d of %d numbered parts were on the screen" % (n, len(PARTS)))
            save(page, "tools-parts.png")
            page.evaluate("() => document.querySelectorAll('.docsnum').forEach(e => e.remove())")
            box = page.query_selector(".tool").bounding_box()
            save(page, "tool-block.png", {"x": box["x"] - 12, "y": box["y"] - 12,
                                          "width": box["width"] + 24, "height": box["height"] + 24})
        step("the Tools page", tools_page)

        def results_page():
            page.goto("%s/?t=%s" % (base, token), wait_until="load")
            page.wait_for_selector(".tool", timeout=20000)
            page.click('.ritem[data-view="runs"]')
            page.wait_for_selector("table.runs", timeout=20000)
            page.wait_for_timeout(600)
            save(page, "results.png")
        step("Results", results_page)

        def handoff():
            run = "/scratch/user/jdoe/adcp_runs/MDM2_p53_peptides"
            page.goto("%s/tool?key=hopemd&t=%s&from=%s" % (base, token, run), wait_until="load")
            page.wait_for_selector("#t-ready:not([hidden])", timeout=20000)
            page.wait_for_timeout(800)
            save(page, "handoff.png", union(page, ".toolbar", "#t-from", "#t-ready", pad=1))
        step("a run handed over", handoff)

        def starting():
            page.goto("%s/tool?key=aptamer&t=%s" % (base, token), wait_until="load")
            page.wait_for_selector("#t-wait:not([hidden])", timeout=20000)
            page.wait_for_timeout(1200)
            save(page, "starting.png", union(page, ".toolbar", "#t-wait", pad=1))
            page.goto("about:blank")
        step("a tool starting", starting)

        browser.close()

    missing = [n for n in WANT if n not in made]
    for name in missing:
        errors.append("%s was not taken" % name)
    if errors:
        print("\nPROBLEMS")
        for e in errors:
            print("  - " + e)
        return 1
    print("\nall %d pictures taken" % len(WANT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
