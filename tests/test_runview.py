"""The plan, and the view of a flow that is running: the routes behind both, and what the page
has to draw them with.

By Aadhil Haq

Two things are checked here. The first is that Launch commits nothing: the plan route asks the
runner what a flow would do and hands the answer back whole, and nothing on the way to it queues.
The second is the run view's seam - the status answer carries all seven of the runner's states
through unchanged, the folder a flow landed in is written down beside the flow it was drawn from,
and the resume route is really there and really refuses a folder that is not a flow.

That last one runs the runner itself rather than a stand-in, in a process whose PATH holds no
sbatch: the point of the check is the wording a person gets back, which comes out of the runner,
and no test of this page may be one sbatch away from committing a card.

    python3 tests/test_runview.py
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from hope_labs import canvas, hub, settings                                      # noqa: E402
from hope_flow import run as runner, state as st                                 # noqa: E402
from hope_flow.flow import Flow                                                  # noqa: E402

fails, ran = [], 0


def check(cond, why):
    global ran
    ran += 1
    if not cond:
        fails.append(why)


# --- what the runner says, answered without a cluster -----------------------
class Stub:
    """A runner that answers but does nothing, and remembers what it was asked for.

    The plan has to be provable without a cluster, and "Launch queued nothing" is only provable by
    something that would have noticed.
    """

    def __init__(self):
        self.asked = []

    def plan(self, doc, runs=""):
        self.asked.append("plan")
        return runner.plan(Flow.from_json(doc), runs or "/scratch/user/jdoe/hope_flows")

    def launch(self, doc, runs=""):
        self.asked.append("launch")
        return {"folder": "/scratch/user/jdoe/hope_flows/" + (doc.get("name") or "flow"),
                "log": ["queued"]}

    def status(self, folder):
        self.asked.append("status")
        return EVERY_STATE

    def resume(self, folder):
        self.asked.append("resume")
        return {"resumed": "nothing to carry on"}

    def stop(self, folder):
        self.asked.append("stop")
        return {"stopped": "stopped 2 jobs"}


#: One card in each of the seven states the runner has, so the page is proved against all of them
#: rather than against the three a happy flow goes through.
EVERY_STATE = {
    "name": "sevenways",
    "cards": [
        {"id": "a", "card": "target", "name": "Target", "state": "done", "jobs": [],
         "rundir": "/scratch/user/jdoe/hope_flows/sevenways/inputs", "note": "", "changed": 1},
        {"id": "b", "card": "pipelines", "name": "HOPE-pipelines", "state": "running",
         "jobs": ["101", "102"], "rundir": "/scratch/user/jdoe/hope/runs/sevenways_pipelines",
         "note": "", "changed": 2},
        {"id": "c", "card": "bindcraft", "name": "BindCraft2", "state": "failed", "jobs": ["103"],
         "rundir": "/scratch/group/sflab/bindcraft_runs/jdoe/sevenways_bindcraft",
         "note": "103 ended as node_fail", "changed": 3},
        {"id": "d", "card": "adcp", "name": "ADCP docking", "state": "queued", "jobs": ["104"],
         "rundir": "", "note": "", "changed": 4},
        {"id": "e", "card": "hopemd", "name": "HOPE-MD", "state": "waiting", "jobs": [],
         "rundir": "", "note": "", "changed": 5},
        {"id": "f", "card": "adcp", "name": "ADCP docking", "state": "ready", "jobs": [],
         "rundir": "", "note": "", "changed": 6},
        {"id": "g", "card": "hopemd", "name": "HOPE-MD", "state": "stopped", "jobs": ["105"],
         "rundir": "", "note": "stopped by hand", "changed": 7},
    ],
    "done": 1, "of": 7, "state": "failed", "note": "103 ended as node_fail",
}


class NoCluster(hub.Hub):
    """The page logic with a stub where the cluster is: this is about the page, not about Grace."""

    def __init__(self):
        super().__init__(None, user="jdoe", host="grace2")
        self.flows = Stub()

    def runs(self, refresh=False, limit_each=12):
        return []


def ask(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            return answer.status, json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except ValueError:
            return exc.code, {"body": raw.decode("utf8", "replace")}


h = NoCluster()
httpd, _url = hub.serve(h, port=0)
base = "http://127.0.0.1:%d" % httpd.server_address[1]
tok = "?t=" + h.token
example = canvas.example()
# The flows and the folders they landed in are kept in the person's own settings file; a test
# writes nowhere near it.
kept, settings.CONFIG = settings.CONFIG, os.path.join(tempfile.mkdtemp(), ".hope_labs.json")
work = tempfile.mkdtemp(prefix="runview.")
try:
    # --- the plan: the whole answer, and nothing queued on the way to it ----
    code, body = ask("/api/flow/plan" + tok, {"flow": example})
    check(code == 200, "/api/flow/plan answered %s: %s" % (code, body))
    check(sorted(body) == ["account", "cards", "folder", "name", "notes", "partition", "problems"],
          "the plan route does not hand back the runner's own answer: %s" % sorted(body))
    check([c["id"] for c in body["cards"]] == [n["id"] for n in example["nodes"]],
          "the plan does not name every card in the order they run: %s"
          % [c["id"] for c in body["cards"]])
    check(all(sorted(c) == ["card", "id", "lands_in", "name", "queues", "scale", "waits_for"]
              for c in body["cards"]),
          "a card in the plan is missing what the page draws: %s" % body["cards"][0])
    md = next(c for c in body["cards"] if c["card"] == "hopemd")
    check("750 ns" in md["scale"] and "amber" in md["scale"],
          "the numbers behind the cost are not in the plan: %r" % md["scale"])
    check(md["lands_in"] and md["lands_in"].startswith("/"),
          "the plan does not say where a card lands: %r" % md["lands_in"])
    check(sorted(c["name"] for c in body["cards"] if c["waits_for"])
          == ["ADCP docking", "BindCraft2", "HOPE-MD", "HOPE-pipelines"],
          "the plan does not say what waits for what")
    # The example has both tracks arriving at the simulation, which is the note that matters most.
    check(any("tracks arrive at the simulation" in n for n in body["notes"]),
          "the plan does not warn that two tracks double the runs: %s" % body["notes"])
    check(body["problems"] == [], "the example's plan has problems: %s" % body["problems"])
    check(h.flows.asked == ["plan"],
          "asking for a plan asked the runner for %s as well" % h.flows.asked)

    # --- a flow that cannot run gets a plan with problems in it -------------
    bad = json.loads(json.dumps(example))
    for node in bad["nodes"]:
        if node["card"] == "hopemd":
            node["settings"] = dict(node["settings"], engine="")
    code, body = ask("/api/flow/plan" + tok, {"flow": bad})
    check(code == 200 and body["problems"],
          "a flow with an unanswered setting has a plan with no problems in it: %s" % body)
    check(any("engine" in p for p in body["problems"]),
          "the plan does not say which setting is unanswered: %s" % body["problems"])
    check(body["cards"], "a refused flow still has a plan to read: %s" % body)
    # and the launch route refuses it, so Queue it being hidden is a courtesy and not the gate
    code, body = ask("/api/flow/launch" + tok, {"flow": bad})
    check(code == 400 and "cannot be queued" in (body.get("error") or ""),
          "/api/flow/launch should refuse a flow with an unanswered setting: %s %s" % (code, body))
    check(h.flows.asked == ["plan", "plan"],
          "a refused flow reached the runner: %s" % h.flows.asked)

    # --- queueing it, and the folder written down beside the drawing --------
    code, body = ask("/api/flow/launch" + tok, {"flow": example})
    folder = body.get("folder")
    check(code == 200 and folder, "/api/flow/launch answered %s %s" % (code, body))
    check(h.flows.asked == ["plan", "plan", "launch"],
          "launching asked the runner for %s" % h.flows.asked)
    code, body = ask("/api/flow/queued" + tok)
    check(code == 200 and [r["folder"] for r in body.get("runs", [])] == [folder],
          "the folder a flow landed in was not remembered: %s" % body)
    back = body["runs"][0]
    check(back.get("name") == example["name"] and back.get("started"),
          "a queued flow is remembered without its name or when it started: %s" % sorted(back))
    check((back.get("flow") or {}).get("nodes") == example["nodes"]
          and (back["flow"]).get("edges") == example["edges"],
          "the drawing was not kept with the folder, so the run view has nothing to draw")
    check(all(len(n.get("at", [])) == 2 for n in back["flow"]["nodes"]),
          "the drawing was kept without the places the cards were put")
    check("runs" in json.load(open(settings.CONFIG)),
          "the queued flows are not kept beside the launcher's other settings")
    check([f["name"] for f in settings.flows()] == [],
          "queueing a flow also saved it as a flow, which Save is for")

    # the same name queued twice is two runs, because it is two folders of work
    settings.queued_save(dict(example, name="example"), folder + "_20261003-090000")
    check(len(settings.queued()) == 2,
          "the same flow queued twice kept one folder: %s" % settings.queued())
    check(settings.queued()[0]["folder"].endswith("090000"),
          "the newest run is not first: %s" % [r["folder"] for r in settings.queued()])
    for n in range(settings.KEEP_RUNS + 5):
        settings.queued_save(dict(example, name="many"), "/scratch/user/jdoe/f/many_%03d" % n)
    check(len(settings.queued()) == settings.KEEP_RUNS,
          "the kept runs grow without limit: %d" % len(settings.queued()))
    try:
        settings.queued_save(example, "")
        check(False, "a run with no folder was remembered anyway")
    except ValueError:
        check(True, "")

    # --- the status answer, in all seven states -----------------------------
    code, body = ask("/api/flow/status" + tok, {"folder": folder})
    check(code == 200 and [c["state"] for c in body["cards"]]
          == ["done", "running", "failed", "queued", "waiting", "ready", "stopped"],
          "the status route does not carry every state through: %s" % body)
    check(set(c["state"] for c in body["cards"])
          == {st.WAITING, st.READY, st.QUEUED, st.RUNNING, st.DONE, st.FAILED, st.STOPPED},
          "the seven states checked here are not the runner's own seven")
    check((body.get("done"), body.get("of")) == (1, 7),
          "how far the flow has got is not in the answer: %s of %s"
          % (body.get("done"), body.get("of")))
    check(all(sorted(c) == ["card", "changed", "id", "jobs", "name", "note", "rundir", "state"]
              for c in body["cards"]), "a card's record is missing something the page shows")

    # --- stop and carry on are both there -----------------------------------
    code, body = ask("/api/flow/stop" + tok, {"folder": folder})
    check(code == 200 and body.get("stopped"), "/api/flow/stop answered %s %s" % (code, body))
    code, body = ask("/api/flow/resume" + tok, {"folder": folder})
    check(code == 200 and "resumed" in body, "/api/flow/resume answered %s %s" % (code, body))
    check(h.flows.asked[-2:] == ["stop", "resume"],
          "stop and resume did not reach the runner: %s" % h.flows.asked)
    code, _body = ask("/api/flow/resume", {"folder": folder})
    check(code == 403, "/api/flow/resume without the token answered %s, not 403" % code)

    # --- the page has what it needs to draw both ----------------------------
    page = hub.index_page()
    for want in ('id="flowplan"', 'id="planbody"', 'id="planqueue"', 'id="planback"',
                 'id="flowrun"', 'id="runcanvas"', 'id="runwires"', 'id="runcards"',
                 'id="runhead"', 'id="runreload"', 'id="runcarry"', 'id="runstop"',
                 'id="flowruns"', 'id="flowwrap"'):
        check(want in page, "the page has no %s" % want)
    with open(os.path.join(ROOT, "hope_labs", "web", "flow.js"), encoding="utf-8") as fh:
        script = fh.read()
    check('$("flowlaunch").onclick = () => { showPlan(); };' in script,
          "Launch does not ask for the plan")
    check(script.count('"/api/flow/launch"') == 1
          and 'api("/api/flow/launch", { flow: FLOW })' in script,
          "something other than Queue it queues the flow")
    check(script.index('$("flowlaunch").onclick') < script.index('$("planqueue").onclick'),
          "Launch comes after Queue it in the page, which is the wrong way round to read")
    for want in ("/api/flow/plan", "/api/flow/status", "/api/flow/resume", "/api/flow/stop",
                 "/api/flow/queued"):
        check('"%s"' % want in script, "the page never asks %s" % want)
    check("RUN_EVERY = 20000" in script, "a running flow is not read again every 20 seconds")
    with open(os.path.join(ROOT, "hope_labs", "web", "style.css"), encoding="utf-8") as fh:
        css = fh.read()
    for want in (".sp.done", ".sp.failed", ".sp.running", ".sp.queued", ".node.watched",
                 ".runsplit", ".planotes", ".planbad"):
        check(want in css, "nothing in the stylesheet says %s" % want)

    # --- the runner's own refusal, run for real ----------------------------
    # Nothing here may be one sbatch away from committing a card, so the runner is given a PATH
    # with no sbatch in it: a resume that somehow reached the queue could not reach it.
    nowhere = os.path.join(work, "bin")
    os.makedirs(nowhere, exist_ok=True)
    check(shutil.which("sbatch", path=nowhere) is None, "the scrubbed PATH still finds sbatch")

    class Local(hub.Flows):
        """The real Flows, with the runner run here instead of down a connection to a login node.

        What is being checked is the wording a person gets back when a folder is not a flow, and
        that comes out of the runner: a stand-in would only prove the stand-in.
        """

        def _run(self, args, timeout=180):
            got = subprocess.run([sys.executable, "-m", "hope_flow.cli"] + shlex.split(args),
                                 cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                                 env={"PATH": nowhere, "PYTHONPATH": ROOT,
                                      "HOME": work, "SCRATCH": work})
            return got.returncode, got.stdout, got.stderr

    flows = Local(h)
    notaflow = os.path.join(work, "not a flow at all")
    os.makedirs(notaflow, exist_ok=True)
    try:
        flows.resume(notaflow)
        check(False, "resume took a folder with no flow in it")
    except RuntimeError as why:
        check("flow.json" in str(why) or "No such file" in str(why),
              "resume refuses a folder that is not a flow without saying why: %s" % why)
        check(len(str(why)) <= 300, "the refusal is longer than a person will read")

    # A flow every card of which has finished: resume has nothing to do, and does nothing. This is
    # the one path through resume that reaches the end without an sbatch, which is why it is the
    # one a test may take.
    done = runner.write_out(Flow.from_json(example), os.path.join(work, "finished"))
    record = st.State.read(done)
    for node in example["nodes"]:
        record.set(node["id"], state=st.DONE, rundir=os.path.join(done, node["id"]), jobs=[])
    record.write()
    got = flows.resume(done)
    check("nothing to carry on" in got.get("resumed", ""),
          "resume on a finished flow said %r" % got.get("resumed"))
    check(st.State.read(done).summary(Flow.from_json(example))["done"] == len(example["nodes"]),
          "resume on a finished flow changed what had finished")
finally:
    settings.CONFIG, gone = kept, settings.CONFIG
    shutil.rmtree(os.path.dirname(gone), ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    httpd.shutdown()

if fails:
    print("FAIL %d of %d" % (len(fails), ran))
    for why in fails:
        print("  - " + why)
    sys.exit(1)
print("ok  %d checks: the plan, the run view's routes and the folder they are remembered by" % ran)
