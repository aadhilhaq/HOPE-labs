"""What has happened to a flow, as the jobs write it down.

state.json sits beside flow.json and is the only thing that changes while a flow runs. It is
written by jobs on compute nodes, several of which can be awake at once, so every write is a
whole new file moved into place: a reader either sees the state before a write or the state
after it, and never half of one. Nothing reads it to decide what to do next except through
`claim()`, which is where that decision is made atomically.
"""
from __future__ import annotations

import json
import os
import time

#: What a card can be. A card is "waiting" until everything arriving at it has finished.
WAITING, READY, QUEUED, RUNNING, DONE, FAILED, STOPPED = (
    "waiting", "ready", "queued", "running", "done", "failed", "stopped")

#: The states a flow does not come back from.
ENDED = (DONE, FAILED, STOPPED)


def _now():
    return int(time.time())


class State:
    """The record of one flow's run, read and written as a whole."""

    def __init__(self, path, data=None):
        self.path = str(path)
        self.data = data if data is not None else {"version": 1, "cards": {}, "started": _now()}

    # ---- reading and writing ---------------------------------------------
    @classmethod
    def read(cls, folder):
        path = os.path.join(str(folder), "state.json")
        try:
            with open(path, encoding="utf-8") as fh:
                return cls(path, json.load(fh))
        except FileNotFoundError:
            return cls(path)
        except (ValueError, OSError):
            # A half-written file should never exist, since every write is a rename, but a flow
            # is not worth losing to one unreadable byte: start a fresh record and say so.
            return cls(path, {"version": 1, "cards": {}, "started": _now(),
                              "note": "the previous record could not be read"})

    def write(self):
        """Replace the file in one step, so a reader never sees a part of it."""
        tmp = "%s.%d.tmp" % (self.path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, sort_keys=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    # ---- one card --------------------------------------------------------
    def card(self, nid):
        return self.data.setdefault("cards", {}).setdefault(
            nid, {"state": WAITING, "jobs": [], "rundir": "", "note": "", "changed": _now()})

    def set(self, nid, state=None, rundir=None, jobs=None, note=None, **more):
        """Record what became of a card. Only what is given is changed."""
        it = self.card(nid)
        if state is not None:
            it["state"] = state
        if rundir is not None:
            it["rundir"] = str(rundir)
        if jobs is not None:
            it["jobs"] = [str(j) for j in jobs]
        if note is not None:
            it["note"] = note
        it.update(more)
        it["changed"] = _now()
        return it

    def state_of(self, nid):
        return self.card(nid)["state"]

    def finished(self, nid):
        return self.state_of(nid) == DONE

    def ended(self):
        """True once nothing more will happen without somebody asking for it."""
        cards = self.data.get("cards", {})
        return bool(cards) and all(c["state"] in ENDED for c in cards.values())

    def summary(self, flow):
        """What the launcher shows: a line per card, in the order they run."""
        rows = []
        for node in flow.order():
            it = self.card(node.id)
            rows.append({"id": node.id, "card": node.card,
                         "name": node.kind.name if node.kind else node.card,
                         "state": it["state"], "jobs": it["jobs"], "rundir": it["rundir"],
                         "note": it["note"], "changed": it["changed"]})
        done = sum(1 for r in rows if r["state"] == DONE)
        bad = [r for r in rows if r["state"] in (FAILED, STOPPED)]
        return {"name": flow.name, "cards": rows, "done": done, "of": len(rows),
                "state": (FAILED if bad else DONE if done == len(rows) else RUNNING),
                "note": bad[0]["note"] if bad else ""}


def claim(folder, nid):
    """Take the right to run this card, once. True for the one caller that gets it.

    A card with two tracks arriving at it is woken by both of them, and on a good day both wake
    at the same moment. A directory is made in one step or not at all, on every file system the
    cluster has, so the one that makes it does the work and the other goes back to sleep.
    """
    where = os.path.join(str(folder), "claims")
    os.makedirs(where, exist_ok=True)
    try:
        os.mkdir(os.path.join(where, nid))
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def unclaim(folder, nid):
    """Give the claim back, so the card can be tried again after a failure."""
    try:
        os.rmdir(os.path.join(str(folder), "claims", nid))
    except OSError:
        pass
