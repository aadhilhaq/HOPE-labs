#!/usr/bin/env python3
"""The chain: waiting, claiming, carrying, and what happens when a card fails or leaves nothing.

No tool is started and nothing is queued. The cards are stubs and sbatch is a counter, because
what is being tested is the order things happen in, which is where a flow can go wrong in ways
no single tool would show.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hope_flow import cards, adapters, drivers, queue, run, state as st                   # noqa: E402
from hope_flow.flow import Flow                                                    # noqa: E402

fails = []


def ok(cond, what):
    print("%s %s" % ("ok  " if cond else "FAIL", what))
    if not cond:
        fails.append(what)


# --- the cluster, as far as this test is concerned -------------------------------------------
QUEUED = []          # (script, dependency)
JOB_STATE = {}       # job id -> what Slurm would say


def fake_submit(script, cwd, dependency="", name=""):
    QUEUED.append((os.path.basename(str(script)), dependency))
    jid = str(9000 + len(QUEUED))
    JOB_STATE[jid] = "PENDING"
    return jid


def fake_states(ids):
    return {str(j): JOB_STATE.get(str(j), "") for j in ids if str(j) in JOB_STATE}


queue.submit = fake_submit
queue.states = fake_states
queue.available = lambda: True


def fake_all_done(ids):
    seen = fake_states(ids)
    bad, pending = [], False
    for j in (str(i) for i in ids):
        s = seen.get(j, "")
        if not s or s in ("PENDING", "RUNNING"):
            pending = True
        elif s != "COMPLETED":
            bad.append((j, s))
    return (not pending, bad)


queue.all_done = fake_all_done

STARTED = []


def tool_driver(node, flow, carried, flow_dir, record, say=print):
    """A card that queues one job, and records what arrived so the test can read it."""
    STARTED.append((node.id, sorted(carried)))
    jid = fake_submit("tool-%s.sbatch" % node.id, flow_dir)
    return os.path.join(flow_dir, node.id), [jid]


def empty_driver(node, flow, carried, flow_dir, record, say=print):
    return os.path.join(flow_dir, node.id), []


def angry_driver(node, flow, carried, flow_dir, record, say=print):
    raise drivers.NotWired("this tool was not installed")


def carry_anything(flow, record, edge, flow_dir):
    """Carries one thing, unless the card before it was told to leave nothing."""
    n = len(record.card(edge.src).get("left", [1]))
    return {"kind": "sequences", "count": n, "what": "%d thing(s)" % n}


for key in ("pipelines", "bindcraft", "adcp", "hopemd", "aptamer"):
    drivers.BY_CARD[key] = tool_driver
for src in ("pipelines", "bindcraft", "adcp", "aptamer"):
    for port in ("sequences", "complexes", "poses"):
        for dst in ("adcp", "hopemd"):
            adapters.BY_JUNCTION[(src, port, dst)] = carry_anything


def a_flow():
    nodes = [{"id": "t", "card": "target", "settings": {
                  "source": "file", "path": __file__, "hotspots": "54,56",
                  "binder_min": 8, "binder_max": 20}},
             {"id": "p", "card": "pipelines", "settings": {"pipeline": cards.PIPELINE_LABELS[0]}}, {"id": "b", "card": "bindcraft", "settings": {"designs": 10}},
             {"id": "a", "card": "adcp"}, {"id": "m", "card": "hopemd", "settings": {"top_n": 10, "engine": "amber", "length_ns": 50}}]
    edges = [("t", "target", "p", "target"), ("t", "target", "b", "target"),
             ("t", "target", "a", "target"), ("p", "sequences", "a", "sequences"),
             ("b", "complexes", "m", "structures"), ("a", "poses", "m", "structures")]
    return Flow.from_json({"name": "chain", "nodes": nodes,
                           "edges": [{"from": e[0], "fromPort": e[1], "to": e[2], "toPort": e[3]}
                                     for e in edges]})


work = tempfile.mkdtemp(prefix="flowrun_", dir="/scratch/group/sflab/hopemd_qa/wt_flow")
try:
    flow = a_flow()
    ok(flow.check() == [], "the test flow is sound: %s" % (flow.check() or "yes"))
    where, queued = run.submit(flow, work, sys.executable, "/nowhere", say=lambda *a: None)
    record = st.State.read(where)
    ok(record.state_of("t") == st.DONE, "the target is done the moment the flow is queued")
    ok(sorted(queued) == ["b", "p"],
       "the two cards with nothing else to wait for are queued: %s" % sorted(queued))
    ok("a" not in queued,
       "the docking is not queued yet: it would only wake to find no peptides")
    ok(record.state_of("m") == st.WAITING, "the simulation is not queued yet")

    # the docking waits for the designs, although the target already reached it
    run.step(where, "a", say=lambda *a: None)
    ok(st.State.read(where).state_of("a") in (st.READY, st.WAITING),
       "the docking waits: its peptides have not been designed yet")
    ok(not [s for s in STARTED if s[0] == "a"], "and nothing was started for it")

    # the designs finish
    for nid in ("p", "b"):
        rec = st.State.read(where)
        run.step(where, nid, say=lambda *a: None)
        rec = st.State.read(where)
        ok(rec.state_of(nid) == st.QUEUED, "%s was queued" % nid)
        for j in rec.card(nid)["jobs"]:
            JOB_STATE[j] = "COMPLETED"

    run.step(where, "a", say=lambda *a: None)
    rec = st.State.read(where)
    ok(rec.state_of("p") == st.DONE, "the card before it is marked done from the queue")
    ok(rec.state_of("a") == st.QUEUED, "the docking runs once its peptides exist")
    ok(("a", ["sequences", "target"]) in STARTED, "and it was given both its inputs: %s" % STARTED)

    # the simulation waits for both tracks
    run.step(where, "m", say=lambda *a: None)
    ok(st.State.read(where).state_of("m") != st.QUEUED,
       "the simulation waits while the docking is still going")
    for j in st.State.read(where).card("a")["jobs"]:
        JOB_STATE[j] = "COMPLETED"
    run.step(where, "m", say=lambda *a: None)
    rec = st.State.read(where)
    ok(rec.state_of("m") == st.QUEUED, "and runs when both tracks have arrived")
    ok(len([s for s in STARTED if s[0] == "m"]) == 1, "the simulation was started once")

    # being woken twice is ordinary, and must not cost a second run of the tool
    st.unclaim(where, "m")
    ok(run.step(where, "m", say=lambda *a: None) in (st.QUEUED, st.RUNNING, st.DONE),
       "waking a card that has had its turn says which state it is already in")
    ok(len([s for s in STARTED if s[0] == "m"]) == 1,
       "and does not start its tool a second time")
finally:
    shutil.rmtree(work, ignore_errors=True)

# --- a track that leaves nothing, and a card that fails ---------------------------------------
work = tempfile.mkdtemp(prefix="flowrun_", dir="/scratch/group/sflab/hopemd_qa/wt_flow")
try:
    flow = a_flow()
    where, _ = run.submit(flow, work, sys.executable, "/nowhere", say=lambda *a: None)
    run.step(where, "p", say=lambda *a: None)
    rec = st.State.read(where)
    for j in rec.card("p")["jobs"]:
        JOB_STATE[j] = "COMPLETED"
    rec.card("p")["left"] = []                       # the design run passed nothing
    rec.write()
    run.step(where, "a", say=lambda *a: None)
    rec = st.State.read(where)
    ok(rec.state_of("a") == st.STOPPED, "a track that designed nothing ends quietly")
    ok("nothing arrived" in rec.card("a")["note"], "and says so: %s" % rec.card("a")["note"])

    drivers.BY_CARD["bindcraft"] = angry_driver
    try:
        run.step(where, "b", say=lambda *a: None)
    except Exception:
        pass
    rec = st.State.read(where)
    ok(rec.state_of("b") == st.FAILED, "a card whose tool will not start is marked failed")
    ok("not installed" in rec.card("b")["note"], "with the reason: %s" % rec.card("b")["note"])
    run.step(where, "m", say=lambda *a: None)
    ok(st.State.read(where).state_of("m") == st.STOPPED,
       "and the card after it stops rather than waiting for ever")
    drivers.BY_CARD["bindcraft"] = tool_driver
finally:
    shutil.rmtree(work, ignore_errors=True)

print("\n%s" % ("ALL PASSED" if not fails else "%d FAILED" % len(fails)))
sys.exit(1 if fails else 0)
