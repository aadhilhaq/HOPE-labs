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

#: The pipelines' own names for their four pipelines, verbatim from hope_core.pipelines: the
#: double space before the bracket is theirs, and the label is matched on, so it is copied rather
#: than tidied.
PIPELINE_LABELS = (
    "dimer loop  (400 dipeptides, grown over rounds)",
    "dimer  (400 dipeptides, single pass)",
    "trimer  (8,000 tripeptides, single pass)",
    "trimer loop  (8,000 tripeptides, grown over rounds)",
    "tetramer  (160,000 tetrapeptides, single pass)",
)

#: The linker families the design pipelines can build a join from, copied from
#: hope_core/linker_choice.py (FAMILY_NOTES) with its own one-line descriptions. Copied because
#: this is read on a laptop, where that package is not installed, and the canvas has to be able to
#: say what a name means before anything reaches the cluster.
#:
#: Only the two loop pipelines use them. The single-pass ones join with the plain Gly/Ser ladder
#: whatever is asked for here, and the pipeline says so in its log rather than silently obeying.
LINKER_FAMILIES = {
    "flexible": "bends freely, the safe default",
    "flexShort": "the same idea with less bulk, for a small gap",
    "helixRigid": "a rigid helix, holding the two ends apart",
    "ppiiAP": "rigid and extended: reaches furthest per residue",
    "ppiiPT": "the same, more soluble",
    "turn": "doubles back over a short distance",
    "polar": "dissolves well, and does not fold onto the site",
    "acidic": "negatively charged, so it repels itself and stays extended",
    "basic": "positively charged, against an acidic site",
    "xten": "unstructured and long, resisting proteases and aggregation",
    "anchorDerived": "made of the anchors' own residues",
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

    def __init__(self, key, label, kind, default=None, choices=(), why="", optional=False,
                 needed=False, advanced=False):
        self.key = key
        self.label = label
        self.kind = kind                # text | number | choice | residues | yesno | path
        self.default = default
        self.choices = tuple(choices)
        self.why = why                  # the line under the field
        self.optional = optional
        #: A setting the flow will not start without. A default is not an answer here: these are
        #: the few where a wrong value is expensive and the right one is nobody's to guess, so a
        #: person says what they mean before anything is queued rather than finding out from a
        #: run that did the wrong thing for a day.
        self.needed = needed
        #: Shown only when a person asks for more. The few settings above the fold are the ones
        #: that change what a run is; these change how it is done, and a tool's own defaults are
        #: the lab's considered answer to most of them. Hiding them is not hiding the choice -
        #: it is not making somebody refuse twenty of them to get to the one they came for.
        self.advanced = advanced

    def as_json(self):
        return {"key": self.key, "label": self.label, "kind": self.kind, "default": self.default,
                "choices": list(self.choices), "why": self.why, "optional": self.optional,
                "needed": self.needed, "advanced": self.advanced}


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
    settings=[
        # Which pipeline is the whole shape of the run - how big a library, and whether it is
        # grown over rounds - so it is asked for rather than defaulted into.
        Setting("pipeline", "Pipeline", "choice", PIPELINE_LABELS[0], choices=PIPELINE_LABELS,
                why="how large a library, and whether it is grown over rounds", needed=True),
        Setting("rounds", "Rounds", "number", 3, optional=True,
                why="only for a pipeline that grows its library"),
        Setting("n_constructs", "Constructs to carry forward", "number", 25, optional=True),
        Setting("n_mmgbsa", "Of those, how many to score with MM-GBSA", "number", 10, optional=True,
                why="the slow step: each one is minutes on a large receptor"),
        # The docking downstream takes nothing over thirty residues, and the pipelines' own
        # default is no maximum at all, so a run can spend a day designing constructs the next
        # card will drop. Reachable here for that reason.
        Setting("max_construct_length", "Longest construct, residues", "number", 0, optional=True,
                advanced=True, why="0 is no maximum. The docking takes 30"),
        Setting("min_construct_length", "Shortest construct, residues", "number", 10,
                optional=True, advanced=True),
        Setting("library_size", "Library size", "number", 0, optional=True, advanced=True,
                why="0 keeps the pipeline's own"),
        Setting("exhaustiveness", "Docking exhaustiveness", "number", 8, optional=True,
                advanced=True),
        Setting("adcp_replicas", "ADCP replicas, when it reranks", "number", 100, optional=True,
                advanced=True),
        Setting("adcp_steps", "ADCP steps", "number", 0, optional=True, advanced=True,
                why="0 is a million per residue, which is the guideline"),
        Setting("ph", "pH", "number", 7.4, optional=True, advanced=True),
        Setting("protein_prep", "Prepare the receptor", "yesno", True, optional=True,
                advanced=True),
        Setting("colabfold", "Co-fold the designs to check the site", "yesno", True,
                optional=True, advanced=True, why="a GPU job after the design job"),
        Setting("mmgbsa", "Rescore with MM-GBSA", "yesno", True, optional=True, advanced=True),
        Setting("scout", "Scout single residues for the gaps", "yesno", False, optional=True,
                advanced=True, why="changes which peptides are designed"),
        Setting("hopepe", "Judge practicality as well as binding", "yesno", True, optional=True,
                advanced=True),
        # How the pieces are joined. Only the loop pipelines reach the chooser at all, which is
        # why each of these says so: a setting that is quietly ignored is worse than one that is
        # not offered.
        Setting("anchor_linkers", "Linker strategy", "choice", "",
                choices=["", "off", "prefer", "compete"], optional=True, advanced=True,
                why="empty keeps the pipeline's own. off joins with the plain Gly/Ser ladder; "
                    "prefer and compete choose a linker by what it is, using the anchors' own "
                    "residues where they already fill the gap. Loop pipelines only"),
        Setting("linker_sweep", "Try several linker families", "yesno", False, optional=True,
                advanced=True, why="builds a candidate from each family and scores them. "
                                   "Loop pipelines only"),
        Setting("sweep_families", "Families to try", "text", "", optional=True, advanced=True,
                why="comma separated, from: " + ", ".join(LINKER_FAMILIES)),
        Setting("cpus", "Cores", "number", 0, optional=True, advanced=True,
                why="0 keeps the pipeline's own"),
        Setting("partition", "Partition", "text", "", optional=True, advanced=True),
        Setting("account", "Account to charge", "text", "", optional=True, advanced=True),
    ],
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
    settings=[
        Setting("designs", "Stop when this many designs pass", "number", 10, needed=True,
                why="a campaign runs until it has this many, or until its walltime ends"),
        Setting("gpu", "Card", "choice", "auto",
                choices=["auto", "a100", "a40", "rtx"], optional=True),
        Setting("walltime", "Walltime", "text", "24:00:00", optional=True,
                why="a campaign that runs out carries on when it is queued again"),
        Setting("coldspots", "Coldspots", "residues", "", optional=True, advanced=True,
                why="residues to keep clear of"),
        Setting("forced", "Focus on the hotspots", "yesno", False, optional=True, advanced=True,
                why="the surface outside them is rebuilt so a binder cannot settle elsewhere"),
        Setting("gpus", "Cards", "number", 1, optional=True, advanced=True),
        Setting("account", "Account to charge", "text", "", optional=True, advanced=True),
    ],
    note="Designs come out already placed on the target, so docking them again is optional.")

# The two machine-learning design tools. Both are the same shape as BindCraft2 - a target in, a
# binder placed on it out - and both differ from it in the same way: they have no page of their
# own on the Tools screen, so a flow is the only way the lab runs them.
RFDIFFUSION = Card(
    "rfdiffusion", "RFdiffusion", "design a binder backbone, then its sequence",
    tool="rfdiffusion",
    inputs=[Port("target", "target", ["target"])],
    # Same two ways out as BindCraft2, and for the same reason: RFdiffusion keeps the target in
    # the structure it writes, so a design is a complex already, and ProteinMPNN is what gives it
    # a sequence to dock.
    outputs=[Port("complexes", "designed complexes", ["complexes"]),
             Port("sequences", "design sequences", ["sequences"], sized=True)],
    settings=[
        Setting("designs", "Backbones to generate", "number", 10, needed=True,
                why="each is a separate diffusion, and the whole run is this many"),
        Setting("seqs_per_backbone", "Sequences per backbone", "number", 8, needed=True,
                why="ProteinMPNN designs this many for each backbone, and the best is kept"),
        Setting("gpu", "Card", "choice", "auto",
                choices=["auto", "a100", "a40", "rtx"], optional=True),
        Setting("walltime", "Walltime", "text", "12:00:00", optional=True),
        # RFdiffusion's own knobs. The defaults are the ones its binder-design example uses, and
        # changing them changes what the diffusion does rather than how it is run.
        # Not RFdiffusion's own default, which is 1: the binder-design example lowers it to 0, and
        # that is what makes the backbones worth giving a sequence to. Raising it is how to ask
        # for more varied designs, at the cost of how many of them hold up.
        Setting("noise_scale", "Noise scale", "number", 0, optional=True, advanced=True,
                why="0 is what the binder-design example uses. Higher is more varied and fewer "
                    "of them fold"),
        Setting("diffuser_T", "Diffusion steps", "number", 50, optional=True, advanced=True,
                why="fewer is faster and rougher"),
        Setting("ckpt", "Checkpoint", "choice", "",
                choices=["", "Complex_base_ckpt.pt", "Complex_beta_ckpt.pt"],
                optional=True, advanced=True, why="empty takes the binder-design default"),
        # There is no "relax each design before scoring" here, and that is deliberate. It was
        # offered and did nothing: relaxing needs dl_binder_design's own interface script, which
        # needs a PyRosetta licence this install has not got. Somebody would have set it, watched
        # a twelve-hour run and concluded it made no difference to the science, rather than that
        # it had never been passed on. If the licence is ever bought, the driver and the helper
        # have to learn it before this comes back.
        Setting("partition", "Partition", "text", "", optional=True, advanced=True),
        Setting("account", "Account to charge", "text", "", optional=True, advanced=True),
    ],
    note="Designs come out placed on the target, so docking them again is optional.")

BOLTZGEN = Card(
    "boltzgen", "BoltzGen", "generate a binder against the target",
    tool="boltzgen",
    inputs=[Port("target", "target", ["target"])],
    outputs=[Port("complexes", "designed complexes", ["complexes"]),
             Port("sequences", "design sequences", ["sequences"], sized=True)],
    settings=[
        # The protocol is the whole of what this tool is asked: a peptide and a nanobody against
        # the same target are different runs of the same model, not different settings of one.
        Setting("protocol", "What to design", "choice", "protein-anything",
                choices=["protein-anything", "peptide-anything", "nanobody-anything",
                         "antibody-anything", "protein-small_molecule", "protein-redesign"],
                needed=True, why="the model's own protocols; the binder kind is chosen here"),
        Setting("designs", "Designs to generate", "number", 10, needed=True),
        # 16 GB is not enough: upstream reports running out of memory on a modest target, and on
        # the analysis step at a hundred designs. So the small cards are not offered here.
        Setting("gpu", "Card", "choice", "a100", choices=["a100", "a40"], optional=True,
                why="BoltzGen needs 40 GB or more; the smaller cards run out"),
        Setting("walltime", "Walltime", "text", "12:00:00", optional=True),
        Setting("cyclic", "Cyclic peptide", "yesno", False, optional=True, advanced=True,
                why="peptide protocols only"),
        # The key is still sampling_steps because saved flows carry it under that name, and
        # renaming it would quietly drop the setting out of every flow already drawn. What it is
        # is BoltzGen's --step_scale, which scales the diffusion step rather than counting steps,
        # and the label says so: the old one read as a number of steps and it is not one.
        Setting("sampling_steps", "Step scale", "number", 0, optional=True, advanced=True,
                why="0 takes the protocol's own. It scales the diffusion step, and is not a "
                    "count of steps"),
        Setting("fold", "Fold and score each design", "yesno", True, optional=True, advanced=True,
                why="the ranking comes from this; off leaves designs unranked"),
        Setting("partition", "Partition", "text", "", optional=True, advanced=True),
        Setting("account", "Account to charge", "text", "", optional=True, advanced=True),
    ],
    note="Generates binders against a target of any kind, protein, peptide, nucleic acid or "
         "small molecule, and leaves them already placed on it.")

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
    settings=[
        Setting("poses", "Poses to keep per peptide", "number", 10, optional=True),
        Setting("replicas", "Replicas", "number", 50, optional=True,
                why="how many independent searches per peptide"),
        Setting("mmgbsa", "Score the best poses with MM-GBSA", "yesno", True, optional=True,
                why="slower, and the more considered estimate of binding"),
        Setting("steps", "Steps per replica", "number", 0, optional=True, advanced=True,
                why="0 is the docking's own"),
        Setting("cpus", "Cores", "number", 48, optional=True, advanced=True),
        Setting("walltime", "Walltime", "text", "08:00:00", optional=True, advanced=True),
        Setting("partition", "Partition", "text", "", optional=True, advanced=True),
        Setting("account", "Account to charge", "text", "", optional=True, advanced=True),
    ],
    note="Takes peptides of %d residues or fewer." % DOCKABLE_MAX_LENGTH)

HOPEMD = Card(
    "hopemd", "HOPE-MD", "simulate what arrives",
    tool="hopemd",
    # One port taking either kind, and as many edges as there are branches: this is where the
    # tracks of a flow meet, and one batch of simulations comes out of all of them.
    inputs=[Port("structures", "poses or complexes", ["poses", "complexes"], many=True)],
    outputs=[Port("trajectories", "trajectories", ["trajectories"])],
    settings=[
        # How many to simulate is the one setting that decides what a flow costs, so it is asked
        # for. Everything arriving here is already ranked by the tool that made it; this takes
        # that many from the top of each track.
        Setting("top_n", "Simulate the best of what arrives", "number", 10, needed=True,
                why="per track. Each one is a full simulation, so this is what the flow costs"),
        Setting("engine", "Engine", "choice", "amber",
                choices=["amber", "openmm", "gromacs", "namd", "desmond"], needed=True),
        Setting("length_ns", "Length, ns", "number", 100, needed=True,
                why="production, per replicate"),
        Setting("frames", "Frames to keep", "number", 500, optional=True,
                why="over the whole production; the interval between them follows from this"),
        Setting("replicates", "Replicates", "number", 3, optional=True,
                why="independent repeats, each with its own seed"),
        Setting("mmgbsa", "Binding energy by MM-GBSA", "yesno", True, optional=True),
        # A flow that runs overnight should leave something to read in the morning. Neither of
        # these is made by a run on its own: they are asked for afterwards, from the Runs screen,
        # which is a person pressing buttons on twenty runs. Asked for here, the flow does it.
        Setting("report", "Write each run's report when it finishes", "yesno", True,
                optional=True, advanced=True),
        Setting("videos", "Make each run's videos when it finishes", "yesno", False,
                optional=True, advanced=True, why="a job of its own per run, cut from the trajectory"),
        Setting("temperature_K", "Temperature, K", "number", 300, optional=True, advanced=True),
        Setting("pressure_bar", "Pressure, bar", "number", 1.0, optional=True, advanced=True),
        Setting("timestep_fs", "Timestep, fs", "number", 4.0, optional=True, advanced=True,
                why="4 fs means hydrogen mass repartitioning"),
        Setting("equil_ps", "Equilibration, ps", "number", 1000, optional=True, advanced=True,
                why="over the restraint ladder"),
        Setting("heat_ps", "Heating, ps", "number", 200, optional=True, advanced=True),
        Setting("minimise_steps", "Minimisation steps", "number", 5000, optional=True,
                advanced=True),
        Setting("seed", "Random seed", "number", -1, optional=True, advanced=True,
                why="-1 lets each replicate pick its own"),
        Setting("water", "Water", "choice", "", choices=["", "OPC", "TIP3P", "TIP4P-Ew", "SPC"],
                optional=True, advanced=True, why="empty takes the engine's usual"),
        Setting("protein", "Protein force field", "choice", "",
                choices=["", "ff19SB", "ff14SB"], optional=True, advanced=True),
        Setting("walltime", "Walltime", "text", "", optional=True, advanced=True,
                why="empty takes the estimate's"),
        Setting("partition", "Partition", "text", "", optional=True, advanced=True),
        Setting("account", "Account to charge", "text", "", optional=True, advanced=True),
    ])

CARDS = (TARGET, PIPELINES, BINDCRAFT, RFDIFFUSION, BOLTZGEN, APTAMER, ADCP, HOPEMD)
BY_KEY = {c.key: c for c in CARDS}


#: What the shape of a catalogue means. Raised when a card gains something the rules below have
#: to understand - a new kind, a new sort of port - not when a card is added or a setting changes.
#: A launcher reading a catalogue newer than it understands keeps its own rather than guessing.
RULES = 1


def catalogue():
    """Every card, for the canvas, and for a launcher that takes its cards from the cluster."""
    return {"rules": RULES, "kinds": KINDS, "dockable_max_length": DOCKABLE_MAX_LENGTH,
            "linker_families": LINKER_FAMILIES, "cards": [c.as_json() for c in CARDS]}


def adopt(doc):
    """Replace the cards with the ones in this catalogue. Returns what was adopted, or "".

    This is what lets a card added on the cluster appear in a launcher built before it. The cards
    are data - their names, sockets, kinds and settings - while the rules about what may be linked
    to what are code, and the code stays in the launcher. So a new card, a new setting or a
    reworded line reaches people without another download, and a change to the rules themselves
    does not pretend to.

    Anything unreadable leaves the built-in cards exactly as they were.
    """
    global CARDS, BY_KEY, KINDS, DOCKABLE_MAX_LENGTH, LINKER_FAMILIES
    try:
        if not isinstance(doc, dict) or not doc.get("cards"):
            return ""
        if int(doc.get("rules", 1)) > RULES:
            return ""                      # written for rules this launcher does not have
        made = [_card_from(c) for c in doc["cards"]]
        if not made or not any(c.key == "target" for c in made):
            return ""                      # no target card: not a catalogue worth having
    except Exception:                                           # noqa: BLE001
        return ""
    CARDS = tuple(made)
    BY_KEY = {c.key: c for c in CARDS}
    if isinstance(doc.get("kinds"), dict) and doc["kinds"]:
        KINDS = dict(doc["kinds"])
    if isinstance(doc.get("linker_families"), dict) and doc["linker_families"]:
        LINKER_FAMILIES = dict(doc["linker_families"])
    try:
        DOCKABLE_MAX_LENGTH = int(doc.get("dockable_max_length") or DOCKABLE_MAX_LENGTH)
    except (TypeError, ValueError):
        pass
    return "%d cards" % len(CARDS)


def _card_from(d):
    return Card(d["key"], d.get("name") or d["key"], d.get("tagline", ""),
                tool=d.get("tool", ""), note=d.get("note", ""), ready=bool(d.get("ready", True)),
                inputs=[_port_from(p) for p in d.get("inputs", [])],
                outputs=[_port_from(p) for p in d.get("outputs", [])],
                settings=[_setting_from(x) for x in d.get("settings", [])])


def _port_from(d):
    return Port(d["key"], d.get("label") or d["key"], d.get("kinds") or [],
                required=bool(d.get("required", True)), many=bool(d.get("many")),
                sized=bool(d.get("sized")))


def _setting_from(d):
    return Setting(d["key"], d.get("label") or d["key"], d.get("kind", "text"),
                   default=d.get("default"), choices=d.get("choices") or (),
                   why=d.get("why", ""), optional=bool(d.get("optional")),
                   needed=bool(d.get("needed")), advanced=bool(d.get("advanced")))


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
        # Where the same card has another socket that would fit, say which. Two sockets a few
        # pixels apart, one of which is the one wanted, is the likeliest reason anybody is
        # reading this at all.
        instead = next((p.label for p in a.outputs
                        if p.key != from_port and any(into.takes(k) for k in p.kinds)), "")
        return ("%s carries %s, and %s takes %s.%s"
                % (out.label, " or ".join(KINDS[k] for k in out.kinds), into.label,
                   " or ".join(KINDS[k] for k in into.kinds),
                   (" Try %s instead." % instead) if instead else ""))
    return ""


def link_warning(from_card, from_port, to_card, to_port, settings=None):
    """What is worth saying about a link that is allowed anyway, or "" when there is nothing.

    Length is a caution rather than a refusal. What the target card asks for is what the design
    tool will aim at, not what it will produce, and a person who shortens the binder afterwards
    should not have to draw the link again to be let through. The run decides: designs that are
    short enough are docked and the rest are left behind by name, which is what the record shows.
    """
    a, b = BY_KEY.get(from_card), BY_KEY.get(to_card)
    if a is None or b is None:
        return ""
    out = a.port_out(from_port)
    if out is None or not out.sized or b.key != "adcp":
        return ""
    longest = (settings or {}).get("binder_max")
    try:
        longest = int(longest)
    except (TypeError, ValueError):
        return ""
    if longest > DOCKABLE_MAX_LENGTH:
        return ("the docking takes peptides of %d residues or fewer, and this flow asks for "
                "binders of up to %d. Designs longer than %d will be left behind rather than "
                "docked; shorten the binder, or simulate them directly instead."
                % (DOCKABLE_MAX_LENGTH, longest, DOCKABLE_MAX_LENGTH))
    return ""
