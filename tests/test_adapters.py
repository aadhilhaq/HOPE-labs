#!/usr/bin/env python3
"""The junctions, against real run folders on Grace.

Nothing is submitted and nothing is written but the peptides files, which go to a temporary
folder. A junction that cannot be checked against a real run of its tool is reported as skipped
rather than passed, because the whole value of these is that they match what the tools leave.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hope_flow import adapters                                            # noqa: E402
from hope_flow.flow import Flow                                           # noqa: E402
from hope_flow import state as st                                         # noqa: E402

fails, skipped = [], []


def ok(cond, what):
    print("%s %s" % ("ok  " if cond else "FAIL", what))
    if not cond:
        fails.append(what)


def skip(what, why):
    print("skip %s (%s)" % (what, why))
    skipped.append(what)


def first_dir(*candidates):
    return next((c for c in candidates if os.path.isdir(c)), "")


#: Real runs on this cluster. Each junction is checked against one, or reported as skipped.
PIPELINES_RUN = first_dir(
    "/scratch/group/sflab/HOPE-pipelines/pipelines/hope-dimer-loop/runs/CLas_SPase1_Sept8",
    "/scratch/group/sflab/HOPE-pipelines/pipelines/hope-dimer-loop/runs/BamA_Aadhil2/P_ar_NamA_Adl_2")
ADCP_RUN = first_dir("/scratch/user/aadhil.haq/adcp_runs/6B88_HOPE_peptides_20260922_154712")
BINDCRAFT_RUN = first_dir("/scratch/group/sflab/bindcraft_runs/_smoketest/pdl1")

WORK = tempfile.mkdtemp(prefix="flowadapt_", dir="/scratch/group/sflab/hopemd_qa/wt_flow")


def a_flow(cards_and_edges, binder=(70, 100)):
    nodes, edges = cards_and_edges
    nodes = [{"id": "t", "card": "target", "settings": {
        "source": "rcsb", "pdb_id": "5O45", "hotspots": "54,56",
        "binder_min": binder[0], "binder_max": binder[1]}}] + nodes
    return Flow.from_json({"name": "junctions", "nodes": nodes,
                           "edges": [{"from": e[0], "fromPort": e[1], "to": e[2], "toPort": e[3]}
                                     for e in edges]})


def carried(flow, rundirs, edge_at):
    record = st.State.read(WORK)
    for nid, where in rundirs.items():
        record.set(nid, state=st.DONE, rundir=where)
    e = flow.edges[edge_at]
    return adapters.carry(flow, record, e, WORK)


# --- the pipelines' peptides into the docking --------------------------------------------------
if not PIPELINES_RUN:
    skip("pipelines to docking", "no finished design run on this cluster")
else:
    flow = a_flow(([{"id": "p", "card": "pipelines"}, {"id": "a", "card": "adcp"}],
                   [("t", "target", "p", "target"), ("t", "target", "a", "target"),
                    ("p", "sequences", "a", "sequences")]))
    got = carried(flow, {"p": PIPELINES_RUN}, 2)
    ok(got["kind"] == "sequences", "the designs are carried as sequences")
    ok(got["count"] > 0, "it read %d peptide(s): %s" % (got["count"], got["what"][:90]))
    text = open(got["path"], encoding="utf-8").read().strip().splitlines()
    ok(len(text) == got["count"], "the peptides file has a line for each")
    ok(all(":" in line for line in text), "each line is the named form the docking cannot misread")
    seqs = [line.split(":", 1)[1].strip() for line in text]
    ok(all(5 <= len(s) <= 30 for s in seqs),
       "every sequence is within what the docking takes: %s" % sorted(set(len(s) for s in seqs)))
    ok(all(set(s) <= adapters.STANDARD for s in seqs), "and uses only residues it has rotamers for")
    ok(len(set(seqs)) == len(seqs), "no sequence is repeated, which the docking refuses a run for")
    print("     first line: %s" % (text[0] if text else "none"))

# --- the docked poses into the simulation ------------------------------------------------------
if not ADCP_RUN:
    skip("docking to simulation", "no finished docking run on this cluster")
else:
    flow = a_flow(([{"id": "a", "card": "adcp"}, {"id": "m", "card": "hopemd"}],
                   [("t", "target", "a", "target"), ("a", "poses", "m", "structures")]))
    got = carried(flow, {"a": ADCP_RUN}, 1)
    ok(got["kind"] == "poses" and got["source_kind"] == "adcp",
       "the poses are carried as the simulation's own docking source")
    ok(got["count"] > 0, "it found %d pose(s): %s" % (got["count"], got["what"][:80]))
    names = [s["peptide"] for s in got["selections"]]
    on_disk = set(os.listdir(os.path.join(ADCP_RUN, "docking")))
    ok(set(names) <= on_disk, "every peptide is named exactly as its folder is")
    ok(all(n == n.upper() or n in on_disk for n in names),
       "and is not re-cased, which would match the reduced-side-chain files instead")

# --- the designs into the simulation, and into the docking -------------------------------------
if not BINDCRAFT_RUN:
    skip("designs to simulation", "no campaign on this cluster")
else:
    flow = a_flow(([{"id": "b", "card": "bindcraft"}, {"id": "m", "card": "hopemd"}],
                   [("t", "target", "b", "target"), ("b", "complexes", "m", "structures")]))
    try:
        got = carried(flow, {"b": BINDCRAFT_RUN}, 1)
        ok(got["kind"] == "complexes", "the designs are carried as complexes")
        if got["count"]:
            one = got["designs"][0]
            ok(bool(one["receptor_chains"]) and bool(one["partner_chains"]),
               "each names its own chains: target %s, binder %s"
               % (one["receptor_chains"], one["partner_chains"]))
            ok(one["receptor_chains"] != one["partner_chains"],
               "and the two are not the same chain")
            ok(os.path.isfile(one["path"]) and not one["path"].endswith("_monomer.cif"),
               "the structure is the complex, not the binder on its own")
        else:
            skip("designs to simulation (content)",
                 "this campaign accepted nothing: %s" % got["what"][:60])
    except adapters.NotWired as why:
        skip("designs to simulation", str(why)[:80])

    # the length gate: the campaign's own request is enough to refuse the whole branch
    flow = a_flow(([{"id": "b", "card": "bindcraft"}, {"id": "a", "card": "adcp"}],
                   [("t", "target", "b", "target"), ("t", "target", "a", "target"),
                    ("b", "sequences", "a", "sequences")]), binder=(70, 100))
    try:
        carried(flow, {"b": BINDCRAFT_RUN}, 2)
        ok(False, "a campaign of 70-100mers should not reach the docking")
    except adapters.NotWired as why:
        ok("could be docked" in str(why) or "takes" in str(why),
           "a campaign too long to dock is refused, with the numbers: %s" % str(why)[:90])

shutil.rmtree(WORK, ignore_errors=True)
print("\n%d skipped" % len(skipped) if skipped else "")
print("%s" % ("ALL PASSED" if not fails else "%d FAILED" % len(fails)))
sys.exit(1 if fails else 0)
