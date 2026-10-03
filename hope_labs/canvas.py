"""What the canvas asks the launcher for: the cards, the checking, and the flow to start from.

The canvas draws; it decides nothing. Which links are legal and what is wrong with a flow are
answered here, out of cards.py and flow.py, which are the same two files the runner reads on the
cluster (hope_labs/cards.py and hope_labs/flow.py are kept byte identical to HOPE-flow's). So a
flow that draws clean on the laptop is a flow the cluster agrees with, and a refusal reads the
same in both places because there is only one wording of it.

The refusal table is the part worth explaining. A link is refused while it is being dragged, and
one round trip per candidate socket would make the drag crawl, so the whole table of what may
reach what is worked out here and handed over with the check: forty-odd sentences, recomputed
whenever anything on the canvas changes. The binder length lives in the target's settings and the
length refusal depends on it, which is why the table is a function of the flow rather than a
constant served once.
"""
from __future__ import annotations

from hope_flow import cards, flow

#: What the Launch button gets until the part of HOPE-flow that queues a flow is installed. It is
#: a sentence rather than a code because it reaches the person as it stands.
RUNNER_MISSING = "the runner is not installed yet"


def catalogue():
    """Every card, their sockets and their settings, for the palette and the panel."""
    return cards.catalogue()


def target_settings(doc):
    """What the target card was filled in with, which is what the length refusal is measured by.

    A flow with no target, or with more than one, is refused by check() in its own words; this
    takes the first so that the sockets still say something useful while one is being drawn.
    """
    for node in (doc or {}).get("nodes") or []:
        if isinstance(node, dict) and node.get("card") == "target":
            got = node.get("settings")
            return dict(got) if isinstance(got, dict) else {}
    return {}


def refusals(settings=None):
    """{"card:port>card:port": why it cannot be drawn, or ""} for every pair of sockets."""
    table = {}
    for out_card in cards.CARDS:
        for out_port in out_card.outputs:
            for in_card in cards.CARDS:
                for in_port in in_card.inputs:
                    table["%s:%s>%s:%s" % (out_card.key, out_port.key, in_card.key, in_port.key)] = \
                        cards.link_refused(out_card.key, out_port.key, in_card.key, in_port.key,
                                           settings)
    return table


def check(doc):
    """What is wrong with this flow, and what may be linked to what as it now stands."""
    problems = flow.Flow.from_json(doc or {}).check()
    return {"problems": problems, "refusals": refusals(target_settings(doc))}


def example():
    """The flow the lab wants: one target, two design tracks, docking, one batch of simulations.

    It is a whole flow rather than a shape to fill in - a real PDB id and real hotspots - because
    a person starting from an example is finding out what the canvas does, and a flow that will
    not launch until six boxes are filled teaches them nothing. The settings a flow will not start
    without are filled in with modest numbers rather than ambitious ones, since this is the flow
    somebody will press Launch on first. The peptides go to the docking and
    the designs do not: BindCraft2's binders are as long as the target card asks for, which is
    longer than the docking takes, and the designs arrive placed on the target already.
    """
    doc = flow.Flow(name="example", nodes=[
        flow.Node("target", "target", {
            "source": "rcsb", "pdb_id": "5O45", "chains": "A", "path": "",
            "hotspots": "54,56,66-70", "binder_min": 70, "binder_max": 100}, at=(16, 146)),
        flow.Node("pipelines", "pipelines", {"pipeline": cards.PIPELINE_LABELS[0]}, at=(252, 16)),
        flow.Node("bindcraft", "bindcraft", {"designs": 10}, at=(252, 286)),
        flow.Node("adcp", "adcp", at=(488, 16)),
        # Modest on purpose: an example a person presses Launch on should not be the one that
        # commits a week of a card. The numbers are theirs to raise once they have read the plan.
        flow.Node("hopemd", "hopemd", {"top_n": 5, "engine": "amber", "length_ns": 50,
                                       "replicates": 3}, at=(724, 160)),
    ], edges=[
        flow.Edge("target", "target", "pipelines", "target"),
        flow.Edge("target", "target", "bindcraft", "target"),
        flow.Edge("target", "target", "adcp", "target"),
        flow.Edge("pipelines", "sequences", "adcp", "sequences"),
        flow.Edge("adcp", "poses", "hopemd", "structures"),
        flow.Edge("bindcraft", "complexes", "hopemd", "structures"),
    ])
    return doc.as_json()


def launch(flows, doc, runs=""):
    """Queue this flow on the cluster, through the connection the launcher already holds.

    What is checked here is checked again by the runner before anything is queued: this page is
    not the authority on whether a flow can run, and a flow can reach the cluster as a file
    without ever passing through here.
    """
    bad = flow.Flow.from_json(doc or {}).check()
    if bad:
        raise RuntimeError("this flow cannot be queued yet: " + "; ".join(bad))
    return flows.launch(doc, runs)


def plan(flows, doc, runs=""):
    """What this flow would do, worked out on the cluster, before anything is queued."""
    return flows.plan(doc, runs)
