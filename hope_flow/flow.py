"""A flow: the graph a person drew, and the order it has to run in.

The file is flow.json in the flow's own folder. It holds what was drawn and nothing of what
happened, so a flow can be read, copied and queued again without carrying one run's history into
the next. What happened is state.json beside it, written by the jobs as they go.
"""
from __future__ import annotations

import json
import re

from . import cards

NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


class Node:
    """One card as it was placed: which card, what was filled in, and where it sits."""

    def __init__(self, nid, card, settings=None, at=(0, 0)):
        self.id = nid
        self.card = card
        self.settings = dict(settings or {})
        self.at = tuple(at)                      # where the canvas drew it; the runner ignores it

    @property
    def kind(self):
        return cards.BY_KEY.get(self.card)

    def as_json(self):
        return {"id": self.id, "card": self.card, "settings": self.settings,
                "at": list(self.at)}


class Edge:
    """One link: a port on one node to a port on another."""

    def __init__(self, src, src_port, dst, dst_port):
        self.src, self.src_port = src, src_port
        self.dst, self.dst_port = dst, dst_port

    def as_json(self):
        return {"from": self.src, "fromPort": self.src_port,
                "to": self.dst, "toPort": self.dst_port}


class Flow:
    """The whole graph, with the questions the runner asks of it."""

    def __init__(self, name="", nodes=(), edges=(), runs_root=""):
        self.name = name
        self.nodes = list(nodes)
        self.edges = list(edges)
        self.runs_root = runs_root

    # ---- reading and writing ---------------------------------------------
    @classmethod
    def from_json(cls, text):
        raw = json.loads(text) if isinstance(text, str) else dict(text)
        nodes = [Node(n["id"], n["card"], n.get("settings"), n.get("at", (0, 0)))
                 for n in raw.get("nodes", [])]
        edges = [Edge(e["from"], e["fromPort"], e["to"], e["toPort"])
                 for e in raw.get("edges", [])]
        return cls(raw.get("name", ""), nodes, edges, raw.get("runs_root", ""))

    def as_json(self):
        return {"version": 1, "name": self.name, "runs_root": self.runs_root,
                "nodes": [n.as_json() for n in self.nodes],
                "edges": [e.as_json() for e in self.edges]}

    def dumps(self):
        return json.dumps(self.as_json(), indent=2, sort_keys=False) + "\n"

    # ---- the graph -------------------------------------------------------
    def node(self, nid):
        return next((n for n in self.nodes if n.id == nid), None)

    def into(self, nid):
        """The edges arriving at this node."""
        return [e for e in self.edges if e.dst == nid]

    def out_of(self, nid):
        return [e for e in self.edges if e.src == nid]

    def upstream(self, nid):
        """The ids this node waits for, in the order they were drawn."""
        seen = []
        for e in self.into(nid):
            if e.src not in seen:
                seen.append(e.src)
        return seen

    def sources(self):
        """The nodes nothing arrives at: where a flow starts."""
        return [n for n in self.nodes if not self.into(n.id)]

    def order(self):
        """Every node, each after the ones it waits for.

        Raises when the graph has a cycle, naming the nodes still waiting, because a cycle drawn
        by hand is otherwise a flow that queues nothing and says nothing about why.
        """
        done, out = set(), []
        left = list(self.nodes)
        while left:
            ready = [n for n in left if all(u in done for u in self.upstream(n.id))]
            if not ready:
                raise ValueError("these cards wait on each other: "
                                 + ", ".join(sorted(n.id for n in left)))
            for n in ready:
                done.add(n.id)
                out.append(n)
            left = [n for n in left if n.id not in done]
        return out

    def target_of(self, nid):
        """The target card feeding this node, however far upstream it sits.

        Every tool needs the receptor and the site, and only the target card holds them, so each
        node follows its edges back to one. A flow with two targets is refused by check(); this
        returns the first it reaches.
        """
        seen, edge = set(), list(self.upstream(nid))
        while edge:
            nid2 = edge.pop(0)
            if nid2 in seen:
                continue
            seen.add(nid2)
            node = self.node(nid2)
            if node is not None and node.card == "target":
                return node
            edge.extend(self.upstream(nid2))
        return None

    # ---- what is wrong with it -------------------------------------------
    def check(self):
        """Everything wrong with this flow, as sentences. Empty means it can be queued."""
        bad = []
        if not NAME_OK.match(self.name or ""):
            bad.append("the flow needs a name of letters, digits, dot, dash or underscore")
        ids = [n.id for n in self.nodes]
        if len(set(ids)) != len(ids):
            bad.append("two cards share an id")
        if not self.nodes:
            bad.append("there is nothing on the canvas")

        targets = [n for n in self.nodes if n.card == "target"]
        if not targets:
            bad.append("there is no target: every flow starts from one")
        elif len(targets) > 1:
            bad.append("there is more than one target, and a flow runs against one")

        for n in self.nodes:
            if n.kind is None:
                bad.append("%s is not a card this launcher knows" % n.id)
        if bad:
            return bad                     # the rest reads the cards, so stop while they are sound

        settings = targets[0].settings if targets else {}
        for e in self.edges:
            src, dst = self.node(e.src), self.node(e.dst)
            if src is None or dst is None:
                bad.append("a link joins a card that is not on the canvas")
                continue
            why = cards.link_refused(src.card, e.src_port, dst.card, e.dst_port, settings)
            if why:
                bad.append("%s to %s: %s" % (src.kind.name, dst.kind.name, why))

        drawn = set()
        for e in self.edges:
            at = (e.src, e.src_port, e.dst, e.dst_port)
            if at in drawn:
                bad.append("the same link is drawn twice, from %s to %s"
                           % (self.node(e.src).kind.name, self.node(e.dst).kind.name))
            drawn.add(at)

        for n in self.nodes:
            for port in n.kind.inputs:
                arriving = [e for e in self.into(n.id) if e.dst_port == port.key]
                if port.required and not arriving:
                    bad.append("%s has nothing arriving at %s" % (n.kind.name, port.label))
                # A port that takes one thing and is given several is not a flow anybody can run:
                # the tool would be told two receptors, or two sets of peptides, with nothing to
                # say which. The canvas refuses the second while it is drawn; this is for a flow
                # that reached the cluster as a file.
                if not port.many and len(arriving) > 1:
                    bad.append("%s takes one thing at %s, and %d arrive"
                               % (n.kind.name, port.label, len(arriving)))
            if n.card != "target" and self.target_of(n.id) is None:
                bad.append("%s is not connected back to the target" % n.kind.name)
            if not n.kind.ready:
                bad.append("%s cannot be started by a flow yet%s"
                           % (n.kind.name, (": " + n.kind.note) if n.kind.note else ""))
            bad.extend(_unanswered(n))

        try:
            self.order()
        except ValueError as why:
            bad.append(str(why))

        if targets:
            bad.extend(_target_problems(targets[0].settings))
        return bad


def _unanswered(node):
    """The settings this card will not start without, that nobody has filled in.

    A default is not an answer for these: they are the few where a wrong value costs a day of a
    cluster and the right one is nobody's to guess. The canvas shows the default in the box, so
    all a person has to do is agree with it - but they have to agree with it.
    """
    bad = []
    for field in node.kind.settings:
        if not field.needed:
            continue
        value = node.settings.get(field.key)
        if value in (None, ""):
            bad.append("%s needs %s" % (node.kind.name, field.label.lower()))
            continue
        if field.kind == "number":
            try:
                if float(value) <= 0:
                    bad.append("%s: %s should be more than nothing"
                               % (node.kind.name, field.label.lower()))
            except (TypeError, ValueError):
                bad.append("%s: %s should be a number" % (node.kind.name, field.label.lower()))
        elif field.choices and str(value) not in field.choices:
            bad.append("%s: %r is not one of the choices for %s"
                       % (node.kind.name, value, field.label.lower()))
    return bad


def _target_problems(s):
    """What is missing or impossible on the target card itself."""
    bad = []
    source = (s.get("source") or "rcsb").strip()
    if source == "rcsb":
        if not re.match(r"^[0-9A-Za-z]{4}$", (s.get("pdb_id") or "").strip()):
            bad.append("the target needs a four-character PDB id")
    elif source == "file":
        if not (s.get("path") or "").strip():
            bad.append("the target needs a structure file")
    else:
        bad.append("the target's source should be rcsb or file")
    if not (s.get("hotspots") or "").strip():
        bad.append("the target needs hotspots: the residues a binder should touch")
    lo, hi = s.get("binder_min"), s.get("binder_max")
    try:
        lo, hi = int(lo), int(hi)
        if lo < 4 or hi < lo:
            bad.append("the binder length should be a range, shortest first, of at least 4 residues")
    except (TypeError, ValueError):
        bad.append("the binder length should be two numbers")
    return bad
