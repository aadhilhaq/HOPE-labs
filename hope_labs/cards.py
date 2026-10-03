"""The cards a flow is drawn from, and what may be linked to what.

A card is one tool. Its ports say what it needs and what it leaves, and a port carries a kind:
a target, sequences, complexes, poses. An edge is allowed only where the kinds meet, which is
what stops the two mistakes that a free-hand canvas would otherwise invite - sending a target
where sequences are wanted, and docking a binder far too large for the docking to take.

Everything a person can draw is described here and nowhere else. The canvas reads this through
the launcher, the runner reads it on the cluster, and neither holds a second opinion about which
links are legal.
"""
from __future__ import annotations

#: What travels along an edge. The text is what the canvas shows when a link is refused, so each
#: one reads as the end of the sentence "this port carries ...".
KINDS = {
    "target":      "a receptor, with the chains and the residues a binder should touch",
    "sequences":   "named peptide or protein sequences, without structures",
    "complexes":   "structures of a binder already placed on the target",
    "poses":       "docked poses, ranked, in a run folder",
    "trajectories": "simulated complexes, with their binding energies",
}

#: The longest peptide ADCP will take (adcp_dock/peptide.py, MAX_LENGTH). A design longer than
#: this cannot be docked, so an edge carrying sequences into docking is refused when the binder
#: length being asked for is above it. The number lives here as well because the canvas has to
#: answer before anything is submitted, on the laptop, where ADCP is not installed.
DOCKABLE_MAX_LENGTH = 30


class Port:
    """One socket on a card: what it carries, and whether a flow can be launched without it."""

    def __init__(self, key, label, kinds, required=True, many=False, sized=False):
        self.key = key
        self.label = label
        self.kinds = tuple(kinds)       # the kinds this port accepts, in order of preference
        self.required = required
        self.many = many                # whether several edges may arrive here
        #: True where what leaves here is as long as the target card asked a binder to be. It is
        #: the designed binders that are: a pipeline's peptides are short by the shape of the
        #: pipeline that made them, whatever length was asked of the design tools beside it.
        self.sized = sized

    def takes(self, kind):
        return kind in self.kinds

    def as_json(self):
        return {"key": self.key, "label": self.label, "kinds": list(self.kinds),
                "required": self.required, "many": self.many, "sized": self.sized}


class Card:
    """One tool on the canvas: its ports, and the settings a person may fill in on it.

    `tool` is the key the launcher's catalogue uses for the same tool, so a flow and the Tools
    page are talking about one install rather than two that happen to share a name. The target
    card has no tool: it is where the person's own input goes.
    """

    def __init__(self, key, name, tagline, tool="", inputs=(), outputs=(), settings=(), note="",
                 ready=True):
        self.key = key
        self.name = name
        self.tagline = tagline
        self.tool = tool
        self.inputs = tuple(inputs)
        self.outputs = tuple(outputs)
        self.settings = tuple(settings)
        self.note = note
        #: Whether a flow can start this tool yet. A card that cannot is still drawn, and still
        #: says what it would do, but a flow holding one is refused before anything is queued
        #: rather than failing in a job twenty minutes later.
        self.ready = ready

    def port_in(self, key):
        return next((p for p in self.inputs if p.key == key), None)

    def port_out(self, key):
        return next((p for p in self.outputs if p.key == key), None)

    def as_json(self):
        return {"key": self.key, "name": self.name, "tagline": self.tagline, "tool": self.tool,
                "note": self.note, "ready": self.ready,
                "inputs": [p.as_json() for p in self.inputs],
                "outputs": [p.as_json() for p in self.outputs],
                "settings": [s.as_json() for s in self.settings]}


class Setting:
    """A field on a card. `kind` is how the canvas draws it, not how it is stored."""

    def __init__(self, key, label, kind, default=None, choices=(), why="", optional=False):
        self.key = key
        self.label = label
        self.kind = kind                # text | number | choice | residues | yesno | path
        self.default = default
        self.choices = tuple(choices)
        self.why = why                  # the line under the field
        self.optional = optional

    def as_json(self):
        return {"key": self.key, "label": self.label, "kind": self.kind, "default": self.default,
                "choices": list(self.choices), "why": self.why, "optional": self.optional}


# --- the cards -------------------------------------------------------------------------------
# The target is the one card a flow cannot do without, and in the simplest flow it is the only
# card anybody fills in: a structure, the residues to aim at, and how long the binder should be.
# Every other card takes its target through an edge rather than asking again, so the same
# receptor and the same site reach the design, the docking and the simulation by construction.

TARGET = Card(
    "target", "Target", "what everything is aimed at",
    outputs=[Port("target", "target", ["target"])],
    settings=[
        Setting("source", "Where the structure comes from", "choice", "rcsb",
                choices=["rcsb", "file"], why="a four-character RCSB id, or a file on the cluster"),
        Setting("pdb_id", "PDB id", "text", "", why="fetched on a login node and copied into the flow"),
        Setting("path", "Structure file", "path", "", optional=True),
        Setting("chains", "Chains", "text", "", optional=True,
                why="empty takes every chain in the file"),
        Setting("hotspots", "Hotspots", "residues", "",
                why="residue numbers of this structure, as 54,56,66-70 or A54,B12-16"),
        # What the design tools are asked for. A pipeline's peptides are not sized from here;
        # their length follows the pipeline that makes them.
        Setting("binder_min", "Shortest designed binder, residues", "number", 70),
        Setting("binder_max", "Longest designed binder, residues", "number", 100),
    ])

PIPELINES = Card(
    "pipelines", "HOPE-pipelines", "design peptides against the target",
    tool="pipelines",
    inputs=[Port("target", "target", ["target"])],
    outputs=[Port("sequences", "designed peptides", ["sequences"])],
    note="Peptides, short enough to dock.")

BINDCRAFT = Card(
    "bindcraft", "BindCraft2", "design a miniprotein binder",
    tool="bindcraft",
    inputs=[Port("target", "target", ["target"])],
    # Two ways out, which is the whole of the choice a person has here. A design arrives with the
    # binder already placed on the target, so it can be simulated as it stands; its sequence can
    # instead be docked, but only where the binder is short enough for the docking to take it.
    outputs=[Port("complexes", "designed complexes", ["complexes"]),
             Port("sequences", "design sequences", ["sequences"], sized=True)],
    note="Designs come out already placed on the target, so docking them again is optional.")

APTAMER = Card(
    "aptamer", "HOPE-Aptamer", "design and fold an aptamer",
    tool="aptamer",
    inputs=[Port("target", "target", ["target"])],
    outputs=[Port("poses", "aptamer poses", ["poses"])],
    # Its poses can be simulated - the simulation has read a HOPE-Aptamer run for a long time -
    # but how to start a run of it without its page is not settled, so a flow will not start one.
    ready=False,
    note="Not yet startable from a flow: its poses can be simulated, but a run of it is still "
         "started from its own page.")

ADCP = Card(
    "adcp", "ADCP docking", "dock peptides into the target",
    tool="adcp",
    inputs=[Port("target", "target", ["target"]),
            Port("sequences", "peptides to dock", ["sequences"], many=True)],
    outputs=[Port("poses", "docked poses", ["poses"])],
    note="Takes peptides of %d residues or fewer." % DOCKABLE_MAX_LENGTH)

HOPEMD = Card(
    "hopemd", "HOPE-MD", "simulate what arrives",
    tool="hopemd",
    # One port taking either kind, and as many edges as there are branches: this is where the
    # tracks of a flow meet, and one batch of simulations comes out of all of them.
    inputs=[Port("structures", "poses or complexes", ["poses", "complexes"], many=True)],
    outputs=[Port("trajectories", "trajectories", ["trajectories"])])

CARDS = (TARGET, PIPELINES, BINDCRAFT, APTAMER, ADCP, HOPEMD)
BY_KEY = {c.key: c for c in CARDS}


def catalogue():
    """Every card, for the canvas."""
    return {"kinds": KINDS, "dockable_max_length": DOCKABLE_MAX_LENGTH,
            "cards": [c.as_json() for c in CARDS]}


def link_refused(from_card, from_port, to_card, to_port, settings=None):
    """Why this link cannot be drawn, or "" when it can.

    The canvas asks before it draws and the runner asks again before it submits, because a flow
    can reach the cluster from a file as well as from the canvas.
    """
    a, b = BY_KEY.get(from_card), BY_KEY.get(to_card)
    if a is None or b is None:
        return "there is no such card"
    out, into = a.port_out(from_port), b.port_in(to_port)
    if out is None:
        return "%s leaves nothing called %s" % (a.name, from_port)
    if into is None:
        return "%s takes nothing called %s" % (b.name, to_port)
    kind = next((k for k in out.kinds if into.takes(k)), "")
    if not kind:
        return ("%s carries %s; %s's %s takes %s"
                % (out.label, " or ".join(KINDS[k] for k in out.kinds), b.name, into.label,
                   " or ".join(KINDS[k] for k in into.kinds)))
    # The one refusal that is about a number rather than a kind. A binder longer than the docking
    # will take is not a link anybody can rescue later, so it is refused while it is being drawn.
    # Only what the flow sized is measured: peptides from a pipeline are short whatever was asked
    # of the design tools beside it, and docking them is the ordinary way round.
    if kind == "sequences" and b.key == "adcp" and out.sized:
        longest = (settings or {}).get("binder_max")
        try:
            longest = int(longest)
        except (TypeError, ValueError):
            # No length asked for yet. The whole flow is refused for that separately, but this is
            # also asked on its own, by the runner, where letting it pass would dock a binder far
            # too long for the docking to take.
            return ("this link needs the binder length the flow asks for, and the target does "
                    "not give one")
        if longest > DOCKABLE_MAX_LENGTH:
            return ("the docking takes peptides of %d residues or fewer, and this flow asks for "
                    "binders of up to %d. Simulate these designs directly, or ask for shorter ones."
                    % (DOCKABLE_MAX_LENGTH, longest))
    return ""
