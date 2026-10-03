"""The flow canvas: the cards it draws from, the checking behind it, and the flows it keeps.

By Aadhil Haq

What is checked here is the seam between the canvas and the cluster. The canvas must hold no
opinion of its own about which links are legal, so the catalogue it reads is the runner's own
file, byte for byte, and the sentences it lists are the ones Flow.check() gives: both are
compared here rather than described. The rest is the routes - the catalogue behind the token, the
check route, the flows kept beside the launcher's other settings, and Launch, which has nowhere
to go until the runner is installed and says so.

    python3 tests/test_flow_canvas.py
"""
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from hope_labs import canvas, hub, settings
from hope_flow import cards, flow    # noqa: E402

#: The catalogue and the flow document as the runner has them. Compared where the checkout is
#: present, skipped where it is not, as the docs kit is.
fails, ran = [], 0


def check(cond, why):
    global ran
    ran += 1
    if not cond:
        fails.append(why)


def flow_with(binder_max, links):
    """A flow drawn by hand: a filled-in target, two design tracks, docking and a simulation."""
    nodes = [{"id": "t", "card": "target", "settings": {
                  "source": "rcsb", "pdb_id": "5O45", "chains": "A", "hotspots": "54,56,66-70",
                  "binder_min": 18, "binder_max": binder_max}},
             {"id": "p", "card": "pipelines"}, {"id": "b", "card": "bindcraft"},
             {"id": "a", "card": "adcp"}, {"id": "m", "card": "hopemd"}]
    port = {"t>p": ("t", "target", "p", "target"), "t>b": ("t", "target", "b", "target"),
            "t>a": ("t", "target", "a", "target"), "p>a": ("p", "sequences", "a", "sequences"),
            "b>a": ("b", "sequences", "a", "sequences"),
            "b>m": ("b", "complexes", "m", "structures"), "a>m": ("a", "poses", "m", "structures")}
    return {"version": 1, "name": "bylaptop", "runs_root": "", "nodes": nodes,
            "edges": [{"from": port[k][0], "fromPort": port[k][1],
                       "to": port[k][2], "toPort": port[k][3]} for k in links]}


# --- the canvas and the runner read one file --------------------------------
check(canvas.cards.__file__ == cards.__file__ and canvas.flow.__file__ == flow.__file__,
      "the canvas reads the runner's own rules, not a copy of them")
check("hope_flow" in cards.__file__, "which live in hope_flow: %s" % cards.__file__)

# --- the example is a flow, not a sketch ------------------------------------
example = canvas.example()
check(flow.Flow.from_json(example).check() == [],
      "the example flow does not validate: %s" % flow.Flow.from_json(example).check())
check(sorted(n["card"] for n in example["nodes"])
      == ["adcp", "bindcraft", "hopemd", "pipelines", "target"],
      "the example is not the flow the lab runs: %s" % [n["card"] for n in example["nodes"]])
check(len([e for e in example["edges"] if e["to"] == "hopemd"]) == 2,
      "both tracks should arrive at HOPE-MD")
check(all(len(n.get("at", [])) == 2 for n in example["nodes"]),
      "the example does not say where its cards go")

# --- the length refusal, which is the one about a number --------------------
long_binder = flow_with(100, ("t>p", "t>b", "t>a", "b>a", "b>m", "a>m"))
said = flow.Flow.from_json(long_binder).check()
check(any("30 residues or fewer" in s and "up to 100" in s for s in said),
      "a 100-residue design linked to the docking is not refused for its length: %s" % said)
check(flow.Flow.from_json(flow_with(24, ("t>p", "t>b", "t>a", "b>a", "b>m", "a>m"))).check() == [],
      "the same flow with short binders should be sound")
# and the table the canvas colours its sockets from says it in the same words
table = canvas.refusals({"binder_max": 100})
check(table["bindcraft:sequences>adcp:sequences"]
      == cards.link_refused("bindcraft", "sequences", "adcp", "sequences", {"binder_max": 100}),
      "the refusal table does not quote the catalogue")
check(len(table) == sum(len(a.outputs) * len(b.inputs)
                        for a in cards.CARDS for b in cards.CARDS),
      "the refusal table does not cover every pair of sockets")


# --- the routes, through the launcher's own handler -------------------------
class NoCluster(hub.Hub):
    """The page logic with nothing behind it: these checks are about the canvas, not the cluster."""

    def __init__(self):
        super().__init__(None, user="jdoe", host="grace2")

    def runs(self, refresh=False, limit_each=12):
        return []


def ask(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as answer:
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
# The flows are kept in the person's own settings file; a test writes nowhere near it.
kept, settings.CONFIG = settings.CONFIG, os.path.join(tempfile.mkdtemp(), ".hope_labs.json")
try:
    code, _body = ask("/api/flow/cards")
    check(code == 403, "/api/flow/cards without the token answered %s, not 403" % code)
    code, body = ask("/api/flow/cards" + tok)
    check(code == 200 and [c["key"] for c in body.get("cards", [])]
          == [c.key for c in cards.CARDS],
          "/api/flow/cards answered %s with %s" % (code, sorted(body)))
    check(body.get("dockable_max_length") == cards.DOCKABLE_MAX_LENGTH
          and body.get("kinds") == cards.KINDS, "the catalogue route does not serve catalogue()")
    target = next(c for c in body["cards"] if c["key"] == "target")
    check([s["kind"] for s in target["settings"]]
          == [s.kind for s in cards.TARGET.settings],
          "the target's settings do not reach the canvas as the catalogue has them")
    check(all(s.get("why") is not None for s in target["settings"]),
          "the line under each field does not reach the canvas")

    # the check route and Flow.check() are one answer
    for name, doc in (("the example", example), ("a long binder docked", long_binder),
                      ("an empty canvas", {"name": "", "nodes": [], "edges": []}),
                      ("a flow with no target", {"name": "x", "nodes": [{"id": "m",
                                                                         "card": "hopemd"}],
                                                 "edges": []})):
        code, body = ask("/api/flow/check" + tok, {"flow": doc})
        check(code == 200 and body.get("problems") == flow.Flow.from_json(doc).check(),
              "/api/flow/check disagrees with Flow.check() about %s: %s against %s"
              % (name, body.get("problems"), flow.Flow.from_json(doc).check()))
    code, body = ask("/api/flow/check" + tok, {"flow": long_binder})
    check(any("30 residues or fewer" in s for s in body.get("problems", [])),
          "the check route does not say why a long binder cannot be docked: %s" % body)
    check(body.get("refusals", {}).get("bindcraft:sequences>adcp:sequences", "")
          == cards.link_refused("bindcraft", "sequences", "adcp", "sequences",
                                {"binder_max": 100}),
          "the check route's table does not carry the catalogue's wording")
    # the same flow, re-checked after the binder length is brought down, draws clean
    code, body = ask("/api/flow/check" + tok, {"flow": flow_with(24, ("t>p", "t>b", "t>a", "b>a",
                                                                      "b>m", "a>m"))})
    check(body.get("problems") == [] and not body["refusals"]["bindcraft:sequences>adcp:sequences"],
          "shortening the binder does not clear the link: %s" % body.get("problems"))

    code, body = ask("/api/flow/example" + tok)
    check(code == 200 and body.get("nodes"), "/api/flow/example answered %s" % code)
    code, body = ask("/api/flow/check" + tok, {"flow": body})
    check(body.get("problems") == [], "the example served to the canvas does not validate: %s"
          % body.get("problems"))

    # Launch has nowhere to go yet, and says so in one sentence
    code, body = ask("/api/flow/launch" + tok, {"flow": example})
    check(body.get("error") == canvas.RUNNER_MISSING,
          "/api/flow/launch answered %s %s, not the runner's absence" % (code, body))

    # a flow is named, kept and reopened, in the settings file on this computer
    code, body = ask("/api/flow/saved" + tok)
    check(code == 200 and body.get("flows") == [], "/api/flow/saved starts with %s" % body)
    code, body = ask("/api/flow/save" + tok, {"flow": dict(example, name="mine")})
    check(code == 200 and [f["name"] for f in body.get("flows", [])] == ["mine"],
          "/api/flow/save answered %s %s" % (code, body))
    code, body = ask("/api/flow/saved" + tok)
    back = (body.get("flows") or [{}])[0]
    check(back.get("nodes") == example["nodes"] and back.get("edges") == example["edges"],
          "a saved flow does not come back as it was drawn")
    check(os.path.isfile(settings.CONFIG) and "flows" in json.load(open(settings.CONFIG)),
          "the flows are not kept beside the launcher's other settings")
    code, body = ask("/api/flow/save" + tok, {"flow": {"name": "", "nodes": []}})
    check(code == 400 and "name" in (body.get("error") or ""),
          "a flow with no name was kept anyway: %s %s" % (code, body))
    code, body = ask("/api/flow/delete" + tok, {"name": "mine"})
    check(body.get("flows") == [], "a flow was not forgotten: %s" % body)

    # the view itself: the rail button, the canvas, and the script that draws it
    page = hub.index_page()
    check('data-view="flow"' in page and ">Flows<" in page, "the rail has no Flows button")
    check('id="canvas"' in page and 'id="palette"' in page and 'id="panel"' in page,
          "the page has no canvas, palette or settings panel")
    check('id="flowlaunch"' in page and 'id="problems"' in page,
          "the page has no Launch button or list of problems")
    check('src="/static/flow.js"' in page, "the page does not load the canvas")
    check('class="creditbar"' in page, "the bar along the bottom is missing from the page")
finally:
    settings.CONFIG, gone = kept, settings.CONFIG
    shutil.rmtree(os.path.dirname(gone), ignore_errors=True)
    httpd.shutdown()

if fails:
    print("FAIL %d of %d" % (len(fails), ran))
    for why in fails:
        print("  - " + why)
    sys.exit(1)
print("ok  %d checks: the cards, the canvas's routes and the flows it keeps" % ran)
