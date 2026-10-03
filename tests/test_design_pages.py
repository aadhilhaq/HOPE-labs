"""The two design pages: the line the launcher reads, the routes, the form, and a whole dry run.

By Aadhil Haq

RFdiffusion and BoltzGen are the two tools whose page is in this repository rather than in the
install, so this is the test that would otherwise be in theirs. It starts each page the way the
launcher starts it, as a subprocess printing to a pipe, and reads the line back with the
launcher's own regular expression: getting that line wrong is the one failure nobody would notice
until a tool stopped launching, because the page works perfectly and the launcher never sees it.

Then, against the running page: the documentation answers without a token and the API does not,
every field the form offers carries its card's default, the page has its Docs button and its bar,
and a run is submitted end to end with the driver's dry run on, which writes the run folder, the
target, the plan and the job script and calls no sbatch. Nothing here asks Slurm for anything.

The target is a structure written here rather than fetched, for two reasons: a test should not
need the RCSB to be answering, and a chain numbered from 18 is what makes BoltzGen's conversion
from the file's numbering to positions in the chain worth checking at all.

    python3 tests/test_design_pages.py
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from hope_flow import cards, drivers                                        # noqa: E402
from hope_labs import tools                                                 # noqa: E402
from hope_labs.pages import CARD_ONLY, SERVES                               # noqa: E402
from hope_labs.pages import docs as pagedocs                                # noqa: E402

fails, ran = [], 0


def check(cond, why):
    global ran
    ran += 1
    if not cond:
        fails.append(why)


# --- a target to design against ------------------------------------------------------------
#: Chain A numbered from 18, chain B from 1. The first is the whole point: BoltzGen counts
#: hotspots as positions in the chain, so residue 54 of chain A is its 37th residue, and a
#: conversion that quietly did nothing would pass against a chain numbered from 1.
FIRST_A, N_A, N_B = 18, 100, 40


def write_pdb(path):
    lines = []
    n = 0
    for chain, first, count in (("A", FIRST_A, N_A), ("B", 1, N_B)):
        for i in range(count):
            n += 1
            lines.append("ATOM  %5d  CA  ALA %s%4d    %8.3f%8.3f%8.3f  1.00  0.00           C"
                         % (n, chain, first + i, i * 3.8, 0.0, 0.0))
    lines.append("END")
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


# --- the page, started the way the launcher starts it ---------------------------------------

class Page:
    """One page as a subprocess, with the URL read off its output the launcher's way."""

    def __init__(self, tool, runs, dry_run=True):
        self.tool = tool
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "hope_labs.pages.serve", tool, "--port", "0",
             "--runs", runs] + (["--dry-run"] if dry_run else []),
            cwd=ROOT, env=dict(os.environ, PYTHONPATH=ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.said = ""
        self.port, self.token = 0, ""
        deadline = time.time() + 90
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                break
            self.said += line
            # The launcher's own reader, not a second copy of the pattern: if this stops matching,
            # the launcher has stopped seeing the page start.
            got = tools.BY_KEY[tool].ready(self.said, 0)
            if got:
                self.port, self.token = got
                return
        raise RuntimeError("%s never printed a URL line. It said:\n%s" % (tool, self.said))

    def url(self, path, token=True):
        base = "http://127.0.0.1:%d%s" % (self.port, path)
        if not token:
            return base
        return base + ("&" if "?" in path else "?") + "t=" + self.token

    def get(self, path, token=True):
        try:
            with urllib.request.urlopen(self.url(path, token), timeout=30) as answer:
                return answer.status, answer.headers.get("Content-Type", ""), answer.read()
        except urllib.error.HTTPError as why:
            return why.code, why.headers.get("Content-Type", ""), why.read()

    def post(self, path, body):
        request = urllib.request.Request(
            self.url(path), data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=300) as answer:
                return answer.status, json.loads(answer.read() or b"{}")
        except urllib.error.HTTPError as why:
            return why.code, json.loads(why.read() or b"{}")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()


work = tempfile.mkdtemp(prefix="hl_pages_", dir=os.environ.get("TMPDIR") or None)
target = write_pdb(os.path.join(work, "target.pdb"))

# The structure this test wrote has to be a structure the tools' own parser reads, or everything
# below is testing nothing.
from hope_flow.helpers import rfdiffusion_design                            # noqa: E402

present = rfdiffusion_design.chains_of(target)
check(sorted(present) == ["A", "B"] and len(present["A"]) == N_A and present["A"][0] == FIRST_A,
      "the test's own structure does not parse: %r" % {c: len(n) for c, n in present.items()})

# --- the catalogue: both tools now have a page -----------------------------------------------
for key in SERVES:
    tool = tools.BY_KEY[key]
    check(not tool.flow_only, "%s is still flow_only, so its tile offers no Launch" % key)
    check(tool.ready is tools._url_ready, "%s does not read a URL line" % key)
    line = tool.command(runs="~/runs", port=0)
    check("hope_labs.pages.serve %s" % key in line, "%s does not start its page: %s" % (key, line))
    check(tools.LABS_INSTALL in line, "%s's line does not run from the HOPE Labs checkout" % key)
    check(tool.install in line, "%s's line does not name the install: %s" % (key, line))
    check('"$HOME"/runs' in line, "%s's line drops the runs folder" % key)

# --- the pages themselves ----------------------------------------------------------------------
for tool in SERVES:
    runs = os.path.join(work, tool + "_runs")
    page = Page(tool, runs)
    card = cards.BY_KEY[tool]
    try:
        check(re.search(r"^open  http://127\.0\.0\.1:%d/\?t=\S+$" % page.port, page.said,
                        re.M) is not None,
              "%s's ready line is not the one tools.py documents:\n%s" % (tool, page.said))

        # ---- the documentation answers without a token, and the API does not -----------
        status, kind, body = page.get("/docs/index.html", token=False)
        check(status == 200 and kind.startswith("text/html") and b'class="side"' in body,
              "%s /docs/index.html without a token answered %s %s" % (tool, status, kind))
        for slug in pagedocs.NAV:
            status, _k, body = page.get("/docs/%s.html" % slug[0], token=False)
            check(status == 200 and b"<h1>" in body,
                  "%s /docs/%s.html answered %s" % (tool, slug[0], status))
        status, kind, _b = page.get("/docs/style.css", token=False)
        check(status == 200 and kind == "text/css",
              "%s /docs/style.css answered %s %s" % (tool, status, kind))
        status, _k, _b = page.get("/docs", token=False)
        # urllib follows the redirect, so a 200 here is index.html having been served.
        check(status == 200, "%s /docs did not lead to a page: %s" % (tool, status))
        for path in ("/docs/nope.html", "/docs/../serve.py", "/docs/pages/index.html"):
            status, _k, _b = page.get(path, token=False)
            check(status == 404, "%s %s answered %s, not 404" % (tool, path, status))
        for path in ("/api/hello", "/api/runs", "/api/run?path=%s" % runs):
            status, _k, _b = page.get(path, token=False)
            check(status == 403, "%s %s without a token answered %s" % (tool, path, status))
        status, _k, body = page.get("/api/hello")
        check(status == 200, "%s /api/hello with the token answered %s" % (tool, status))
        hello = json.loads(body)

        # ---- the form is the card ------------------------------------------------------
        offered = {f["key"]: f for f in hello["fields"]}
        expected = {s.key: s for s in card.settings if s.key not in CARD_ONLY[tool]}
        check(set(offered) == set(expected),
              "%s's form and its card do not offer the same settings: form %s, card %s"
              % (tool, sorted(set(offered) - set(expected)), sorted(set(expected) - set(offered))))
        for key, setting in expected.items():
            got = offered.get(key, {})
            check(got.get("default") == setting.default,
                  "%s %s defaults to %r on the page and %r on the card"
                  % (tool, key, got.get("default"), setting.default))
            check(got.get("choices") == list(setting.choices),
                  "%s %s offers %r and the card offers %r"
                  % (tool, key, got.get("choices"), list(setting.choices)))
            check(got.get("label") == setting.label and got.get("why") == setting.why,
                  "%s %s is labelled differently from its card" % (tool, key))
        # And the ones left out are left out on purpose, with a reason written down.
        for key in CARD_ONLY[tool]:
            check(key in {s.key for s in card.settings} and key not in offered,
                  "%s %s is in CARD_ONLY but that is not what the card and the form say" % (tool, key))
        targets = {f["key"]: f["default"] for f in hello["target_fields"]}
        check(targets.get("binder_min") == 70 and targets.get("binder_max") == 100,
              "%s's binder boxes do not take the target card's defaults: %r" % (tool, targets))
        check(hello["resources"] == drivers.DESIGN_RESOURCES[tool],
              "%s says Slurm will be asked for something the driver does not ask for" % tool)

        # ---- the page carries its Docs button and its bar ------------------------------
        status, kind, body = page.get("/", token=False)
        text = body.decode("utf-8")
        check(status == 200 and kind.startswith("text/html"), "%s / answered %s" % (tool, status))
        check("__CREDIT" not in text and "__APP__" not in text and "__TOOL__" not in text,
              "%s's page was served with a placeholder left in it" % tool)
        # Escaped, because the kit escapes it on the way into the bar: "Texas A&M" is written
        # "Texas A&amp;M" in the page, and a test matching the raw string would never pass.
        check('class="creditbar"' in text and html.escape(pagedocs.COPYRIGHT) in text,
              "%s's page has no bar along the bottom carrying the copyright" % tool)
        check('id="docsbtn"' in text and 'href="/docs/index.html"' in text,
              "%s's page has no Docs button" % tool)
        check(pagedocs.ABOUT[tool].app in text, "%s's page does not name itself" % tool)
        # Whose work it is, on every screen, because the bar is on every screen.
        upstream = "RFdiffusion" if tool == "rfdiffusion" else "BoltzGen"
        check(upstream in text and hello["tool_version"] in text,
              "%s's bar does not credit %s and the version it runs" % (tool, upstream))
        status, kind, _b = page.get("/static/app.js", token=False)
        check(status == 200 and "javascript" in kind, "%s's script answered %s" % (tool, status))

        # ---- reading the target --------------------------------------------------------
        status, got = page.post("/api/target", {"kind": "path", "path": target})
        check(status == 200 and got.get("residues") == N_A + N_B,
              "%s would not read the target: %r" % (tool, got))
        chains = {c["id"]: c for c in got.get("chains", [])}
        check(chains.get("A", {}).get("first") == FIRST_A,
              "%s does not report the numbering the chain actually uses: %r" % (tool, chains))
        status, got = page.post("/api/target", {"kind": "path", "path": target + ".nope"})
        check(status == 400 and "nope" in json.dumps(got),
              "%s did not refuse a file that is not there: %s %r" % (tool, status, got))

        # ---- checking the form ---------------------------------------------------------
        form = {"path": target, "chains": "A", "hotspots": "54,56,66-70",
                "binder_min": 70, "binder_max": 100, "name": "pagetest"}
        for key, field in offered.items():
            form[key] = field["default"]
        status, got = page.post("/api/check", form)
        check(status == 200 and not got["problems"] and not got["fields"],
              "%s refused a form that should pass: %r" % (tool, got))
        check(got["plan"]["gpu"] in ("a100", "a40") and got["plan"]["partition"] == "gpu",
              "%s's plan does not say what Slurm will be asked for: %r" % (tool, got["plan"]))
        check(got["plan"]["mem"] == drivers.DESIGN_RESOURCES[tool]["mem"],
              "%s's plan and the driver disagree about memory" % tool)

        # The hotspots, as the job will be given them. This is the check that matters most on
        # BoltzGen, where the numbers change, and it is worth having on both.
        lines = " ".join(got["preview"]["lines"])
        if tool == "rfdiffusion":
            check("contigmap.contigs=[A18-117/0 70-100]" in lines,
                  "the contig map is not what the job will be given: %r" % lines)
            check("ppi.hotspot_res=[A54,A56,A66,A67,A68,A69,A70]" in lines,
                  "the hotspots are not spelled out for RFdiffusion: %r" % lines)
        else:
            # Chain A starts at 18, so 54 is its 37th residue and 66 to 70 are 49 to 53.
            check("positions 37,39,49,50,51,52,53" in lines,
                  "the hotspots were not converted to positions in the chain: %r" % lines)
            check("numbered %d to %d" % (FIRST_A, FIRST_A + N_A - 1) in lines,
                  "the conversion does not show the numbering it converted from: %r" % lines)

        # A residue the chain has not got, named against the box that holds it.
        status, got = page.post("/api/check", dict(form, hotspots="54,9999"))
        check("hotspots" in got["fields"] and "9999" in got["fields"]["hotspots"],
              "%s did not name a residue that is not in the target: %r" % (tool, got["fields"]))
        status, got = page.post("/api/check", dict(form, chains="Z"))
        check("chains" in got["fields"], "%s accepted a chain the target has not got" % tool)
        status, got = page.post("/api/check", dict(form, hotspots=""))
        check(any("hotspot" in p for p in got["problems"]),
              "%s accepted a form with no hotspots, which a flow refuses: %r" % (tool, got))
        status, got = page.post("/api/check", dict(form, walltime="half an hour"))
        check("walltime" in got["fields"], "%s accepted a walltime Slurm would not: %r" % (tool, got))
        status, got = page.post("/api/check", dict(form, out=os.path.expanduser("~/runs")))
        check("out" in got["fields"], "%s accepted a run folder inside home" % tool)
        # A number with a typo in it, on a setting the flow does not insist on. The flow checks
        # only the ones it will not start without, so without this the driver would be handed
        # "ten" and fail somewhere nobody could act on.
        optional = next((f["key"] for f in hello["fields"]
                         if f["kind"] == "number" and not f["needed"]), "")
        if optional:
            status, got = page.post("/api/check", dict(form, **{optional: "ten"}))
            check(optional in got["fields"],
                  "%s accepted %r as a number: %r" % (tool, optional, got["fields"]))
        status, got = page.post("/api/check", dict(form, binder_min="seventy"))
        check("binder_min" in got["fields"] and not got["plan"],
              "%s accepted a binder length that is not a number: %r" % (tool, got))

        # ---- a whole dry run -----------------------------------------------------------
        status, got = page.post("/api/submit", form)
        check(status == 200 and got.get("run"),
              "%s would not write a dry run: %s %r" % (tool, status, got))
        run = got.get("run") or {}
        check(run.get("job_id") == "" and run.get("dry_run") is True,
              "%s queued something on a dry run: %r" % (tool, run))
        where = run.get("path") or ""
        check(where.startswith(os.path.abspath(runs)),
              "%s wrote its run outside the folder it was given: %r" % (tool, where))
        for name in ("flow.json", "submission.json", os.path.join("inputs", "target.pdb")):
            check(os.path.isfile(os.path.join(where, name)),
                  "%s's dry run left no %s" % (tool, name))
        job = os.path.join(run.get("rundir") or "", "job.sbatch")
        check(os.path.isfile(job), "%s's dry run wrote no job script" % tool)
        script = open(job).read() if os.path.isfile(job) else ""
        check("--gres=gpu:%s:1" % got["run"]["plan"]["gpu"] in script,
              "%s's job script asks for a different card from the plan the page showed" % tool)
        check('XDG_CACHE_HOME="$OUT/cache"' in script and "MPLCONFIGDIR" in script
              and "CUDA_CACHE_PATH" in script,
              "%s's job script lets the caches reach home" % tool)
        plan = os.path.join(run.get("rundir") or "", "plan.json")
        check(os.path.isfile(plan), "%s's dry run wrote no plan" % tool)
        if os.path.isfile(plan):
            told = json.load(open(plan))
            check(told.get("hotspots") == "54,56,66-70" and told.get("chains") == "A",
                  "%s's plan does not carry what the form said: %r" % (tool, told))
            check(os.path.isfile(told.get("target") or ""),
                  "%s's plan points at a target that is not there" % tool)

        # ---- and the Runs screen finds it ----------------------------------------------
        status, _k, body = page.get("/api/runs?scope=mine")
        listed = json.loads(body)["runs"]
        check([r for r in listed if r["path"] == where],
              "%s's Runs screen does not list the run it just wrote" % tool)
        one = next((r for r in listed if r["path"] == where), {})
        check(one.get("state") == "DRY RUN",
              "%s's dry run is not shown as one: %r" % (tool, one.get("state")))
        check(one.get("designs") is None,
              "%s shows a design count for a run that has written no designs.json" % tool)
        status, _k, body = page.get("/api/run?path=" + where)
        detail = json.loads(body)["run"]
        check(detail.get("results") == run.get("rundir"),
              "%s does not say where the results will be: %r" % (tool, detail.get("results")))
        check(any(f.endswith("job.sbatch") for f in detail.get("files", [])),
              "%s's run view does not offer the job script: %r" % (tool, detail.get("files")))
        status, kind, body = page.get("/api/download?path=%s&file=%s"
                                      % (where, os.path.relpath(job, where)))
        check(status == 200 and b"#SBATCH" in body,
              "%s would not hand over its own job script: %s" % (tool, status))
        status, _k, _b = page.get("/api/download?path=%s&file=../../etc/passwd" % where)
        check(status in (403, 404), "%s served a file outside the run: %s" % (tool, status))
        status, _k, _b = page.get("/api/run?path=/etc")
        check(status == 400, "%s read a folder outside its run roots: %s" % (tool, status))
    finally:
        page.stop()

# Nothing above should have left the flag set, or the server could not queue anything after a
# dry run. It is a module flag, and that is the risk of one.
check(drivers.DRY_RUN is False, "the driver's dry run flag was left on")

shutil.rmtree(work, ignore_errors=True)
if fails:
    print("FAIL %d of %d" % (len(fails), ran))
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ok  %d checks: both design pages, their docs, their forms and a dry run each" % ran)
