"""The pages for the two design tools that had none: RFdiffusion and BoltzGen.

By Aadhil Haq

Five of the lab's tools are a web page already and HOPE Labs only starts them. These two were
not. They were installed, and a flow was the only way the lab ran them, which meant drawing a
graph to do one thing. The page they were missing is here, in the launcher's own repository
rather than in the tool it drives, for two reasons: the code that queues them is here
(hope_flow/drivers.py) and a page must call that code rather than a copy of it, and neither
install is ours to put a server inside.

One page serves both. The two tools are the same shape, as hope_flow/cards.py says of them: a
target in, a binder placed on it out. What differs between them is their card, so the form is
drawn from the card and the page itself knows nothing about either tool. That is also what keeps
the page and the canvas offering the same settings with the same defaults, because there is one
description of them and both read it.

    python -m hope_labs.pages.serve rfdiffusion --host 127.0.0.1 --port 8130

It serves on a login node, where the queue and the RCSB are, and prints the line the launcher
reads to know it is up (hope_labs/tools.py, URL_LINE). --dry-run writes the run folder, fetches
the target and writes the job script without queueing it, which is how the page is worked on
without asking for an A100 for twelve hours.
"""
from __future__ import annotations

#: The tools this page can serve, which is the one thing a caller has to name. Each is a card in
#: hope_flow/cards.py and a tool in hope_labs/tools.py under the same key, and the page refuses
#: anything else rather than drawing an empty form from a card that is not there.
SERVES = ("rfdiffusion", "boltzgen")

#: Settings a tool's card offers that its submitter does not read yet, so the form leaves them
#: out. The form is otherwise the card, field for field, and a control that changed nothing would
#: be worse than one that is not offered: somebody would set it, watch a twelve-hour run, and
#: conclude the setting did nothing to the science rather than nothing at all.
#:
#: rfdiffusion.mpnn_relax is the only one. drivers._rfdiffusion does not put it in the plan and
#: helpers/rfdiffusion_design.py does not read it; relaxing a design needs dl_binder_design's
#: own interface script, and that needs a PyRosetta licence the lab's install has not got.
CARD_ONLY = {
    "rfdiffusion": ("mpnn_relax",),
    "boltzgen": (),
}
