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

import json
import os
import time

from . import adapters, cards, drivers, queue, state as st
from .flow import Flow


def folder_for(flow, runs_root):
    """Where this flow's own folder goes: its name under the root, never over an existing run."""
    root = os.path.abspath(os.path.expandvars(os.path.expanduser(str(runs_root))))
    where = os.path.join(root, flow.name)
    if os.path.exists(where):
        where = "%s_%s" % (where, time.strftime("%Y%m%d-%H%M%S"))
    return where


def write_out(flow, where, settled=None):
    """Lay the flow's folder out. Nothing of a card's own run is put here: the tools do that."""
    os.makedirs(where, exist_ok=True)
    for part in ("logs", "inputs", "claims", "state"):
        os.makedirs(os.path.join(where, part), exist_ok=True)
    doc = flow.as_json()
    if settled:
        doc["settled"] = dict(settled)
    with open(os.path.join(where, "flow.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
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

    where = folder_for(flow, runs_root)
    # What a step job needs and nobody changes afterwards goes in with the drawing, written once.
    # Keeping it out of the record is what lets the record be one small file per card, which is
    # what stops two step jobs writing over each other.
    settled = {"python": str(python), "package_root": str(package_root),
               "account": account, "partition": partition}
    write_out(flow, where, settled)
    record = st.State.read(where)
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
    # Through set(), not by reaching into the card: only what set() is told about is written, so a
    # change made by hand would be kept in this process and lost everywhere else.
    was = record.state_of(node_id)
    record.set(node_id, step=jid, state=st.READY if was == st.WAITING else None,
               note="" if was == st.WAITING else None)
    return jid


def _queue_seal(where, node_id, record, after, say=print):
    """A job that reads the flow's own state once the last card's work has ended, and writes it.

    It runs `status`, which is the one thing that brings a record up to date from the queue. Not
    worth failing the card for if it cannot be queued: the record is then as it always was, true
    the moment anybody asks.
    """
    script = os.path.join(where, "logs", "seal-%s.sbatch" % node_id)
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(queue.step_script(where, node_id,
                                   record.data.get("python") or "python3",
                                   record.data.get("package_root") or "",
                                   record.data.get("account") or "",
                                   record.data.get("partition") or "")
                 .replace("hope_flow.cli step", "hope_flow.cli status")
                 .replace(" %s\n" % _q(node_id), "\n")
                 .replace("--job-name=flow-%s" % node_id, "--job-name=flow-%s-seal" % node_id))
    os.chmod(script, 0o755)
    try:
        jid = queue.submit(script, where, dependency=after, name="flow-%s-seal" % node_id)
        # Written down so that anything waiting for the flow to be finished with can see it. A job
        # nobody records is a job nobody can wait for.
        record.set(node_id, seal=jid)
        record.write()
        say("%s will write down how it ended" % jid)
    except RuntimeError as why:
        say("the sealing job was refused (%s); the record is true whenever it is next read" % why)


def _q(text):
    import shlex
    return shlex.quote(str(text))


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
    flow = _flow_in(where)
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
    # Nothing comes after this card, so nothing will ever look at it again and mark it finished:
    # a card's state is brought up to date by the card after it. Left alone, a flow that ended
    # while nobody was watching reads as still queued for ever. One small job behind its tool
    # settles it, which is what somebody opening the launcher a week later will read.
    if jobs and not flow.out_of(node_id):
        _queue_seal(where, node_id, record, after, say)

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


def plan(flow, runs_root, account="", partition=""):
    """What this flow would do, worked out without doing any of it.

    A person pressing Launch is committing a cluster allocation, sometimes for days, and until now
    they were doing it blind. This says what will be queued, in what order, where it will land and
    what drives the cost, so the press is a decision rather than a leap.

    The numbers here are counts and arithmetic, not predictions. An hour figure would have to come
    from a built system, which does not exist until the flow has run; inventing one would be worse
    than giving none, so what is given is what is known: how many of what.
    """
    where = folder_for(flow, runs_root)
    rows, notes = [], []
    target = next((n for n in flow.nodes if n.card == "target"), None)
    settings = target.settings if target else {}

    for node in flow.order():
        card = node.kind
        waits = [flow.node(u).kind.name for u in flow.upstream(node.id)]
        row = {"id": node.id, "card": node.card, "name": card.name,
               "waits_for": waits, "queues": "", "lands_in": "", "scale": ""}
        if node.card == "target":
            row["queues"] = "nothing: fetched here, before anything is queued"
            row["lands_in"] = os.path.join(where, "inputs")
            row["scale"] = _target_line(settings)
        else:
            row["lands_in"] = os.path.join(
                os.path.abspath(os.path.expandvars(os.path.expanduser(
                    node.settings.get("runs") or drivers.RUNS.get(node.card, "")))),
                "%s_%s" % (flow.name, node.id))
            row["queues"], row["scale"] = _card_scale(node, settings)
        rows.append(row)
        notes.extend(_card_notes(node, settings, flow))

    return {"name": flow.name, "folder": where, "cards": rows, "notes": notes,
            "account": account, "partition": partition,
            "problems": flow.check()}


def _target_line(s):
    where = ("PDB " + (s.get("pdb_id") or "?")) if (s.get("source") or "rcsb") == "rcsb" \
        else os.path.basename(s.get("path") or "?")
    return "%s, chains %s, hotspots %s" % (where, s.get("chains") or "all",
                                           s.get("hotspots") or "none")


def _card_scale(node, target_settings):
    """(what this card queues, the numbers that decide what it costs)."""
    s = node.settings
    if node.card == "pipelines":
        return ("one design job, and a co-folding job behind it when it is asked for",
                "%s%s" % (s.get("pipeline") or "the default pipeline",
                          ", %s rounds" % s["rounds"] if s.get("rounds") else ""))
    if node.card == "bindcraft":
        return ("one campaign on %s, up to %s" % (s.get("gpu") or "auto",
                                                  s.get("walltime") or "24:00:00"),
                "until %s designs pass, binders of %s-%s residues"
                % (s.get("designs") or "?", target_settings.get("binder_min"),
                   target_settings.get("binder_max")))
    if node.card == "adcp":
        return ("three jobs: prepare, dock as an array over the peptides, then gather",
                "%s replicas a peptide, %s poses kept%s"
                % (s.get("replicas") or 50, s.get("poses") or 10,
                   ", then MM-GBSA" if s.get("mmgbsa", True) else ""))
    if node.card == "hopemd":
        runs = int(_int(s.get("top_n"), 10))
        reps = int(_int(s.get("replicates"), 3))
        ns = _int(s.get("length_ns"), 100)
        return ("up to %d run%s per track, each of about five jobs"
                % (runs, "" if runs == 1 else "s"),
                "%d x %d replicate%s x %g ns = %g ns a track, on %s"
                % (runs, reps, "" if reps == 1 else "s", ns, runs * reps * ns,
                   s.get("engine") or "amber"))
    return ("one job", "")


def _int(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _card_notes(node, target_settings, flow):
    """What a person should know about this card before pressing Launch."""
    out = []
    if node.card == "hopemd":
        runs = int(_int(node.settings.get("top_n"), 10))
        reps = int(_int(node.settings.get("replicates"), 3))
        # The best of each track, not the best overall: two tracks arriving means twice the runs,
        # which is the single easiest way for a flow to cost twice what was intended.
        tracks = max(1, len(flow.into(node.id)))
        total = runs * tracks * reps * _int(node.settings.get("length_ns"), 100)
        if tracks > 1:
            out.append("%d tracks arrive at the simulation and the best %d of each is taken, so up "
                       "to %d runs rather than %d." % (tracks, runs, runs * tracks, runs))
        if total >= 3000:
            out.append("That is %g ns in all. A nanosecond of a middling system is minutes on one "
                       "card, so this is a long commitment: check the number before starting it."
                       % total)
    if node.card == "bindcraft":
        longest = _int(target_settings.get("binder_max"), 0)
        if longest and longest > cards.DOCKABLE_MAX_LENGTH and \
                any(e.dst_port == "sequences" for e in flow.out_of(node.id)):
            out.append("Designs of up to %g residues cannot be docked; that link is refused."
                       % longest)
    return out


def _step_pending(record, node_id):
    """The step job watching this card, if one is still in the queue."""
    jid = record.card(node_id).get("step")
    if not jid:
        return ""
    state = queue.states([jid]).get(str(jid), "")
    return str(jid) if state.startswith(("PENDING", "RUNNING", "CONFIGURING", "REQUEUED",
                                         "SUSPENDED")) else ""


def _flow_in(where):
    """The flow in this folder, or a sentence saying why there is not one.

    A path that is not a flow is the ordinary mistake - a run folder of one of the tools, or a
    folder that has been tidied away - and it deserves an answer rather than a traceback, because
    the answer reaches a person through the launcher's page.
    """
    path = os.path.join(str(where), "flow.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return Flow.from_json(fh.read())
    except FileNotFoundError:
        raise ValueError("there is no flow in %s: it holds no flow.json" % where)
    except (ValueError, OSError) as why:
        raise ValueError("the flow in %s could not be read: %s" % (where, why))


def resume(where, say=print):
    """Carry on a flow that stopped, from the first card that has not finished.

    A flow stops for reasons that have nothing to do with the flow: a node failed under a job, a
    queue was full, an allocation ran out overnight. What has finished is left alone - its runs
    are on disk and cost what they cost - and everything from the first unfinished card is queued
    again. A card that failed has its claim given back, so it is tried rather than skipped.
    """
    where = os.path.abspath(str(where))
    flow = _flow_in(where)
    record = st.State.read(where)
    refresh(flow, record)

    again = []
    for node in flow.nodes:
        state = record.state_of(node.id)
        if state == st.DONE:
            continue
        if state in (st.QUEUED, st.RUNNING):
            # Still in the queue. Starting it again would be a second run of the same work.
            say("%s is still %s; leaving it" % (node.id, state))
            continue
        # A card that has not had its turn yet may already have a step job waiting for the card
        # before it; pressing Carry on twice is an ordinary thing to do and should not leave two
        # behind. A card that failed or was stopped is different: its step job has already run, so
        # it needs a new one however the old one ended.
        if state in (st.WAITING, st.READY):
            waiting_already = _step_pending(record, node.id)
            if waiting_already:
                say("%s is already waiting as job %s" % (node.id, waiting_already))
                continue
        st.unclaim(where, node.id)
        record.set(node.id, state=st.WAITING, note="")
        again.append(node.id)
    if not again:
        record.write()
        say("nothing to carry on: every card has finished or is already queued")
        return where, {}

    queued = {}
    for node in flow.nodes:
        if node.id not in again:
            continue
        if not all(record.finished(u) for u in flow.upstream(node.id)):
            continue
        if node.card == "target":
            rundir, _ = drivers.submit(node, flow, {}, where, record, say=say)
            record.set(node.id, state=st.DONE, rundir=rundir, jobs=[], note="")
            continue
        queued[node.id] = _queue_step(where, node.id, record, dependency="")
        say("%s queued again as job %s" % (node.id, queued[node.id]))
    record.write()
    return where, queued
