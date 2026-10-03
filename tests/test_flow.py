#!/usr/bin/env python3
"""The graph: what may be drawn, what may not, and the order it runs in."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hope_flow import cards, flow                                        # noqa: E402

fails = []


def ok(cond, what):
    print("%s %s" % ("ok  " if cond else "FAIL", what))
    if not cond:
        fails.append(what)


def built(binder=(70, 100), links=("t>p", "t>b", "t>a", "p>a", "b>m", "a>m")):
    """The flow a person draws: a target, two design tracks, docking, one simulation."""
    nodes = [{"id": "t", "card": "target", "settings": {
                  "source": "rcsb", "pdb_id": "5O45", "chains": "A", "hotspots": "54,56,66-70",
                  "binder_min": binder[0], "binder_max": binder[1]}},
             {"id": "p", "card": "pipelines"}, {"id": "b", "card": "bindcraft"},
             {"id": "a", "card": "adcp"}, {"id": "m", "card": "hopemd"}]
    port = {"t>p": ("t", "target", "p", "target"), "t>b": ("t", "target", "b", "target"),
            "t>a": ("t", "target", "a", "target"), "p>a": ("p", "sequences", "a", "sequences"),
            "b>a": ("b", "sequences", "a", "sequences"), "b>m": ("b", "complexes", "m", "structures"),
            "a>m": ("a", "poses", "m", "structures")}
    edges = [{"from": port[k][0], "fromPort": port[k][1], "to": port[k][2], "toPort": port[k][3]}
             for k in links]
    return flow.Flow.from_json({"name": "pdl1", "nodes": nodes, "edges": edges})


f = built()
ok(f.check() == [], "the flow drawn as asked for is sound: %s" % (f.check() or "no problems"))
ok([n.id for n in f.order()][0] == "t", "the target runs first")
order = [n.id for n in f.order()]
ok(order.index("p") < order.index("a") and order.index("a") < order.index("m"),
   "design, then docking, then simulation: %s" % " ".join(order))
ok(order.index("b") < order.index("m"), "the other track also precedes the simulation")
ok(len(f.into("m")) == 2, "both tracks arrive at the simulation")
ok(f.target_of("m").id == "t", "the simulation traces back to the target")

# the kinds
ok(cards.link_refused("target", "target", "hopemd", "structures") != "",
   "a target cannot be simulated on its own")
ok(cards.link_refused("pipelines", "sequences", "hopemd", "structures") != "",
   "sequences without structures cannot be simulated")
ok(cards.link_refused("bindcraft", "complexes", "hopemd", "structures") == "",
   "a designed complex can be simulated")
ok(cards.link_refused("bindcraft", "complexes", "adcp", "sequences") != "",
   "a complex is not a list of peptides to dock")

# the length rule, which is the one refusal about a number
short, long_ = {"binder_max": 24}, {"binder_max": 100}
ok(cards.link_refused("bindcraft", "sequences", "adcp", "sequences", short) == "",
   "a short design may be docked")
why = cards.link_refused("bindcraft", "sequences", "adcp", "sequences", long_)
ok(why != "" and "30" in why, "a 100-residue design may not be docked: %s" % why[:70])
ok(flow.Flow.from_json(built(binder=(70, 100), links=("t>p", "t>b", "t>a", "b>a", "b>m", "a>m")
                             ).dumps()).check() != [], "and the whole flow is refused for it")
ok(built(binder=(18, 24), links=("t>p", "t>b", "t>a", "b>a", "b>m", "a>m")).check() == [],
   "while the same flow with short binders is sound")

# what is missing
ok(any("target" in b for b in flow.Flow.from_json(
    {"name": "x", "nodes": [{"id": "m", "card": "hopemd"}], "edges": []}).check()),
   "a flow with no target is refused")
ok(any("wait on each other" in b for b in flow.Flow.from_json(
    {"name": "x", "nodes": [{"id": "t", "card": "target", "settings": {
         "source": "rcsb", "pdb_id": "5O45", "hotspots": "54", "binder_min": 8, "binder_max": 20}},
      {"id": "a", "card": "adcp"}, {"id": "p", "card": "pipelines"}],
     "edges": [{"from": "t", "fromPort": "target", "to": "a", "toPort": "target"},
               {"from": "a", "fromPort": "poses", "to": "p", "toPort": "target"},
               {"from": "p", "fromPort": "sequences", "to": "a", "toPort": "sequences"}]}).check()),
   "a cycle is named rather than hung on")
bad = flow.Flow.from_json({"name": "x", "nodes": [
    {"id": "t", "card": "target", "settings": {"source": "rcsb", "pdb_id": "", "hotspots": ""}},
    {"id": "a", "card": "adcp"}], "edges": [
    {"from": "t", "fromPort": "target", "to": "a", "toPort": "target"}]}).check()
ok(any("PDB id" in b for b in bad) and any("hotspots" in b for b in bad),
   "an empty target says which fields are missing")
ok(any("nothing arriving at" in b for b in bad), "and that the docking has no peptides")

# a port that takes one thing, given several
two = flow.Flow.from_json(built().as_json())
two.edges.append(flow.Edge("b", "complexes", "m", "structures"))
ok(any("drawn twice" in b for b in two.check()), "the same link drawn twice is refused")
twice = flow.Flow.from_json(built().as_json())
twice.nodes.append(flow.Node("t2", "target", dict(twice.node("t").settings)))
twice.edges.append(flow.Edge("t2", "target", "a", "target"))
bad2 = twice.check()
ok(any("takes one thing at" in b for b in bad2) or any("more than one target" in b for b in bad2),
   "two things arriving where one is taken is refused: %s" % bad2[:1])
ok(cards.link_refused("bindcraft", "sequences", "adcp", "sequences", {}) != "",
   "a link that needs the binder length is refused when the flow gives none")

# it survives the round trip
again = flow.Flow.from_json(built().dumps())
ok(again.as_json() == built().as_json(), "a flow written and read back is the same flow")
ok(json.loads(json.dumps(cards.catalogue()))["cards"][0]["key"] == "target",
   "the catalogue is JSON the canvas can read")

print("\n%s" % ("ALL PASSED" if not fails else "%d FAILED" % len(fails)))
sys.exit(1 if fails else 0)
