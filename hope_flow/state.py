"""What has happened to a flow, as the jobs write it down.

A flow's record is a folder, `state/`, holding one small file per card, beside flow.json. Each is
written whole and moved into place, so a reader sees a card before a write or after it and never
half of one.

One file per card rather than one for the flow, and that is not tidiness. Several step jobs are
awake at once, and a single document meant every one of them read it, changed its own card and
wrote the whole thing back - so two cards finishing within a few seconds of each other lost one of
the two writes. It happened on the first real run: a card queued its tool, said so in its log, and
the record still showed it as waiting, because the card beside it wrote afterwards from a copy
taken before. Cards are now written one at a time and only by the jobs that have something to say
about them, and where two jobs do write the same card they write the same thing.

What does not change while a flow runs - where it came from, which Python, which account - stays
in flow.json, written once.
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
    """The record of one flow's run: a folder of small files, one for each card."""

    def __init__(self, folder, data=None):
        self.folder = str(folder)
        self.where = os.path.join(self.folder, "state")
        self.data = data if data is not None else {"version": 1, "cards": {}, "started": _now()}
        self._changed = set()                  # the cards this process has something to say about

    # ---- reading and writing ---------------------------------------------
    @classmethod
    def read(cls, folder):
        it = cls(folder)
        it.data = {"version": 1, "cards": {}, "started": _now()}
        try:
            names = sorted(os.listdir(it.where))
        except OSError:
            names = []
        for name in names:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(it.where, name), encoding="utf-8") as fh:
                    it.data["cards"][name[:-5]] = json.load(fh)
            except (ValueError, OSError):
                # A half-written file should never exist, since every write is a rename, and one
                # card that cannot be read is not worth losing the rest of the flow to.
                it.data["cards"][name[:-5]] = {
                    "state": WAITING, "jobs": [], "rundir": "", "changed": _now(),
                    "note": "this card's record could not be read"}
        # Anything settled when the flow was queued and not changed since.
        try:
            with open(os.path.join(it.folder, "flow.json"), encoding="utf-8") as fh:
                it.data["settled"] = json.load(fh).get("settled") or {}
        except (ValueError, OSError):
            it.data["settled"] = {}
        it.data.update(it.data.get("settled") or {})
        return it

    def write(self):
        """Write the cards this process changed, each in one step, and nothing else.

        Writing only what this job has something to say about is the whole point: a job that
        rewrote every card would undo whatever another job wrote while it was working.
        """
        os.makedirs(self.where, exist_ok=True)
        for nid in sorted(self._changed):
            path = os.path.join(self.where, "%s.json" % nid)
            tmp = "%s.%d.tmp" % (path, os.getpid())
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data["cards"][nid], fh, indent=2, sort_keys=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        self._changed.clear()

    # ---- one card --------------------------------------------------------
    def card(self, nid):
        """One card's record. Read it freely; change it only through set(), which is what marks
        it to be written. Reaching in here and assigning is a change this process keeps and
        nothing else ever sees."""
        return self.data.setdefault("cards", {}).setdefault(
            nid, {"state": WAITING, "jobs": [], "rundir": "", "note": "", "changed": _now()})

    def set(self, nid, state=None, rundir=None, jobs=None, note=None, **more):
        """Record what became of a card. Only what is given is changed."""
        it = self.card(nid)
        self._changed.add(nid)
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
        # A flow somebody stopped has not failed, and telling them it did would be wrong twice
        # over: it says something went wrong, and it hides the one that actually did when a flow
        # holds both.
        broken = [r for r in rows if r["state"] == FAILED]
        halted = [r for r in rows if r["state"] == STOPPED]
        if broken:
            state = FAILED
        elif done == len(rows):
            state = DONE
        elif halted and not any(r["state"] in (QUEUED, RUNNING, READY, WAITING) for r in rows):
            state = STOPPED
        else:
            state = RUNNING
        first = (broken or halted or [{"note": ""}])[0]
        return {"name": flow.name, "cards": rows, "done": done, "of": len(rows),
                "state": state, "note": first["note"]}


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
