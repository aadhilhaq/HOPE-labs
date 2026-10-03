"""Queueing a flow, and the few minutes of work that happen at each card.

A flow is submitted once and then runs itself. Submitting queues a step job for every card that
nothing arrives at. Each step job, when the cards before it have finished, turns what they left
into what this card needs, starts the card's tool, and queues the next cards' step jobs behind
the tool it just started. The chain unrolls as it goes, so a dependency is always on a job id
that already exists.

A card with two tracks arriving at it is woken by both. The first to arrive finds the other
unfinished and goes back to sleep; the last does the work. If both arrive at once, `claim()`
settles it. Waking a card twice is therefore ordinary rather than exceptional, and costs a
minute of a short queue.
"""
from __future__ import annotations

import os
import time

from . import adapters, drivers, queue, state as st
from .flow import Flow


def folder_for(flow, runs_root):
    """Where this flow's own folder goes: its name under the root, never over an existing run."""
    root = os.path.abspath(os.path.expandvars(os.path.expanduser(str(runs_root))))
    where = os.path.join(root, flow.name)
    if os.path.exists(where):
        where = "%s_%s" % (where, time.strftime("%Y%m%d-%H%M%S"))
    return where


def write_out(flow, where):
    """Lay the flow's folder out. Nothing of a card's own run is put here: the tools do that."""
    os.makedirs(where, exist_ok=True)
    for part in ("logs", "inputs", "claims"):
        os.makedirs(os.path.join(where, part), exist_ok=True)
    with open(os.path.join(where, "flow.json"), "w", encoding="utf-8") as fh:
        fh.write(flow.dumps())
    return where


def submit(flow, runs_root, python, package_root, account="", partition="", say=print):
    """Queue the flow. Returns (its folder, {card id: the step job watching it}).

    Only the cards nothing arrives at are queued here. The rest are queued by the cards before
    them, when there is something for them to wait on.
    """
    bad = flow.check()
    if bad:
        raise ValueError("this flow cannot be queued:\n  " + "\n  ".join(bad))
    if not queue.available():
        raise RuntimeError("there is no sbatch here: a flow is queued from a login node")

    where = write_out(flow, folder_for(flow, runs_root))
    record = st.State.read(where)
    record.data["flow"] = flow.name
    record.data["python"] = str(python)
    record.data["package_root"] = str(package_root)
    record.data["account"] = account
    record.data["partition"] = partition
    for node in flow.nodes:
        record.set(node.id, state=st.WAITING)
    record.write()

    # The target is fetched here, on the login node, rather than in a job. A compute node on
    # this cluster has no way out to the internet, so an RCSB id could not be fetched from one;
    # and doing it now means a wrong id is refused while the person is still looking at the page
    # instead of quietly, in a queue, several minutes later.
    for node in flow.nodes:
        if node.card != "target":
            continue
        rundir, _ = drivers.submit(node, flow, {}, where, record, say=say)
        record.set(node.id, state=st.DONE, rundir=rundir, jobs=[], note="")
    record.write()

    queued = {}
    for node in flow.nodes:
        if record.state_of(node.id) != st.WAITING:
            continue
        if all(record.finished(u) for u in flow.upstream(node.id)):
            queued[node.id] = _queue_step(where, node.id, record, dependency="")
    record.write()
    return where, queued


def _queue_step(where, node_id, record, dependency=""):
    """Write and queue one card's step job."""
    script = os.path.join(where, "logs", "step-%s.sbatch" % node_id)
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(queue.step_script(where, node_id,
                                   record.data.get("python") or "python3",
                                   record.data.get("package_root") or "",
                                   record.data.get("account") or "",
                                   record.data.get("partition") or ""))
    os.chmod(script, 0o755)
    jid = queue.submit(script, where, dependency=dependency, name="flow-%s" % node_id)
    card = record.card(node_id)
    card["step"] = jid
    if card["state"] == st.WAITING:
        record.set(node_id, state=st.READY, note="")
    return jid


def refresh(flow, record):
    """Bring every card's state up to date from Slurm. The only thing that reads the queue."""
    changed = False
    for node in flow.nodes:
        card = record.card(node.id)
        if card["state"] in st.ENDED or not card.get("jobs"):
            continue
        finished, bad = queue.all_done(card["jobs"])
        if bad:
            record.set(node.id, state=st.FAILED,
                       note="%s ended as %s" % (bad[0][0], bad[0][1].lower()))
            changed = True
        elif finished:
            record.set(node.id, state=st.DONE, note="")
            changed = True
        elif card["state"] != st.RUNNING:
            record.set(node.id, state=st.RUNNING)
            changed = True
    return changed


def step(where, node_id, say=print):
    """One card's turn: wait, adapt, submit, and wake the cards after it.

    Returns a short word saying what it did, which is what the job's log is for.
    """
    where = os.path.abspath(str(where))
    with open(os.path.join(where, "flow.json"), encoding="utf-8") as fh:
        flow = Flow.from_json(fh.read())
    record = st.State.read(where)
    node = flow.node(node_id)
    if node is None:
        say("there is no card called %s in this flow" % node_id)
        return "unknown"

    refresh(flow, record)

    # This card has already had its turn. A step job can run twice: Slurm requeues one when a
    # node fails under it, and a card with two tracks arriving is woken by both. Starting the
    # tool again would be a second run of the same work, charged a second time, so the state
    # this card is already in is the first thing read.
    already = record.state_of(node_id)
    if already in (st.QUEUED, st.RUNNING, st.DONE):
        say("this card is already %s" % already)
        return already
    if already == st.STOPPED:
        say("this card was stopped")
        return "stopped"

    # Something before this card went wrong, so there is nothing to carry forward. Slurm will
    # have cancelled this job's own dependency in most cases; this is the case where it did not.
    for up in flow.upstream(node_id):
        if record.state_of(up) in (st.FAILED, st.STOPPED):
            record.set(node_id, state=st.STOPPED, note="%s did not finish" % up)
            record.write()
            say("%s did not finish, so nothing is queued here" % up)
            return "stopped"
    waiting = [u for u in flow.upstream(node_id) if not record.finished(u)]
    if waiting:
        record.write()
        say("still waiting for %s" % ", ".join(waiting))
        return "waiting"

    if not st.claim(where, node_id):
        say("another job is already starting this card")
        return "claimed"

    try:
        carried = {}
        for edge in flow.into(node_id):
            port = flow.node(edge.src)
            got = adapters.carry(flow, record, edge, where)
            carried.setdefault(edge.dst_port, []).append(got)
            say("from %s: %s" % (port.kind.name if port.kind else edge.src, got.get("what", "")))

        empty = [p for p, got in carried.items()
                 if all(not g.get("count", 1) for g in got)]
        if empty:
            # Nothing came out of the track before this one. That is a result, not a fault: a
            # design run can pass nothing, and the flow should say so rather than queue a card
            # with an empty input and let the tool refuse it a minute later.
            record.set(node_id, state=st.STOPPED,
                       note="nothing arrived at %s" % ", ".join(sorted(empty)))
            record.write()
            say("nothing arrived: this track ends here")
            return "empty"

        rundir, jobs = drivers.submit(node, flow, carried, where, record, say=say)
        record.set(node_id, state=st.QUEUED, rundir=rundir, jobs=jobs, note="")
        record.write()
        say("%s queued as %s" % (node.kind.name, ", ".join(jobs) or "nothing"))
    except Exception as why:                                    # noqa: BLE001
        record.set(node_id, state=st.FAILED, note=str(why)[:400])
        record.write()
        st.unclaim(where, node_id)
        say("this card failed: %s" % why)
        raise

    after = "afterok:" + ":".join(jobs) if jobs else ""
    for edge in flow.out_of(node_id):
        if record.state_of(edge.dst) in (st.QUEUED, st.RUNNING, st.DONE):
            continue
        try:
            _queue_step(where, edge.dst, record, dependency=after)
            say("%s will wake when this finishes" % edge.dst)
        except RuntimeError as why:
            record.set(edge.dst, state=st.FAILED, note=str(why)[:400])
            say("could not queue %s: %s" % (edge.dst, why))
    record.write()
    return "queued"
