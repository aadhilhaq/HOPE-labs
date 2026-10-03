"""The command line. The launcher calls these over the connection it already holds.

    hope-flow check   flow.json
    hope-flow submit  flow.json [--runs ROOT] [--account A] [--partition P]
    hope-flow status  FLOWDIR [--json]
    hope-flow step    FLOWDIR CARD        (what a step job runs; not for typing)
    hope-flow stop    FLOWDIR

Nothing here needs a token or a page: a flow is a file, and this queues it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, run, state as st
from .flow import Flow

#: Where a person's flows go when they do not say. Personal scratch, never a home folder.
DEFAULT_RUNS = os.path.join(os.environ.get("SCRATCH", "/tmp"), "hope_flows")

#: The Python and the checkout a step job starts from. A flow queued from one install runs on
#: that install from start to end, so an update halfway through a flow cannot change it.
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return Flow.from_json(fh.read())


def cmd_check(a):
    bad = _read(a.flow).check()
    for line in bad:
        print(line)
    print("this flow can be queued" if not bad else "%d problem%s" % (len(bad), "" if len(bad) == 1 else "s"))
    return 1 if bad else 0


def cmd_submit(a):
    flow = _read(a.flow)
    where, queued = run.submit(flow, a.runs or DEFAULT_RUNS, a.python or sys.executable,
                               a.package_root or HERE, a.account, a.partition,
                               say=lambda *m: print(" ", *m))
    print(where)
    for nid, jid in queued.items():
        print("  %s waits as job %s" % (nid, jid))
    return 0


def cmd_status(a):
    flow = _read(os.path.join(a.flowdir, "flow.json"))
    record = st.State.read(a.flowdir)
    run.refresh(flow, record)
    record.write()
    got = record.summary(flow)
    if a.json:
        print(json.dumps(got, indent=2))
        return 0
    print("%s: %s, %d of %d cards done" % (got["name"], got["state"], got["done"], got["of"]))
    for row in got["cards"]:
        note = ("  " + row["note"]) if row["note"] else ""
        print("  %-10s %-9s %s%s" % (row["id"], row["state"], row["rundir"] or "", note))
    return 0


def cmd_step(a):
    return 0 if run.step(a.flowdir, a.card) not in ("unknown",) else 2


def cmd_stop(a):
    """Cancel what this flow still has in the queue. What has finished is left alone."""
    from . import queue
    import subprocess
    flow = _read(os.path.join(a.flowdir, "flow.json"))
    record = st.State.read(a.flowdir)
    ids = []
    for node in flow.nodes:
        card = record.card(node.id)
        ids.extend(card.get("jobs") or [])
        if card.get("step"):
            ids.append(card["step"])
    alive = [j for j, s in queue.states(ids).items()
             if s.startswith(("PENDING", "RUNNING", "SUSPENDED", "CONFIGURING", "REQUEUED"))]
    if alive:
        subprocess.run(["scancel"] + alive, check=False, timeout=120)
    for node in flow.nodes:
        if record.state_of(node.id) not in st.ENDED:
            record.set(node.id, state=st.STOPPED, note="stopped by hand")
    record.write()
    print("stopped %d job%s" % (len(alive), "" if len(alive) == 1 else "s"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hope-flow", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version="HOPE-flow " + __version__)
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("check", help="what is wrong with a flow, if anything")
    c.add_argument("flow")
    c.set_defaults(fn=cmd_check)

    s = sub.add_parser("submit", help="queue a flow")
    s.add_argument("flow")
    s.add_argument("--runs", default="", help="where the flow's folder goes (default %s)" % DEFAULT_RUNS)
    s.add_argument("--account", default="", help="the allocation to charge")
    s.add_argument("--partition", default="", help="the partition the step jobs run in")
    s.add_argument("--python", default="", help="the Python the step jobs use")
    s.add_argument("--package-root", default="", help="the HOPE-flow checkout they import from")
    s.set_defaults(fn=cmd_submit)

    t = sub.add_parser("status", help="how far a flow has got")
    t.add_argument("flowdir")
    t.add_argument("--json", action="store_true")
    t.set_defaults(fn=cmd_status)

    p = sub.add_parser("step", help="run one card (what a step job calls)")
    p.add_argument("flowdir")
    p.add_argument("card")
    p.set_defaults(fn=cmd_step)

    k = sub.add_parser("stop", help="cancel what is still queued")
    k.add_argument("flowdir")
    k.set_defaults(fn=cmd_stop)

    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return 2
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
